"""Integration tests for TmuxManager with a real tmux server."""

import shutil

import pytest

from ccbot.tmux_manager import TmuxManager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed"),
]

TEST_SESSION = "ccbot-test-integration"


@pytest.fixture()
async def tmux(tmp_path):
    mgr = TmuxManager(session_name=TEST_SESSION)
    mgr.get_or_create_session()
    yield mgr
    session = mgr.get_session()
    if session:
        session.kill()


async def test_create_and_list_windows(tmux, tmp_path) -> None:
    ok, _msg, name, window_id = await tmux.create_window(
        str(tmp_path), window_name="test-win", start_agent=False
    )
    assert ok
    assert name == "test-win"
    assert window_id.startswith("@")

    windows = await tmux.list_windows()
    ids = [w.window_id for w in windows]
    assert window_id in ids

    match = next(w for w in windows if w.window_id == window_id)
    assert match.window_name == "test-win"


async def test_find_window_by_id(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="find-me", start_agent=False
    )
    assert ok

    found = await tmux.find_window_by_id(window_id)
    assert found is not None
    assert found.window_name == "find-me"

    missing = await tmux.find_window_by_id("@99999")
    assert missing is None


async def test_send_keys_and_capture_pane(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="echo-win", start_agent=False
    )
    assert ok

    await tmux.send_keys(window_id, "echo hello-integration")
    import asyncio

    await asyncio.sleep(0.5)

    output = await tmux.capture_pane(window_id)
    assert output is not None
    assert "hello-integration" in output


async def test_kill_window(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="kill-me", start_agent=False
    )
    assert ok

    killed = await tmux.kill_window(window_id)
    assert killed is True

    windows = await tmux.list_windows()
    ids = [w.window_id for w in windows]
    assert window_id not in ids


async def test_reset_server_reconnects(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="reset-test", start_agent=False
    )
    assert ok

    tmux._reset_server()

    windows = await tmux.list_windows()
    ids = [w.window_id for w in windows]
    assert window_id in ids


async def test_capture_pane_raw_returns_tuple(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="raw-test", start_agent=False
    )
    assert ok

    # Send something so pane has content (empty panes return None)
    await tmux.send_keys(window_id, "echo raw-test-output")
    import asyncio

    await asyncio.sleep(0.5)

    result = await tmux.capture_pane_raw(window_id)
    assert result is not None
    content, cols, rows = result
    assert isinstance(content, str)
    assert "raw-test-output" in content
    assert cols > 0
    assert rows > 0


async def test_get_pane_title(tmux, tmp_path) -> None:
    ok, _msg, _name, window_id = await tmux.create_window(
        str(tmp_path), window_name="title-test", start_agent=False
    )
    assert ok

    title = await tmux.get_pane_title(window_id)
    assert isinstance(title, str)
