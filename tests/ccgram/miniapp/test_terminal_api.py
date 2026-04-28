import asyncio
import json

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from ccgram.miniapp import build_app, sign_token
from ccgram.miniapp.api.terminal import (
    DEFAULT_POLL_INTERVAL,
    MAX_FRAME_BYTES,
    register_terminal_routes,
)

BOT = "1234:abcdef"
WINDOW_ID = "ccgram:@7"


class FakePane:
    """Capture stub returning a queue of frames; blocks once exhausted."""

    def __init__(self, frames: list[str | None]):
        self.frames = list(frames)
        self.calls: list[str] = []

    async def __call__(self, window_id: str) -> str | None:
        self.calls.append(window_id)
        if self.frames:
            return self.frames.pop(0)
        # Idle forever — keeps the websocket alive between assertions.
        await asyncio.sleep(0.5)
        return None


def _make_app(capture, *, interval: float = 0.05) -> web.Application:
    app = web.Application()
    register_terminal_routes(
        app, bot_token=BOT, capture=capture, poll_interval=interval
    )
    return app


@pytest.fixture
async def app_client():
    capture = FakePane(["screen one", "screen one", "screen two"])
    app = _make_app(capture, interval=0.05)
    async with TestClient(TestServer(app)) as c:
        yield c, capture


async def _read_one(ws, *, timeout: float = 1.0) -> dict:
    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
    assert msg.type == WSMsgType.TEXT, f"unexpected ws msg type {msg.type}"
    return json.loads(msg.data)


async def test_websocket_rejects_invalid_token(app_client):
    c, _ = app_client
    resp = await c.get("/ws/terminal/garbage")
    assert resp.status == 403


async def test_websocket_rejects_token_for_other_bot(app_client):
    c, _ = app_client
    tok = sign_token(bot_token="9999:other", window_id=WINDOW_ID, user_id=1)
    resp = await c.get(f"/ws/terminal/{tok}")
    assert resp.status == 403


async def test_websocket_streams_hello_then_frame(app_client):
    c, capture = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
        hello = await _read_one(ws)
        assert hello["type"] == "hello"
        assert hello["window_id"] == WINDOW_ID
        assert hello["interval"] == pytest.approx(0.05)

        frame = await _read_one(ws)
        assert frame["type"] == "frame"
        assert frame["text"] == "screen one"
        assert frame["hash"]
        await ws.close()

    # First frame plus possibly a couple of poll calls.
    assert capture.calls and capture.calls[0] == WINDOW_ID


async def test_websocket_dedupes_unchanged_frames(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
        hello = await _read_one(ws)
        assert hello["type"] == "hello"

        frame_a = await _read_one(ws)
        assert frame_a["type"] == "frame"
        assert frame_a["text"] == "screen one"

        # The next pane capture returns identical text — no new frame should
        # arrive within a short window. The third capture flips text and
        # produces "screen two".
        frame_b = await _read_one(ws, timeout=2.0)
        assert frame_b["type"] == "frame"
        assert frame_b["text"] == "screen two"
        assert frame_b["hash"] != frame_a["hash"]
        await ws.close()


async def test_websocket_disconnect_stops_capture():
    capture = FakePane(["a", "b", "c", "d", "e", "f"])
    app = _make_app(capture, interval=0.05)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
            await _read_one(ws)  # hello
            await _read_one(ws)  # first frame
            await ws.close()
        # Drain in-flight tick, then snapshot call count.
        await asyncio.sleep(0.05)
        baseline = len(capture.calls)
        # No further captures should fire after the socket is closed.
        await asyncio.sleep(0.1)
        assert len(capture.calls) == baseline


async def test_websocket_capture_failure_emits_error_then_continues():
    class ExplodingThenFine:
        def __init__(self):
            self.calls = 0

        async def __call__(self, _window_id: str) -> str | None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return "ok"

    capture = ExplodingThenFine()
    app = _make_app(capture, interval=0.05)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
            await _read_one(ws)  # hello
            err = await _read_one(ws, timeout=1.0)
            assert err["type"] == "error"
            assert "capture failed" in err["message"]
            frame = await _read_one(ws, timeout=1.0)
            assert frame["type"] == "frame"
            assert frame["text"] == "ok"
            await ws.close()


async def test_websocket_truncates_oversized_frame():
    huge = "x" * (MAX_FRAME_BYTES + 1024)
    capture = FakePane([huge])
    app = _make_app(capture, interval=0.05)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
            await _read_one(ws)  # hello
            frame = await _read_one(ws)
            assert frame["type"] == "frame"
            assert len(frame["text"].encode("utf-8")) <= MAX_FRAME_BYTES
            await ws.close()


async def test_websocket_handles_none_capture_as_empty():
    capture = FakePane([None])
    app = _make_app(capture, interval=0.05)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        async with c.ws_connect(f"/ws/terminal/{tok}") as ws:
            await _read_one(ws)  # hello
            frame = await _read_one(ws)
            assert frame["type"] == "frame"
            assert frame["text"] == ""
            await ws.close()


def test_register_clamps_low_poll_interval():
    app = _make_app(FakePane([]), interval=0.0001)
    # Stash key uses module-private AppKey but we can still iterate values.
    intervals = [v for k, v in app.items() if isinstance(v, float)]
    assert intervals
    assert min(intervals) >= 0.05


def test_default_poll_interval_constant():
    assert DEFAULT_POLL_INTERVAL == 0.2


async def test_build_app_includes_terminal_route():
    app = build_app(bot_token=BOT, terminal_capture=FakePane(["hello"]))
    routes = {
        getattr(r.resource, "canonical", str(r.resource)) for r in app.router.routes()
    }
    assert any("/ws/terminal" in r for r in routes)
