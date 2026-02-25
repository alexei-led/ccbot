"""Tests for hook event dispatcher."""

import pytest

from ccbot.handlers.hook_events import (
    HookEvent,
    _active_subagents,
    _resolve_users_for_window_key,
    clear_subagents,
    dispatch_hook_event,
    get_subagent_count,
)


class TestResolveUsersForWindowKey:
    def test_extracts_window_id(self, monkeypatch) -> None:
        bindings = [
            (111, 42, "@0"),
            (222, 99, "@5"),
        ]
        monkeypatch.setattr(
            "ccbot.handlers.hook_events.session_manager.iter_thread_bindings",
            lambda: iter(bindings),
        )
        result = _resolve_users_for_window_key("ccbot:@0")
        assert result == [(111, 42, "@0")]

    def test_no_match(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ccbot.handlers.hook_events.session_manager.iter_thread_bindings",
            lambda: iter([]),
        )
        result = _resolve_users_for_window_key("ccbot:@99")
        assert result == []

    def test_invalid_key_format(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ccbot.handlers.hook_events.session_manager.iter_thread_bindings",
            lambda: iter([]),
        )
        result = _resolve_users_for_window_key("nocolon")
        assert result == []


class TestSubagentTracking:
    def setup_method(self) -> None:
        _active_subagents.clear()

    def test_start_increments_count(self) -> None:
        _active_subagents["@0"] = [{"subagent_id": "a1"}]
        assert get_subagent_count("@0") == 1

    def test_clear_removes_all(self) -> None:
        _active_subagents["@0"] = [{"subagent_id": "a1"}, {"subagent_id": "a2"}]
        clear_subagents("@0")
        assert get_subagent_count("@0") == 0

    def test_count_missing_window(self) -> None:
        assert get_subagent_count("@999") == 0


@pytest.mark.asyncio
class TestDispatchHookEvent:
    async def test_unknown_event_ignored(self) -> None:
        event = HookEvent(
            event_type="SomeUnknownEvent",
            window_key="ccbot:@0",
            session_id="test-id",
            data={},
            timestamp=0.0,
        )
        await dispatch_hook_event(event, None)  # type: ignore[arg-type]
