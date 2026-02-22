"""Tests for status polling: shell detection, autoclose timers, rename sync,
activity heuristic, and startup timeout."""

import time

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import make_mock_provider

from ccbot.handlers.status_polling import (
    _autoclose_timers,
    _check_autoclose_timers,
    _check_transcript_activity,
    _clear_autoclose_if_active,
    _has_seen_status,
    _start_autoclose_timer,
    _startup_times,
    clear_autoclose_timer,
    is_shell_prompt,
    reset_autoclose_state,
    reset_seen_status_state,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_autoclose_state()
    reset_seen_status_state()
    yield
    reset_autoclose_state()
    reset_seen_status_state()


class TestIsShellPrompt:
    @pytest.mark.parametrize(
        "cmd",
        ["bash", "zsh", "fish", "sh", "/usr/bin/zsh", "  bash  ", "dash", "ksh"],
    )
    def test_shell_detected(self, cmd: str) -> None:
        assert is_shell_prompt(cmd) is True

    @pytest.mark.parametrize("cmd", ["node", "claude", "npx", ""])
    def test_non_shell_rejected(self, cmd: str) -> None:
        assert is_shell_prompt(cmd) is False


class TestAutocloseTimers:
    def test_start_timer(self) -> None:
        _start_autoclose_timer(1, 42, "done", 100.0)
        assert _autoclose_timers[(1, 42)] == ("done", 100.0)

    def test_start_timer_preserves_existing_same_state(self) -> None:
        _start_autoclose_timer(1, 42, "done", 100.0)
        _start_autoclose_timer(1, 42, "done", 200.0)
        assert _autoclose_timers[(1, 42)] == ("done", 100.0)

    def test_start_timer_resets_on_state_change(self) -> None:
        _start_autoclose_timer(1, 42, "done", 100.0)
        _start_autoclose_timer(1, 42, "dead", 200.0)
        assert _autoclose_timers[(1, 42)] == ("dead", 200.0)

    def test_clear_on_active(self) -> None:
        _start_autoclose_timer(1, 42, "done", 100.0)
        _clear_autoclose_if_active(1, 42)
        assert (1, 42) not in _autoclose_timers

    def test_clear_timer(self) -> None:
        _start_autoclose_timer(1, 42, "done", 100.0)
        clear_autoclose_timer(1, 42)
        assert (1, 42) not in _autoclose_timers

    def test_clear_nonexistent_is_noop(self) -> None:
        clear_autoclose_timer(1, 42)

    @pytest.mark.parametrize(
        ("state", "minutes", "elapsed"),
        [("done", 30, 30 * 60 + 1), ("dead", 10, 10 * 60 + 1)],
        ids=["done", "dead"],
    )
    async def test_check_expired(
        self, state: str, minutes: int, elapsed: float
    ) -> None:
        _start_autoclose_timer(1, 42, state, 0.0)
        bot = AsyncMock()
        with (
            patch("ccbot.handlers.status_polling.config") as mock_config,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_config.autoclose_done_minutes = 30
            mock_config.autoclose_dead_minutes = minutes
            mock_time.monotonic.return_value = elapsed
            mock_sm.resolve_chat_id.return_value = -100
            await _check_autoclose_timers(bot)
        bot.close_forum_topic.assert_called_once_with(
            chat_id=-100, message_thread_id=42
        )
        assert (1, 42) not in _autoclose_timers

    async def test_check_not_expired_yet(self) -> None:
        _start_autoclose_timer(1, 42, "done", 0.0)
        bot = AsyncMock()
        with (
            patch("ccbot.handlers.status_polling.config") as mock_config,
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_config.autoclose_done_minutes = 30
            mock_config.autoclose_dead_minutes = 10
            mock_time.monotonic.return_value = 29 * 60
            await _check_autoclose_timers(bot)
        bot.close_forum_topic.assert_not_called()
        assert (1, 42) in _autoclose_timers

    async def test_check_disabled_when_zero(self) -> None:
        _start_autoclose_timer(1, 42, "done", 0.0)
        bot = AsyncMock()
        with (
            patch("ccbot.handlers.status_polling.config") as mock_config,
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_config.autoclose_done_minutes = 0
            mock_config.autoclose_dead_minutes = 0
            mock_time.monotonic.return_value = 999999
            await _check_autoclose_timers(bot)
        bot.close_forum_topic.assert_not_called()

    async def test_check_telegram_error_handled(self) -> None:
        from telegram.error import TelegramError

        _start_autoclose_timer(1, 42, "done", 0.0)
        bot = AsyncMock()
        bot.close_forum_topic.side_effect = TelegramError("fail")
        with (
            patch("ccbot.handlers.status_polling.config") as mock_config,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_config.autoclose_done_minutes = 30
            mock_config.autoclose_dead_minutes = 10
            mock_time.monotonic.return_value = 30 * 60 + 1
            mock_sm.resolve_chat_id.return_value = -100
            await _check_autoclose_timers(bot)
        assert (1, 42) not in _autoclose_timers


class TestWindowRenameSync:
    async def test_rename_detected_calls_rename_topic(self) -> None:
        with (
            patch("ccbot.handlers.status_polling.tmux_manager") as mock_tm,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji"),
            patch("ccbot.handlers.status_polling.enqueue_status_update"),
            patch(
                "ccbot.handlers.status_polling.get_interactive_window",
                return_value=None,
            ),
            patch(
                "ccbot.handlers.status_polling.get_provider_for_window",
                return_value=make_mock_provider(has_status=True),
            ),
            patch("ccbot.handlers.status_polling.rename_topic") as mock_rename,
        ):
            from ccbot.handlers.status_polling import update_status_message

            mock_window = MagicMock()
            mock_window.window_id = "@0"
            mock_window.window_name = "new-name"
            mock_window.pane_current_command = "node"
            mock_tm.find_window_by_id = AsyncMock(return_value=mock_window)
            mock_tm.capture_pane = AsyncMock(return_value="some output")
            mock_tm.get_pane_title = AsyncMock(return_value="")
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "old-name"

            bot = AsyncMock()
            await update_status_message(bot, 1, "@0", thread_id=42)

            mock_sm.set_display_name.assert_called_once_with("@0", "new-name")
            mock_rename.assert_called_once_with(bot, -100, 42, "new-name")

    async def test_no_rename_when_names_match(self) -> None:
        with (
            patch("ccbot.handlers.status_polling.tmux_manager") as mock_tm,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji"),
            patch("ccbot.handlers.status_polling.enqueue_status_update"),
            patch(
                "ccbot.handlers.status_polling.get_interactive_window",
                return_value=None,
            ),
            patch(
                "ccbot.handlers.status_polling.get_provider_for_window",
                return_value=make_mock_provider(has_status=True),
            ),
            patch("ccbot.handlers.status_polling.rename_topic") as mock_rename,
        ):
            from ccbot.handlers.status_polling import update_status_message

            mock_window = MagicMock()
            mock_window.window_id = "@0"
            mock_window.window_name = "myproject"
            mock_window.pane_current_command = "node"
            mock_tm.find_window_by_id = AsyncMock(return_value=mock_window)
            mock_tm.capture_pane = AsyncMock(return_value="some output")
            mock_tm.get_pane_title = AsyncMock(return_value="")
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "myproject"

            bot = AsyncMock()
            await update_status_message(bot, 1, "@0", thread_id=42)

            mock_sm.set_display_name.assert_not_called()
            mock_rename.assert_not_called()


class TestTranscriptActivityHeuristic:
    def test_active_when_recent_transcript(self) -> None:
        now = time.monotonic()
        mock_monitor = MagicMock()
        mock_monitor.get_last_activity.return_value = now - 5.0
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch(
                "ccbot.handlers.status_polling.get_active_monitor",
                return_value=mock_monitor,
            ),
        ):
            mock_sm.get_session_id_for_window.return_value = "sess-123"
            result = _check_transcript_activity("@0", now)
        assert result is True
        assert "@0" in _has_seen_status

    def test_inactive_when_stale_transcript(self) -> None:
        now = time.monotonic()
        mock_monitor = MagicMock()
        mock_monitor.get_last_activity.return_value = now - 20.0
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch(
                "ccbot.handlers.status_polling.get_active_monitor",
                return_value=mock_monitor,
            ),
        ):
            mock_sm.get_session_id_for_window.return_value = "sess-123"
            result = _check_transcript_activity("@0", now)
        assert result is False
        assert "@0" not in _has_seen_status

    def test_inactive_when_no_session(self) -> None:
        now = time.monotonic()
        with patch("ccbot.handlers.status_polling.session_manager") as mock_sm:
            mock_sm.get_session_id_for_window.return_value = None
            result = _check_transcript_activity("@0", now)
        assert result is False

    def test_inactive_when_no_monitor(self) -> None:
        now = time.monotonic()
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch(
                "ccbot.handlers.status_polling.get_active_monitor",
                return_value=None,
            ),
        ):
            mock_sm.get_session_id_for_window.return_value = "sess-123"
            result = _check_transcript_activity("@0", now)
        assert result is False

    def test_clears_startup_timer_on_activity(self) -> None:
        now = time.monotonic()
        _startup_times["@0"] = now - 15.0
        mock_monitor = MagicMock()
        mock_monitor.get_last_activity.return_value = now - 3.0
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch(
                "ccbot.handlers.status_polling.get_active_monitor",
                return_value=mock_monitor,
            ),
        ):
            mock_sm.get_session_id_for_window.return_value = "sess-123"
            result = _check_transcript_activity("@0", now)
        assert result is True
        assert "@0" not in _startup_times


class TestStartupTimeout:
    async def test_first_poll_records_startup_time(self) -> None:
        from ccbot.handlers.status_polling import _handle_no_status

        bot = AsyncMock()
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji"),
            patch("ccbot.handlers.status_polling._send_typing_throttled"),
            patch(
                "ccbot.handlers.status_polling._check_transcript_activity",
                return_value=False,
            ),
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1000.0
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "project"
            await _handle_no_status(bot, 1, "@0", 42, "node", "normal")
        assert "@0" in _startup_times

    async def test_startup_timeout_transitions_to_idle(self) -> None:
        from ccbot.handlers.status_polling import _handle_no_status

        bot = AsyncMock()
        _startup_times["@0"] = 1000.0
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji") as mock_emoji,
            patch("ccbot.handlers.status_polling.enqueue_status_update"),
            patch(
                "ccbot.handlers.status_polling._check_transcript_activity",
                return_value=False,
            ),
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1000.0 + 31.0
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "project"
            await _handle_no_status(bot, 1, "@0", 42, "node", "normal")
        assert "@0" in _has_seen_status
        assert "@0" not in _startup_times
        mock_emoji.assert_called_once_with(bot, -100, 42, "idle", "project")

    async def test_startup_grace_period_sends_typing(self) -> None:
        from ccbot.handlers.status_polling import _handle_no_status

        bot = AsyncMock()
        _startup_times["@0"] = 1000.0
        with (
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji") as mock_emoji,
            patch(
                "ccbot.handlers.status_polling._send_typing_throttled"
            ) as mock_typing,
            patch(
                "ccbot.handlers.status_polling._check_transcript_activity",
                return_value=False,
            ),
            patch("ccbot.handlers.status_polling.time") as mock_time,
        ):
            mock_time.monotonic.return_value = 1010.0
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "project"
            await _handle_no_status(bot, 1, "@0", 42, "node", "normal")
        mock_typing.assert_called_once_with(bot, 1, 42)
        mock_emoji.assert_called_once_with(bot, -100, 42, "active", "project")
        assert "@0" not in _has_seen_status


class TestParseWithPyte:
    """Tests for pyte-based screen parsing integration."""

    def setup_method(self) -> None:
        from ccbot.handlers.status_polling import reset_screen_buffer_state

        reset_screen_buffer_state()

    def teardown_method(self) -> None:
        from ccbot.handlers.status_polling import reset_screen_buffer_state

        reset_screen_buffer_state()

    def test_detects_spinner_status(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte

        sep = "─" * 30
        pane_text = f"Some output\n✻ Reading file src/main.py\n{sep}\n"
        result = _parse_with_pyte("@0", pane_text)
        assert result is not None
        assert result.raw_text == "Reading file src/main.py"
        assert result.display_label == "…reading"
        assert result.is_interactive is False

    def test_detects_braille_spinner(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte

        sep = "─" * 30
        pane_text = f"Output\n⠋ Thinking about things\n{sep}\n"
        result = _parse_with_pyte("@0", pane_text)
        assert result is not None
        assert result.raw_text == "Thinking about things"
        assert result.is_interactive is False

    def test_detects_interactive_ui(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte

        pane_text = (
            "  Would you like to proceed?\n"
            "  ─────────────────────────────────\n"
            "  Yes     No\n"
            "  ─────────────────────────────────\n"
            "  ctrl-g to edit in vim\n"
        )
        result = _parse_with_pyte("@0", pane_text)
        assert result is not None
        assert result.is_interactive is True
        assert result.ui_type == "ExitPlanMode"

    def test_returns_none_for_plain_text(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte

        pane_text = "$ echo hello\nhello\n$\n"
        result = _parse_with_pyte("@0", pane_text)
        assert result is None

    def test_screen_buffer_cached_per_window(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte, _screen_buffers

        sep = "─" * 30
        pane_text = f"Output\n✻ Working\n{sep}\n"
        _parse_with_pyte("@0", pane_text)
        assert "@0" in _screen_buffers

        _parse_with_pyte("@1", pane_text)
        assert "@1" in _screen_buffers
        assert "@0" in _screen_buffers

    def test_interactive_takes_precedence_over_status(self) -> None:
        from ccbot.handlers.status_polling import _parse_with_pyte

        sep = "─" * 30
        pane_text = (
            f"✻ Working on task\n{sep}\n"
            "  Do you want to proceed?\n"
            "  Allow write to /tmp/foo\n"
            "  Esc to cancel\n"
        )
        result = _parse_with_pyte("@0", pane_text)
        assert result is not None
        assert result.is_interactive is True
        assert result.ui_type == "PermissionPrompt"


class TestPyteFallbackInUpdateStatus:
    """Tests that update_status_message falls back to regex when pyte returns None."""

    async def test_falls_back_to_provider_when_pyte_returns_none(self) -> None:
        with (
            patch("ccbot.handlers.status_polling.tmux_manager") as mock_tm,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji"),
            patch("ccbot.handlers.status_polling.enqueue_status_update"),
            patch(
                "ccbot.handlers.status_polling.get_interactive_window",
                return_value=None,
            ),
            patch(
                "ccbot.handlers.status_polling.get_provider_for_window",
                return_value=make_mock_provider(has_status=True),
            ) as mock_get_provider,
            patch(
                "ccbot.handlers.status_polling._parse_with_pyte",
                return_value=None,
            ),
        ):
            from ccbot.handlers.status_polling import update_status_message

            mock_window = MagicMock()
            mock_window.window_id = "@0"
            mock_window.window_name = "project"
            mock_window.pane_current_command = "node"
            mock_tm.find_window_by_id = AsyncMock(return_value=mock_window)
            mock_tm.capture_pane = AsyncMock(return_value="some output")
            mock_tm.get_pane_title = AsyncMock(return_value="")
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "project"
            mock_sm.get_notification_mode.return_value = "normal"

            bot = AsyncMock()
            await update_status_message(bot, 1, "@0", thread_id=42)

            # Provider regex parsing was called as fallback
            mock_get_provider.return_value.parse_terminal_status.assert_called_once()

    async def test_uses_pyte_result_when_available(self) -> None:
        from ccbot.providers.base import StatusUpdate

        pyte_status = StatusUpdate(
            raw_text="Reading file",
            display_label="…reading",
        )
        with (
            patch("ccbot.handlers.status_polling.tmux_manager") as mock_tm,
            patch("ccbot.handlers.status_polling.session_manager") as mock_sm,
            patch("ccbot.handlers.status_polling.update_topic_emoji"),
            patch(
                "ccbot.handlers.status_polling.enqueue_status_update"
            ) as mock_enqueue,
            patch(
                "ccbot.handlers.status_polling.get_interactive_window",
                return_value=None,
            ),
            patch(
                "ccbot.handlers.status_polling.get_provider_for_window",
                return_value=make_mock_provider(has_status=True),
            ) as mock_get_provider,
            patch(
                "ccbot.handlers.status_polling._parse_with_pyte",
                return_value=pyte_status,
            ),
        ):
            from ccbot.handlers.status_polling import update_status_message

            mock_window = MagicMock()
            mock_window.window_id = "@0"
            mock_window.window_name = "project"
            mock_window.pane_current_command = "node"
            mock_tm.find_window_by_id = AsyncMock(return_value=mock_window)
            mock_tm.capture_pane = AsyncMock(return_value="some output")
            mock_tm.get_pane_title = AsyncMock(return_value="")
            mock_sm.resolve_chat_id.return_value = -100
            mock_sm.get_display_name.return_value = "project"
            mock_sm.get_notification_mode.return_value = "normal"

            bot = AsyncMock()
            await update_status_message(bot, 1, "@0", thread_id=42)

            # Provider regex parsing was NOT called (pyte succeeded)
            mock_get_provider.return_value.parse_terminal_status.assert_not_called()
            # Status was enqueued using pyte result
            mock_enqueue.assert_called_once()
            call_args = mock_enqueue.call_args
            assert call_args[0][3] == "…reading"
