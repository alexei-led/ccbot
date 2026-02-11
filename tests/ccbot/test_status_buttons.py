"""Tests for status message inline action buttons (Esc, Screenshot)."""

from ccbot.handlers.callback_data import CB_STATUS_ESC, CB_STATUS_SCREENSHOT
from ccbot.handlers.message_queue import _build_status_keyboard


class TestBuildStatusKeyboard:
    def test_has_esc_button(self) -> None:
        kb = _build_status_keyboard("@0")
        data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any(d.startswith(CB_STATUS_ESC) for d in data)

    def test_has_screenshot_button(self) -> None:
        kb = _build_status_keyboard("@0")
        data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any(d.startswith(CB_STATUS_SCREENSHOT) for d in data)

    def test_window_id_in_callback_data(self) -> None:
        kb = _build_status_keyboard("@42")
        data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert f"{CB_STATUS_ESC}@42" in data
        assert f"{CB_STATUS_SCREENSHOT}@42" in data

    def test_callback_data_truncated_to_64_bytes(self) -> None:
        long_id = "@" + "x" * 60  # prefix + id > 64 bytes
        kb = _build_status_keyboard(long_id)
        for row in kb.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data) == 64
                assert btn.callback_data.startswith(
                    CB_STATUS_ESC
                ) or btn.callback_data.startswith(CB_STATUS_SCREENSHOT)
