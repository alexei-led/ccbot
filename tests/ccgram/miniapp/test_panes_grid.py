import asyncio
import json

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from ccgram.miniapp import build_app, sign_token
from ccgram.miniapp.api.terminal import register_terminal_routes

from ._helpers import make_init_data

BOT = "1234:abcdef"
WINDOW_ID = "ccgram:@7"


def _init_headers(*, user_id: int = 42) -> dict[str, str]:
    return {"X-Telegram-Init-Data": make_init_data(bot_token=BOT, user_id=user_id)}


async def _ws_authenticate(ws, *, user_id: int = 42) -> None:
    await ws.send_json({"init_data": make_init_data(bot_token=BOT, user_id=user_id)})


def _pane(pane_id, *, active=False, name=None, state="idle", subscribed=False):
    return {
        "pane_id": pane_id,
        "index": int(pane_id.lstrip("%")) if pane_id.startswith("%") else 0,
        "active": active,
        "command": "claude",
        "width": 80,
        "height": 24,
        "name": name,
        "state": state,
        "subscribed": subscribed,
    }


class FakePaneList:
    def __init__(self, panes_by_window):
        self._panes = panes_by_window
        self.calls: list[str] = []

    async def __call__(self, window_id):
        self.calls.append(window_id)
        return list(self._panes.get(window_id, []))


class FakePaneCapture:
    """Per-(window, pane) capture stub returning preset frames or blocking."""

    def __init__(self, frames_by_pane):
        self._frames = {k: list(v) for k, v in frames_by_pane.items()}
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, window_id, pane_id):
        self.calls.append((window_id, pane_id))
        q = self._frames.get(pane_id)
        if q:
            return q.pop(0)
        await asyncio.sleep(0.5)
        return None


class FakeActiveCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls: list[str] = []

    async def __call__(self, window_id):
        self.calls.append(window_id)
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(0.5)
        return None


def _make_app(*, pane_list=None, pane_capture=None, active_capture=None, interval=0.05):
    app = web.Application()
    register_terminal_routes(
        app,
        bot_token=BOT,
        capture=active_capture or FakeActiveCapture([]),
        pane_capture=pane_capture or FakePaneCapture({}),
        pane_list=pane_list or FakePaneList({}),
        poll_interval=interval,
    )
    return app


async def _read_one(ws, *, timeout=1.0):
    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
    assert msg.type == WSMsgType.TEXT
    return json.loads(msg.data)


async def test_panes_endpoint_rejects_invalid_token():
    app = _make_app()
    async with TestClient(TestServer(app)) as c:
        resp = await c.get("/api/panes/garbage")
        assert resp.status == 403


async def test_panes_endpoint_rejects_token_for_other_bot():
    panes = FakePaneList({WINDOW_ID: [_pane("%5", active=True)]})
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        bad = sign_token(bot_token="9999:other", window_id=WINDOW_ID, user_id=1)
        resp = await c.get(f"/api/panes/{bad}", headers=_init_headers())
        assert resp.status == 403


async def test_panes_endpoint_rejects_missing_init_data_header():
    panes = FakePaneList({WINDOW_ID: [_pane("%5", active=True)]})
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}")
        assert resp.status == 403


async def test_panes_endpoint_returns_one_pane():
    panes = FakePaneList({WINDOW_ID: [_pane("%5", active=True, name="api")]})
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        assert resp.status == 200
        data = await resp.json()
        assert data["window_id"] == WINDOW_ID
        assert len(data["panes"]) == 1
        assert data["panes"][0]["pane_id"] == "%5"
        assert data["panes"][0]["name"] == "api"
        assert data["panes"][0]["active"] is True


async def test_panes_endpoint_returns_two_panes():
    panes = FakePaneList(
        {
            WINDOW_ID: [
                _pane("%5", active=True, name="api"),
                _pane("%6", active=False, name="db", state="idle"),
            ]
        }
    )
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        assert resp.status == 200
        data = await resp.json()
        assert [p["pane_id"] for p in data["panes"]] == ["%5", "%6"]


async def test_panes_endpoint_returns_four_panes():
    layout = [
        _pane("%5", active=True, name="api"),
        _pane("%6", active=False, name="db"),
        _pane("%7", active=False, name="frontend"),
        _pane("%8", active=False, name="logs", state="blocked"),
    ]
    panes = FakePaneList({WINDOW_ID: layout})
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        data = await resp.json()
        assert [p["pane_id"] for p in data["panes"]] == ["%5", "%6", "%7", "%8"]
        # Blocked state preserved end-to-end.
        assert data["panes"][3]["state"] == "blocked"


async def test_panes_endpoint_handles_lister_failure():
    class Boom:
        async def __call__(self, _wid):
            raise RuntimeError("tmux gone")

    app = _make_app(pane_list=Boom())
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        assert resp.status == 500
        body = await resp.json()
        assert body["error"] == "list failed"


async def test_websocket_streams_specific_pane_when_query_set():
    pane_capture = FakePaneCapture({"%6": ["pane six frame"]})
    active = FakeActiveCapture(["should-not-be-read"])
    app = _make_app(active_capture=active, pane_capture=pane_capture)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}?pane=%256") as ws:
            await _ws_authenticate(ws)
            hello = await _read_one(ws)
            assert hello["type"] == "hello"
            assert hello["pane_id"] == "%6"
            frame = await _read_one(ws)
            assert frame["type"] == "frame"
            assert frame["text"] == "pane six frame"
            await ws.close()
        # Active-pane capture must not be called when ?pane is set.
        assert active.calls == []
        assert pane_capture.calls and pane_capture.calls[0] == (WINDOW_ID, "%6")


async def test_websocket_falls_back_to_active_pane_when_query_missing():
    active = FakeActiveCapture(["active-frame"])
    pane_capture = FakePaneCapture({})
    app = _make_app(active_capture=active, pane_capture=pane_capture)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
            await _ws_authenticate(ws)
            hello = await _read_one(ws)
            assert hello["pane_id"] is None
            frame = await _read_one(ws)
            assert frame["text"] == "active-frame"
            await ws.close()
        assert active.calls and active.calls[0] == WINDOW_ID
        assert pane_capture.calls == []


async def test_websocket_per_pane_capture_failure_emits_error():
    class ExplodingPane:
        def __init__(self):
            self.calls = 0

        async def __call__(self, _wid, _pid):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("pane gone")
            return "recovered"

    pane_capture = ExplodingPane()
    app = _make_app(pane_capture=pane_capture)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}?pane=%255") as ws:
            await _ws_authenticate(ws)
            await _read_one(ws)  # hello
            err = await _read_one(ws)
            assert err["type"] == "error"
            frame = await _read_one(ws)
            assert frame["type"] == "frame"
            assert frame["text"] == "recovered"
            await ws.close()


async def test_subscription_lifecycle_per_pane_disconnect_stops_capture():
    pane_capture = FakePaneCapture({"%5": ["frame-a", "frame-a", "frame-b"]})
    app = _make_app(pane_capture=pane_capture)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}?pane=%255") as ws:
            await _ws_authenticate(ws)
            await _read_one(ws)  # hello
            await _read_one(ws)  # frame
            await ws.close()
        await asyncio.sleep(0.05)
        baseline = len(pane_capture.calls)
        await asyncio.sleep(0.1)
        assert len(pane_capture.calls) == baseline


async def test_build_app_includes_panes_route():
    app = build_app(bot_token=BOT)
    routes = {
        getattr(r.resource, "canonical", str(r.resource)) for r in app.router.routes()
    }
    assert any("/api/panes" in r for r in routes)


async def test_panes_endpoint_empty_window():
    app = _make_app(pane_list=FakePaneList({WINDOW_ID: []}))
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        assert resp.status == 200
        data = await resp.json()
        assert data["panes"] == []


async def test_panes_endpoint_window_isolation():
    """Token for window A must not be able to read panes for window B."""
    panes = FakePaneList(
        {
            "ccgram:@1": [_pane("%1")],
            "ccgram:@2": [_pane("%2")],
        }
    )
    app = _make_app(pane_list=panes)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id="ccgram:@1", user_id=42)
        resp = await c.get(f"/api/panes/{tok}", headers=_init_headers())
        data = await resp.json()
        assert [p["pane_id"] for p in data["panes"]] == ["%1"]
        assert panes.calls == ["ccgram:@1"]
