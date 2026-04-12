from unittest.mock import AsyncMock, MagicMock, patch

from ccgram.handlers.screenshot_callbacks import (
    _send_toolbar_key,
    build_toolbar_keyboard,
)


class TestBuildToolbarKeyboardRow1:
    def test_row1_has_4_buttons_for_all_providers(self):
        for provider in ["claude", "codex", "gemini", "shell"]:
            kb = build_toolbar_keyboard("@0", provider)
            row1 = kb.inline_keyboard[0]
            assert len(row1) == 4, f"row1 has {len(row1)} buttons for {provider}"

    def test_row1_labels_universal(self):
        for provider in ["claude", "codex", "gemini", "shell"]:
            kb = build_toolbar_keyboard("@0", provider)
            labels = [b.text for b in kb.inline_keyboard[0]]
            assert "Screenshot" in labels[0]
            assert "Ctrl-C" in labels[1]
            assert "Live" in labels[2]
            assert "Send" in labels[3]

    def test_row1_callback_data_contains_window_id(self):
        kb = build_toolbar_keyboard("@5", "claude")
        for btn in kb.inline_keyboard[0]:
            cb = btn.callback_data
            assert isinstance(cb, str) and "@5" in cb


class TestBuildToolbarKeyboardRow2:
    def test_claude_row2(self):
        kb = build_toolbar_keyboard("@0", "claude")
        labels = [b.text for b in kb.inline_keyboard[1]]
        assert "Mode" in labels[0]
        assert "Think" in labels[1]
        assert "Esc" in labels[2]
        assert "Close" in labels[3]

    def test_codex_row2(self):
        kb = build_toolbar_keyboard("@0", "codex")
        labels = [b.text for b in kb.inline_keyboard[1]]
        assert "Esc" in labels[0]
        assert "Enter" in labels[1]
        assert "Tab" in labels[2]
        assert "Close" in labels[3]

    def test_gemini_row2(self):
        kb = build_toolbar_keyboard("@0", "gemini")
        labels = [b.text for b in kb.inline_keyboard[1]]
        assert "Mode" in labels[0]
        assert "YOLO" in labels[1]
        assert "Esc" in labels[2]
        assert "Close" in labels[3]

    def test_shell_row2(self):
        kb = build_toolbar_keyboard("@0", "shell")
        labels = [b.text for b in kb.inline_keyboard[1]]
        assert "Enter" in labels[0]
        assert "EOF" in labels[1]
        assert "Susp" in labels[2]
        assert "Close" in labels[3]

    def test_unknown_provider_defaults_to_claude(self):
        kb = build_toolbar_keyboard("@0", "unknown_thing")
        labels = [b.text for b in kb.inline_keyboard[1]]
        assert "Mode" in labels[0]

    def test_has_exactly_2_rows(self):
        for provider in ["claude", "codex", "gemini", "shell"]:
            kb = build_toolbar_keyboard("@0", provider)
            assert len(kb.inline_keyboard) == 2, (
                f"{provider} has {len(kb.inline_keyboard)} rows"
            )

    def test_row2_has_4_buttons(self):
        for provider in ["claude", "codex", "gemini", "shell"]:
            kb = build_toolbar_keyboard("@0", provider)
            assert len(kb.inline_keyboard[1]) == 4


class TestSendToolbarKey:
    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_mode_sends_shift_tab(self, mock_tmux, _mock_owns):
        query = AsyncMock()
        await _send_toolbar_key(
            query, 123, "tb:mode:@0", "tb:mode:", "\x1b[Z", "Mode", literal=True
        )
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "\x1b[Z"
        assert mock_tmux.send_keys.call_args[1]["literal"] is True

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_regular_key_not_literal(self, mock_tmux, _mock_owns):
        query = AsyncMock()
        await _send_toolbar_key(query, 123, "tb:esc:@0", "tb:esc:", "Escape", "Esc")
        assert mock_tmux.send_keys.call_args[1]["literal"] is False

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=False)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_not_owner_rejected(self, mock_tmux, _mock_owns):
        query = AsyncMock()
        await _send_toolbar_key(query, 123, "tb:esc:@0", "tb:esc:", "Escape", "Esc")
        mock_tmux.send_keys.assert_not_called()
        query.answer.assert_awaited_once_with("Not your session", show_alert=True)

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_window_not_found(self, mock_tmux, _mock_owns):
        mock_tmux.find_window_by_id.return_value = None
        query = AsyncMock()
        await _send_toolbar_key(query, 123, "tb:eof:@0", "tb:eof:", "C-d", "^D")
        mock_tmux.send_keys.assert_not_called()


class TestHandleToolbarSend:
    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=False)
    async def test_not_owner_rejected(self, _mock_owns):
        query = AsyncMock()
        query.data = "tb:send:@0"
        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_send

        await _handle_toolbar_send(query, 123, "tb:send:@0", update, context)
        query.answer.assert_awaited_once_with("Not your session", show_alert=True)

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.session_manager")
    async def test_no_cwd_shows_error(self, mock_sm, _mock_owns):
        mock_sm.get_window_state.return_value = None
        query = AsyncMock()
        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_send

        await _handle_toolbar_send(query, 123, "tb:send:@0", update, context)
        query.answer.assert_awaited_once_with(
            "Working directory not available", show_alert=True
        )

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.thread_router")
    @patch("ccgram.handlers.screenshot_callbacks.session_manager")
    @patch("ccgram.handlers.screenshot_callbacks.safe_send", new_callable=AsyncMock)
    @patch("ccgram.handlers.screenshot_callbacks.build_file_browser")
    async def test_opens_file_browser(
        self, mock_browser, mock_safe_send, mock_sm, mock_router, _mock_owns, tmp_path
    ):
        ws = MagicMock()
        ws.cwd = str(tmp_path)
        mock_sm.get_window_state.return_value = ws
        mock_router.resolve_chat_id.return_value = 999
        mock_browser.return_value = ("Browse files", MagicMock(), [tmp_path / "a.txt"])

        query = AsyncMock()
        update = MagicMock()
        update.effective_message.message_thread_id = 42
        context = MagicMock()
        context.user_data = {}
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_send

        with patch(
            "ccgram.handlers.screenshot_callbacks.get_thread_id", return_value=42
        ):
            await _handle_toolbar_send(query, 123, "tb:send:@0", update, context)

        mock_safe_send.assert_awaited_once()
        call_kwargs = mock_safe_send.call_args
        assert call_kwargs[0][1] == 999
        assert call_kwargs[1]["message_thread_id"] == 42
        query.answer.assert_awaited_once_with()
