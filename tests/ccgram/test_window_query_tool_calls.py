from __future__ import annotations

import pytest

from ccgram.window_query import get_tool_call_visibility, is_tool_calls_hidden
from ccgram.window_state_store import WindowState, window_store


@pytest.fixture(autouse=True)
def _isolate_store():
    saved = dict(window_store.window_states)
    window_store.window_states.clear()
    yield
    window_store.window_states.clear()
    window_store.window_states.update(saved)


class TestGetToolCallVisibility:
    def test_no_state_returns_default(self):
        assert get_tool_call_visibility("@404") == "default"

    @pytest.mark.parametrize("mode", ["default", "shown", "hidden"])
    def test_returns_stored_mode(self, mode: str):
        window_store.window_states["@0"] = WindowState(tool_call_visibility=mode)
        assert get_tool_call_visibility("@0") == mode

    def test_invalid_value_falls_back_to_default(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="garbage")
        assert get_tool_call_visibility("@0") == "default"


class TestIsToolCallsHidden:
    def test_hidden_overrides_global_false(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="hidden")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = False
            assert is_tool_calls_hidden("@0") is True
        finally:
            config.hide_tool_calls = original

    def test_hidden_overrides_global_true(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="hidden")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = True
            assert is_tool_calls_hidden("@0") is True
        finally:
            config.hide_tool_calls = original

    def test_shown_overrides_global_true(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="shown")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = True
            assert is_tool_calls_hidden("@0") is False
        finally:
            config.hide_tool_calls = original

    def test_shown_overrides_global_false(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="shown")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = False
            assert is_tool_calls_hidden("@0") is False
        finally:
            config.hide_tool_calls = original

    def test_default_falls_through_to_global_true(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="default")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = True
            assert is_tool_calls_hidden("@0") is True
        finally:
            config.hide_tool_calls = original

    def test_default_falls_through_to_global_false(self):
        window_store.window_states["@0"] = WindowState(tool_call_visibility="default")
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = False
            assert is_tool_calls_hidden("@0") is False
        finally:
            config.hide_tool_calls = original

    def test_no_state_falls_through_to_global(self):
        from ccgram.config import config

        original = config.hide_tool_calls
        try:
            config.hide_tool_calls = True
            assert is_tool_calls_hidden("@missing") is True
            config.hide_tool_calls = False
            assert is_tool_calls_hidden("@missing") is False
        finally:
            config.hide_tool_calls = original
