"""Tests for handlers/toolbar_callbacks — keyboard build + dispatch + state readback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.callback_data import CB_TOOLBAR
from ccgram.handlers.toolbar_callbacks import (
    _parse_callback_data,
    build_toolbar_keyboard,
    handle_toolbar_callback,
    reload_toolbar_config,
)
from ccgram.toolbar_config import (
    BUILTIN_ACTIONS,
    DEFAULT_LAYOUTS,
    ToolbarAction,
    ToolbarConfig,
    ToolbarLayout,
)


@pytest.fixture(autouse=True)
def _fresh_toolbar_config():
    """Force-reload before each test so config state doesn't leak."""
    reload_toolbar_config()
    yield
    reload_toolbar_config()


# ──────────────────────────────────────────────────────────────────────
# build_toolbar_keyboard
# ──────────────────────────────────────────────────────────────────────


class TestBuildToolbarKeyboard:
    @pytest.mark.parametrize("provider", ["claude", "codex", "gemini", "shell"])
    def test_default_grid_is_3x3(self, provider: str) -> None:
        kb = build_toolbar_keyboard("@5", provider)
        assert len(kb.inline_keyboard) == 3
        for row in kb.inline_keyboard:
            assert len(row) == 3

    @pytest.mark.parametrize("provider", ["claude", "codex", "gemini", "shell"])
    def test_callback_data_uses_single_prefix(self, provider: str) -> None:
        kb = build_toolbar_keyboard("@5", provider)
        for row in kb.inline_keyboard:
            for btn in row:
                cb = btn.callback_data
                assert isinstance(cb, str)
                assert cb.startswith(CB_TOOLBAR)
                # tb:@5:<name>
                assert ":@5:" in cb

    def test_unknown_provider_falls_back_to_claude(self) -> None:
        kb_default = build_toolbar_keyboard("@1", "claude")
        kb_unknown = build_toolbar_keyboard("@1", "aider")
        labels_default = [[b.text for b in row] for row in kb_default.inline_keyboard]
        labels_unknown = [[b.text for b in row] for row in kb_unknown.inline_keyboard]
        assert labels_default == labels_unknown

    def test_emoji_text_style_renders_emoji_and_text(self) -> None:
        kb = build_toolbar_keyboard("@1", "claude")
        first = kb.inline_keyboard[0][0]
        assert "Screen" in first.text
        assert "\U0001f4f7" in first.text


class TestBuildToolbarKeyboardCustom:
    def test_text_style_renders_text_only(self) -> None:
        custom_layout = ToolbarLayout(
            style="text",
            buttons=(("ctrlc", "esc"),),
        )
        custom_cfg = ToolbarConfig(
            layouts={"claude": custom_layout},
            actions=dict(BUILTIN_ACTIONS),
        )
        with patch(
            "ccgram.handlers.toolbar_callbacks._get_toolbar_config",
            return_value=custom_cfg,
        ):
            kb = build_toolbar_keyboard("@7", "claude")
        assert kb.inline_keyboard[0][0].text == "Ctrl-C"
        assert kb.inline_keyboard[0][1].text == "Esc"

    def test_emoji_style_renders_emoji_only(self) -> None:
        custom_layout = ToolbarLayout(
            style="emoji",
            buttons=(("ctrlc",),),
        )
        custom_cfg = ToolbarConfig(
            layouts={"claude": custom_layout},
            actions=dict(BUILTIN_ACTIONS),
        )
        with patch(
            "ccgram.handlers.toolbar_callbacks._get_toolbar_config",
            return_value=custom_cfg,
        ):
            kb = build_toolbar_keyboard("@7", "claude")
        assert kb.inline_keyboard[0][0].text == "\u23f9"


# ──────────────────────────────────────────────────────────────────────
# _parse_callback_data
# ──────────────────────────────────────────────────────────────────────


class TestParseCallbackData:
    def test_simple_window_id(self) -> None:
        assert _parse_callback_data("tb:@5:mode") == ("@5", "mode")

    def test_foreign_window_id_with_colon(self) -> None:
        # Foreign window IDs contain colons. action_name is after the LAST colon.
        assert _parse_callback_data("tb:emdash-x:@0:close") == (
            "emdash-x:@0",
            "close",
        )

    def test_missing_prefix_returns_none(self) -> None:
        assert _parse_callback_data("foo:bar") is None

    def test_no_colon_returns_none(self) -> None:
        assert _parse_callback_data("tb:") is None


# ──────────────────────────────────────────────────────────────────────
# Dispatch — common test helpers
# ──────────────────────────────────────────────────────────────────────


def _make_query(data: str) -> AsyncMock:
    query = AsyncMock()
    query.data = data
    query.answer = AsyncMock()
    query.delete_message = AsyncMock()
    query.get_bot = MagicMock(return_value=MagicMock())
    return query


def _make_update_with_user(user_id: int = 100) -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock(id=user_id)
    update.effective_chat = MagicMock(id=-100, type="supergroup")
    update.effective_message = MagicMock(message_thread_id=42)
    return update


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


# ──────────────────────────────────────────────────────────────────────
# Dispatch — key actions
# ──────────────────────────────────────────────────────────────────────


class TestDispatchKey:
    async def test_key_action_sends_tmux_key(self) -> None:
        query = _make_query("tb:@5:esc")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.find_window_by_id = AsyncMock(
                return_value=MagicMock(window_id="@5")
            )
            mock_tmux.send_keys = AsyncMock()
            await handle_toolbar_callback(query, 100, "tb:@5:esc", update, context)
        mock_tmux.send_keys.assert_awaited_once_with(
            "@5", "Escape", enter=False, literal=False
        )
        query.answer.assert_awaited_once()

    async def test_mode_action_uses_literal_true(self) -> None:
        query = _make_query("tb:@5:mode")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
            patch(
                "ccgram.handlers.toolbar_callbacks._scrape_mode_toast",
                new=AsyncMock(return_value="auto-accept edits"),
            ),
        ):
            mock_tmux.find_window_by_id = AsyncMock(
                return_value=MagicMock(window_id="@5")
            )
            mock_tmux.send_keys = AsyncMock()
            await handle_toolbar_callback(query, 100, "tb:@5:mode", update, context)
        mock_tmux.send_keys.assert_awaited_once_with(
            "@5", "\x1b[Z", enter=False, literal=True
        )
        query.answer.assert_awaited_once_with("auto-accept edits")

    async def test_window_not_found_alerts(self) -> None:
        query = _make_query("tb:@5:esc")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.find_window_by_id = AsyncMock(return_value=None)
            await handle_toolbar_callback(query, 100, "tb:@5:esc", update, context)
        query.answer.assert_awaited_once_with("Window not found", show_alert=True)


# ──────────────────────────────────────────────────────────────────────
# Dispatch — text actions
# ──────────────────────────────────────────────────────────────────────


class TestDispatchText:
    async def test_text_action_sends_with_enter_literal(self) -> None:
        clear_action = ToolbarAction(
            name="clear",
            emoji="\U0001f9f9",
            text="Clear",
            action_type="text",
            payload="/clear",
        )
        custom_cfg = ToolbarConfig(
            layouts=dict(DEFAULT_LAYOUTS),
            actions={**BUILTIN_ACTIONS, "clear": clear_action},
        )
        query = _make_query("tb:@5:clear")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks._get_toolbar_config",
                return_value=custom_cfg,
            ),
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.find_window_by_id = AsyncMock(
                return_value=MagicMock(window_id="@5")
            )
            mock_tmux.send_keys = AsyncMock()
            await handle_toolbar_callback(query, 100, "tb:@5:clear", update, context)
        mock_tmux.send_keys.assert_awaited_once_with(
            "@5", "/clear", enter=True, literal=True
        )
        query.answer.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────
# Dispatch — builtin actions
# ──────────────────────────────────────────────────────────────────────


class TestDispatchBuiltinCtrlc:
    async def test_sends_ctrl_c(self) -> None:
        query = _make_query("tb:@5:ctrlc")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.find_window_by_id = AsyncMock(
                return_value=MagicMock(window_id="@5")
            )
            mock_tmux.send_keys = AsyncMock()
            await handle_toolbar_callback(query, 100, "tb:@5:ctrlc", update, context)
        mock_tmux.send_keys.assert_awaited_once_with(
            "@5", "C-c", enter=False, literal=False
        )


class TestDispatchBuiltinDismiss:
    async def test_deletes_message(self) -> None:
        query = _make_query("tb:@5:close")
        update = _make_update_with_user()
        context = _make_context()
        with patch(
            "ccgram.handlers.toolbar_callbacks.user_owns_window",
            return_value=True,
        ):
            await handle_toolbar_callback(query, 100, "tb:@5:close", update, context)
        query.delete_message.assert_awaited_once()


class TestDispatchBuiltinSend:
    async def test_no_cwd_alerts(self) -> None:
        query = _make_query("tb:@5:send")
        update = _make_update_with_user()
        context = _make_context()
        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.user_owns_window",
                return_value=True,
            ),
            patch("ccgram.handlers.toolbar_callbacks.session_manager") as mock_sm,
        ):
            mock_sm.view_window.return_value = None
            await handle_toolbar_callback(query, 100, "tb:@5:send", update, context)
        query.answer.assert_awaited_once_with(
            "Working directory not available", show_alert=True
        )


# ──────────────────────────────────────────────────────────────────────
# Dispatch — error paths
# ──────────────────────────────────────────────────────────────────────


class TestDispatchErrorPaths:
    async def test_bad_callback_data_format(self) -> None:
        query = _make_query("notb:foo")
        update = _make_update_with_user()
        context = _make_context()
        await handle_toolbar_callback(query, 100, "notb:foo", update, context)
        query.answer.assert_awaited_once_with("Bad toolbar callback", show_alert=True)

    async def test_ownership_rejection(self) -> None:
        query = _make_query("tb:@5:esc")
        update = _make_update_with_user()
        context = _make_context()
        with patch(
            "ccgram.handlers.toolbar_callbacks.user_owns_window",
            return_value=False,
        ):
            await handle_toolbar_callback(query, 100, "tb:@5:esc", update, context)
        query.answer.assert_awaited_once_with("Not your session", show_alert=True)

    async def test_unknown_action_alerts(self) -> None:
        query = _make_query("tb:@5:doesnotexist")
        update = _make_update_with_user()
        context = _make_context()
        with patch(
            "ccgram.handlers.toolbar_callbacks.user_owns_window",
            return_value=True,
        ):
            await handle_toolbar_callback(
                query, 100, "tb:@5:doesnotexist", update, context
            )
        call_args = query.answer.call_args
        assert call_args is not None
        assert "doesnotexist" in call_args.args[0]
        assert call_args.kwargs.get("show_alert") is True


# ──────────────────────────────────────────────────────────────────────
# State readback (Mode/Think/YOLO)
# ──────────────────────────────────────────────────────────────────────


class TestStateReadback:
    async def test_scrape_returns_mode_line_when_found(self) -> None:
        from ccgram.handlers.toolbar_callbacks import _scrape_mode_toast

        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.capture_pane = AsyncMock(
                return_value="some output\n? auto-accept edits on (shift+tab to cycle)\n? prompt"
            )
            result = await _scrape_mode_toast("@5", "fallback")
        assert "auto-accept edits" in result

    async def test_scrape_falls_back_when_no_mode_line(self) -> None:
        from ccgram.handlers.toolbar_callbacks import _scrape_mode_toast

        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.capture_pane = AsyncMock(
                return_value="just some random terminal output"
            )
            result = await _scrape_mode_toast("@5", "fallback")
        assert result == "fallback"

    async def test_scrape_falls_back_when_capture_empty(self) -> None:
        from ccgram.handlers.toolbar_callbacks import _scrape_mode_toast

        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.capture_pane = AsyncMock(return_value="")
            result = await _scrape_mode_toast("@5", "fb")
        assert result == "fb"

    async def test_scrape_falls_back_when_capture_raises(self) -> None:
        from ccgram.handlers.toolbar_callbacks import _scrape_mode_toast

        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.capture_pane = AsyncMock(side_effect=OSError("boom"))
            result = await _scrape_mode_toast("@5", "fb")
        assert result == "fb"

    async def test_scrape_strips_ansi(self) -> None:
        from ccgram.handlers.toolbar_callbacks import _scrape_mode_toast

        with (
            patch(
                "ccgram.handlers.toolbar_callbacks.asyncio.sleep",
                new=AsyncMock(),
            ),
            patch("ccgram.handlers.toolbar_callbacks.tmux_manager") as mock_tmux,
        ):
            mock_tmux.capture_pane = AsyncMock(
                return_value="\x1b[1;33mPlan mode\x1b[0m on"
            )
            result = await _scrape_mode_toast("@5", "fb")
        assert "Plan mode" in result
