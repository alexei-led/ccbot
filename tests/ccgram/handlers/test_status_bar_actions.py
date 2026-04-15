from unittest.mock import ANY, AsyncMock, MagicMock, patch

from ccgram.handlers.callback_data import (
    CB_KEYS_PREFIX,
    CB_STATUS_ESC,
    CB_STATUS_NOTIFY,
    CB_STATUS_REMOTE,
)
from ccgram.handlers.status_bar_actions import _handle_status_bar_action

MOD = "ccgram.handlers.status_bar_actions"


def _q() -> AsyncMock:
    q = AsyncMock()
    q.answer = AsyncMock()
    q.edit_message_reply_markup = AsyncMock()
    q.get_bot = MagicMock(return_value=AsyncMock())
    return q


class TestNotifyToggle:
    async def test_cycles_mode_and_updates_keyboard(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch(f"{MOD}.session_manager") as sm,
            patch(
                "ccgram.handlers.status_bubble.build_status_keyboard",
                return_value=MagicMock(),
            ) as bsk,
        ):
            sm.cycle_notification_mode.return_value = "mentions"
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_NOTIFY}@0", MagicMock(), MagicMock()
            )
        sm.cycle_notification_mode.assert_called_once_with("@0")
        bsk.assert_called_once_with("@0", rc_active=ANY)
        query.answer.assert_awaited_once()

    async def test_rejects_non_owner(self):
        query = _q()
        with patch(f"{MOD}.user_owns_window", return_value=False):
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_NOTIFY}@0", MagicMock(), MagicMock()
            )
        query.answer.assert_awaited_once_with("Not your session", show_alert=True)


class TestStatusEsc:
    async def test_sends_escape_key(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch(f"{MOD}.tmux_manager") as tm,
        ):
            tm.find_window_by_id = AsyncMock(return_value=MagicMock(window_id="@0"))
            tm.send_keys = AsyncMock()
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_ESC}@0", MagicMock(), MagicMock()
            )
        tm.send_keys.assert_awaited_once_with(
            "@0", "Escape", enter=False, literal=False
        )
        query.answer.assert_awaited_once_with("\u238b Sent Escape")

    async def test_window_not_found(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch(f"{MOD}.tmux_manager") as tm,
        ):
            tm.find_window_by_id = AsyncMock(return_value=None)
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_ESC}@0", MagicMock(), MagicMock()
            )
        query.answer.assert_awaited_once_with("Window not found", show_alert=True)


class TestRemoteControl:
    async def test_activates_remote_control(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch("ccgram.handlers.polling_strategies.terminal_screen_buffer") as tsb,
            patch(f"{MOD}.thread_router") as tr,
            patch(f"{MOD}.send_to_window", new_callable=AsyncMock) as mock_send,
        ):
            tsb.is_rc_active.return_value = False
            tr.get_display_name.return_value = "my-project"
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_REMOTE}@0", MagicMock(), MagicMock()
            )
        mock_send.assert_awaited_once_with("@0", "/remote-control my-project")
        query.answer.assert_awaited_once_with("\U0001f4e1 Activating\u2026")

    async def test_shows_already_active(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch("ccgram.handlers.polling_strategies.terminal_screen_buffer") as tsb,
        ):
            tsb.is_rc_active.return_value = True
            await _handle_status_bar_action(
                query, 1, f"{CB_STATUS_REMOTE}@0", MagicMock(), MagicMock()
            )
        query.answer.assert_awaited_once_with("\U0001f4e1 Remote Control active")


class TestKeys:
    async def test_sends_key_and_schedules_refresh(self):
        query = _q()
        update = MagicMock()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch(f"{MOD}.get_thread_id", return_value=None),
            patch(f"{MOD}.tmux_manager") as tm,
            patch(f"{MOD}._schedule_key_refresh") as mock_sched,
        ):
            tm.find_window_by_id = AsyncMock(return_value=MagicMock(window_id="@0"))
            tm.send_keys = AsyncMock()
            await _handle_status_bar_action(
                query, 1, f"{CB_KEYS_PREFIX}ent:@0", update, MagicMock()
            )
        tm.send_keys.assert_awaited_once()
        mock_sched.assert_called_once()

    async def test_unknown_key_rejected(self):
        query = _q()
        with (
            patch(f"{MOD}.user_owns_window", return_value=True),
            patch(f"{MOD}.tmux_manager"),
        ):
            await _handle_status_bar_action(
                query, 1, f"{CB_KEYS_PREFIX}xxx:@0", MagicMock(), MagicMock()
            )
        query.answer.assert_awaited_once_with("Unknown key")


class TestClearKeyRefreshes:
    def test_cancels_matching_tasks(self):
        from ccgram.handlers.status_bar_actions import (
            _clear_key_refreshes,
            _pending_key_refreshes,
        )

        task1 = MagicMock()
        task1.done.return_value = False
        task2 = MagicMock()
        task2.done.return_value = False
        _pending_key_refreshes[(1, "@0")] = task1
        _pending_key_refreshes[(2, "@1")] = task2
        _clear_key_refreshes("@0")
        task1.cancel.assert_called_once()
        task2.cancel.assert_not_called()
        _pending_key_refreshes.clear()
