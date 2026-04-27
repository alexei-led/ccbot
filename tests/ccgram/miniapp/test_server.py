import pytest
from aiohttp.test_utils import TestClient, TestServer

from ccgram.miniapp import build_app, sign_token

BOT = "1234:abcdef"


@pytest.fixture
async def client():
    app = build_app(bot_token=BOT)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_healthz_open(client: TestClient):
    resp = await client.get("/healthz")
    assert resp.status == 200
    assert (await resp.text()) == "ok"


async def test_app_route_with_valid_token(client: TestClient):
    tok = sign_token(bot_token=BOT, window_id="ccgram:@5", user_id=99)
    resp = await client.get(f"/app/{tok}")
    assert resp.status == 200
    body = await resp.text()
    assert 'name="ccgram-payload"' in body
    assert 'data-window-id="ccgram:@5"' in body
    assert 'data-user-id="99"' in body
    assert resp.headers["Content-Type"].startswith("text/html")


async def test_app_route_rejects_invalid_token(client: TestClient):
    resp = await client.get("/app/garbage")
    assert resp.status == 403


async def test_app_route_rejects_token_signed_for_other_bot(client: TestClient):
    tok = sign_token(bot_token="9999:other", window_id="@1", user_id=1)
    resp = await client.get(f"/app/{tok}")
    assert resp.status == 403


async def test_static_files_served(client: TestClient):
    # static/index.html exists; /static/index.html should serve it raw
    resp = await client.get("/static/index.html")
    assert resp.status == 200
    body = await resp.text()
    assert "<!DOCTYPE html>" in body


async def test_start_and_stop_server_roundtrip(unused_tcp_port: int):
    from ccgram.miniapp import start_server, stop_server

    runner = await start_server(bot_token=BOT, host="127.0.0.1", port=unused_tcp_port)
    try:
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://127.0.0.1:{unused_tcp_port}/healthz") as resp,
        ):
            assert resp.status == 200
    finally:
        await stop_server(runner)
