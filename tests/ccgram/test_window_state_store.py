from __future__ import annotations

import pytest

from ccgram.session import SessionManager
from ccgram.window_state_store import (
    DEFAULT_TOOL_CALL_VISIBILITY,
    TOOL_CALL_VISIBILITY_MODES,
    WindowState,
    window_store,
)


@pytest.fixture
def mgr(monkeypatch) -> SessionManager:
    monkeypatch.setattr(SessionManager, "_load_state", lambda self: None)
    monkeypatch.setattr(SessionManager, "_save_state", lambda self: None)
    window_store.window_states.clear()
    return SessionManager()


class TestToolCallVisibilityConstants:
    def test_modes_tuple(self):
        assert TOOL_CALL_VISIBILITY_MODES == ("default", "shown", "hidden")

    def test_default_value(self):
        assert DEFAULT_TOOL_CALL_VISIBILITY == "default"


class TestToolCallVisibilityStore:
    def test_get_default(self, mgr: SessionManager) -> None:
        assert mgr.get_tool_call_visibility("@0") == "default"

    def test_get_nonexistent_window(self, mgr: SessionManager) -> None:
        assert mgr.get_tool_call_visibility("@999") == "default"

    def test_set_valid(self, mgr: SessionManager) -> None:
        mgr.set_tool_call_visibility("@0", "hidden")
        assert mgr.get_tool_call_visibility("@0") == "hidden"
        mgr.set_tool_call_visibility("@0", "shown")
        assert mgr.get_tool_call_visibility("@0") == "shown"
        mgr.set_tool_call_visibility("@0", "default")
        assert mgr.get_tool_call_visibility("@0") == "default"

    def test_set_invalid_raises(self, mgr: SessionManager) -> None:
        with pytest.raises(ValueError, match="Invalid tool_call_visibility"):
            mgr.set_tool_call_visibility("@0", "bogus")

    @pytest.mark.parametrize(
        ("start", "expected"),
        [
            ("default", "shown"),
            ("shown", "hidden"),
            ("hidden", "default"),
        ],
    )
    def test_cycle(self, mgr: SessionManager, start: str, expected: str) -> None:
        mgr.set_tool_call_visibility("@0", start)
        assert mgr.cycle_tool_call_visibility("@0") == expected
        assert mgr.get_tool_call_visibility("@0") == expected

    def test_cycle_full_circle(self, mgr: SessionManager) -> None:
        assert mgr.cycle_tool_call_visibility("@1") == "shown"
        assert mgr.cycle_tool_call_visibility("@1") == "hidden"
        assert mgr.cycle_tool_call_visibility("@1") == "default"


class TestToolCallVisibilitySerialization:
    @pytest.mark.parametrize(
        ("mode", "expect_key"),
        [("default", False), ("shown", True), ("hidden", True)],
    )
    def test_to_dict(self, mode: str, expect_key: bool) -> None:
        ws = WindowState(session_id="s1", cwd="/tmp", tool_call_visibility=mode)
        d = ws.to_dict()
        if expect_key:
            assert d["tool_call_visibility"] == mode
        else:
            assert "tool_call_visibility" not in d

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            ({"session_id": "s1", "cwd": "/tmp"}, "default"),
            (
                {"session_id": "s1", "cwd": "/tmp", "tool_call_visibility": "shown"},
                "shown",
            ),
            (
                {"session_id": "s1", "cwd": "/tmp", "tool_call_visibility": "hidden"},
                "hidden",
            ),
        ],
    )
    def test_from_dict(self, data: dict[str, str], expected: str) -> None:
        assert WindowState.from_dict(data).tool_call_visibility == expected

    @pytest.mark.parametrize("mode", list(TOOL_CALL_VISIBILITY_MODES))
    def test_roundtrip(self, mode: str) -> None:
        ws = WindowState(session_id="s1", cwd="/tmp", tool_call_visibility=mode)
        assert WindowState.from_dict(ws.to_dict()).tool_call_visibility == mode
