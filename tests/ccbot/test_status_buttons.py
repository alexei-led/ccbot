"""Tests for status message inline action buttons (Esc, Screenshot, Notify)."""

from unittest.mock import patch

import pytest

from ccbot.handlers.callback_data import (
    CB_STATUS_ESC,
    CB_STATUS_NOTIFY,
    CB_STATUS_SCREENSHOT,
    NOTIFY_MODE_ICONS,
)
from ccbot.handlers.message_queue import build_status_keyboard


def _all_callback_data(window_id: str) -> list[str]:
    kb = build_status_keyboard(window_id)
    return [btn.callback_data for row in kb.inline_keyboard for btn in row]


class TestBuildStatusKeyboard:
    @pytest.mark.parametrize(
        "prefix", [CB_STATUS_ESC, CB_STATUS_SCREENSHOT, CB_STATUS_NOTIFY]
    )
    def test_has_button_with_prefix(self, prefix: str) -> None:
        assert any(d.startswith(prefix) for d in _all_callback_data("@0"))

    def test_window_id_in_callback_data(self) -> None:
        data = _all_callback_data("@42")
        assert f"{CB_STATUS_ESC}@42" in data
        assert f"{CB_STATUS_SCREENSHOT}@42" in data
        assert f"{CB_STATUS_NOTIFY}@42" in data

    def test_callback_data_truncated_to_64_bytes(self) -> None:
        long_id = "@" + "x" * 60
        kb = build_status_keyboard(long_id)
        prefixes = (CB_STATUS_ESC, CB_STATUS_SCREENSHOT, CB_STATUS_NOTIFY)
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data) == 64
                assert any(btn.callback_data.startswith(p) for p in prefixes)

    @pytest.mark.parametrize(("mode", "expected_icon"), list(NOTIFY_MODE_ICONS.items()))
    def test_bell_icon_reflects_notification_mode(
        self, mode: str, expected_icon: str
    ) -> None:
        with patch("ccbot.handlers.message_queue.session_manager") as mock_sm:
            mock_sm.get_notification_mode.return_value = mode
            kb = build_status_keyboard("@0")
            notify_btn = kb.inline_keyboard[0][2]
            assert notify_btn.text == expected_icon
