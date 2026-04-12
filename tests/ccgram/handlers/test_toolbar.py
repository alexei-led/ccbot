from unittest.mock import AsyncMock, patch

from ccgram.handlers.screenshot_callbacks import build_toolbar_keyboard


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


class TestToolbarKeyHandlers:
    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_mode_sends_shift_tab(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_mode

        query = AsyncMock()
        await _handle_toolbar_mode(query, 123, "tb:mode:@0")
        mock_tmux.send_keys.assert_called_once()
        call_args = mock_tmux.send_keys.call_args
        assert call_args[0][1] == "\x1b[Z"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_think_sends_tab(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_think

        query = AsyncMock()
        await _handle_toolbar_think(query, 123, "tb:think:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "Tab"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_yolo_sends_ctrl_y(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_yolo

        query = AsyncMock()
        await _handle_toolbar_yolo(query, 123, "tb:yolo:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "C-y"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_eof_sends_ctrl_d(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_eof

        query = AsyncMock()
        await _handle_toolbar_eof(query, 123, "tb:eof:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "C-d"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_suspend_sends_ctrl_z(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_suspend

        query = AsyncMock()
        await _handle_toolbar_suspend(query, 123, "tb:susp:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "C-z"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_esc_sends_escape(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_esc

        query = AsyncMock()
        await _handle_toolbar_esc(query, 123, "tb:esc:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "Escape"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_enter_sends_enter(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_enter

        query = AsyncMock()
        await _handle_toolbar_enter(query, 123, "tb:ent:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "Enter"

    @patch("ccgram.handlers.screenshot_callbacks.user_owns_window", return_value=True)
    @patch("ccgram.handlers.screenshot_callbacks.tmux_manager", new_callable=AsyncMock)
    async def test_tab_sends_tab(self, mock_tmux, _mock_owns):
        from ccgram.handlers.screenshot_callbacks import _handle_toolbar_tab

        query = AsyncMock()
        await _handle_toolbar_tab(query, 123, "tb:tab:@0")
        mock_tmux.send_keys.assert_called_once()
        assert mock_tmux.send_keys.call_args[0][1] == "Tab"
