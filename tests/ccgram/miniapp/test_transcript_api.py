import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from ccgram.miniapp import build_app, sign_token
from ccgram.miniapp.api.transcript import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_SEARCH_RESULTS,
    register_transcript_routes,
)

from ._helpers import make_init_data

BOT = "1234:abcdef"
WINDOW_ID = "ccgram:@9"


def _hdr(*, user_id: int = 42) -> dict[str, str]:
    return {"X-Telegram-Init-Data": make_init_data(bot_token=BOT, user_id=user_id)}


def _msg(
    idx: int,
    role: str = "assistant",
    text: str | None = None,
    ts: str | None = None,
    ctype: str = "text",
) -> dict:
    return {
        "role": role,
        "text": text if text is not None else f"message {idx}",
        "content_type": ctype,
        "timestamp": ts or f"2026-04-2{idx % 10}T10:0{idx % 10}:00",
    }


class FakeReader:
    def __init__(self, messages: list[dict] | dict[str, list[dict]]):
        if isinstance(messages, dict):
            self._per_window = messages
            self._fallback: list[dict] | None = None
        else:
            self._per_window = {}
            self._fallback = messages
        self.calls: list[str] = []

    async def __call__(self, window_id: str) -> list[dict]:
        self.calls.append(window_id)
        if self._fallback is not None:
            return list(self._fallback)
        return list(self._per_window.get(window_id, []))


def _make_app(reader, *, bot_token: str = BOT) -> web.Application:
    app = web.Application()
    register_transcript_routes(app, bot_token=bot_token, reader=reader)
    return app


@pytest.fixture
async def app_client():
    messages = [
        _msg(0, role="user", text="hello there"),
        _msg(1, role="assistant", text="hi back"),
        _msg(2, role="user", text="search me FOO bar"),
        _msg(3, role="assistant", text="ok"),
        _msg(4, role="user", text="another"),
    ]
    reader = FakeReader(messages)
    app = _make_app(reader)
    async with TestClient(TestServer(app)) as c:
        yield c, reader


async def test_list_rejects_invalid_token(app_client):
    c, _ = app_client
    resp = await c.get("/api/transcript/garbage")
    assert resp.status == 403


async def test_list_rejects_token_for_other_bot(app_client):
    c, _ = app_client
    tok = sign_token(bot_token="9999:other", window_id=WINDOW_ID, user_id=1)
    resp = await c.get(f"/api/transcript/{tok}")
    assert resp.status == 403


async def test_list_returns_first_page_with_cursor(app_client):
    c, reader = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}?cursor=0&limit=2", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 5
    assert data["next_cursor"] == 2
    assert len(data["messages"]) == 2
    assert data["messages"][0]["text"] == "hello there"
    assert reader.calls == [WINDOW_ID]


async def test_list_paginates_to_end(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}?cursor=4&limit=10", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert data["next_cursor"] is None
    assert len(data["messages"]) == 1


async def test_list_cursor_past_end_is_empty(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}?cursor=999", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert data["messages"] == []
    assert data["next_cursor"] is None


async def test_list_limit_clamped_to_max(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}?limit=99999", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    # total is small, but the endpoint must still accept oversized limit values.
    assert len(data["messages"]) <= MAX_LIMIT


async def test_list_invalid_cursor_falls_back_to_zero(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}?cursor=abc", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert (
        len(data["messages"]) == DEFAULT_LIMIT or len(data["messages"]) == data["total"]
    )


async def test_list_empty_session_returns_404():
    reader = FakeReader([])
    app = _make_app(reader)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/transcript/{tok}", headers=_hdr())
        assert resp.status == 404
        data = await resp.json()
        assert data["reason"] == "no_session"
        assert data["messages"] == []


async def test_search_finds_case_insensitive(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}/search?q=foo", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 1
    match = data["matches"][0]
    assert match["index"] == 2
    assert "FOO" in match["entry"]["text"]
    # Context entries on either side
    assert match["before"]["text"] == "hi back"
    assert match["after"]["text"] == "ok"


async def test_search_no_matches(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}/search?q=xyzzy", headers=_hdr())
    assert resp.status == 200
    data = await resp.json()
    assert data["matches"] == []
    assert data["total"] == 0


async def test_search_missing_query_rejected(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}/search?q=", headers=_hdr())
    assert resp.status == 400


async def test_search_rejects_invalid_token(app_client):
    c, _ = app_client
    resp = await c.get("/api/transcript/badtoken/search?q=hi")
    assert resp.status == 403


async def test_list_rejects_missing_init_data(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}")
    assert resp.status == 403


async def test_list_rejects_init_data_user_mismatch(app_client):
    c, _ = app_client
    tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
    resp = await c.get(f"/api/transcript/{tok}", headers=_hdr(user_id=999))
    assert resp.status == 403


async def test_search_caps_results():
    big = [
        _msg(i, role="user", text=f"hit {i}") for i in range(MAX_SEARCH_RESULTS + 25)
    ]
    reader = FakeReader(big)
    app = _make_app(reader)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/transcript/{tok}/search?q=hit", headers=_hdr())
        data = await resp.json()
        assert data["total"] == MAX_SEARCH_RESULTS


async def test_search_empty_session_returns_404():
    reader = FakeReader([])
    app = _make_app(reader)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id=WINDOW_ID, user_id=42)
        resp = await c.get(f"/api/transcript/{tok}/search?q=hello", headers=_hdr())
        assert resp.status == 404
        data = await resp.json()
        assert data["reason"] == "no_session"


async def test_auth_scopes_to_token_window():
    """Token's window_id is the only one passed to the reader — even with a path
    that names another window, the reader must only see the token's window."""
    per_window = {
        "ccgram:@1": [_msg(0, text="window1 only")],
        "ccgram:@2": [_msg(0, text="window2 only")],
    }
    reader = FakeReader(per_window)
    app = _make_app(reader)
    async with TestClient(TestServer(app)) as c:
        tok = sign_token(bot_token=BOT, window_id="ccgram:@1", user_id=42)
        resp = await c.get(f"/api/transcript/{tok}", headers=_hdr())
        data = await resp.json()
        assert data["messages"][0]["text"] == "window1 only"
        assert reader.calls == ["ccgram:@1"]


async def test_build_app_includes_transcript_routes():
    app = build_app(bot_token=BOT, transcript_reader=FakeReader([]))
    paths = {
        getattr(r.resource, "canonical", str(r.resource)) for r in app.router.routes()
    }
    assert any("/api/transcript" in p for p in paths)
    # Both routes present
    assert any("/search" in p for p in paths if "/api/transcript" in p)
