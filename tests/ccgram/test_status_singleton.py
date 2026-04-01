"""Tests for status message singleton behavior (no pile-up).

Verifies three invariants:
1. Edit failure does NOT send a new status message (clears tracking only).
2. Content delivery does NOT eagerly recreate status (poll loop handles it).
3. _do_send_status_message edits existing status instead of sending new.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.claude_task_state import claude_task_state
from ccgram.handlers.message_queue import (
    MessageTask,
    _do_send_status_message,
    _process_status_clear_task,
    _process_status_update_task,
    _status_msg_info,
)

USER_ID = 1
THREAD_ID = 10
WINDOW_ID = "@0"
CHAT_ID = 42
SKEY = (USER_ID, THREAD_ID)


@pytest.fixture(autouse=True)
def _clear_status_tracking():
    _status_msg_info.pop(SKEY, None)
    yield
    _status_msg_info.pop(SKEY, None)


def _status_task(text: str = "running...", window_id: str = WINDOW_ID) -> MessageTask:
    return MessageTask(
        task_type="status_update",
        text=text,
        window_id=window_id,
        thread_id=THREAD_ID,
    )


class TestEditFailureNoNewMessage:
    """Change 1: edit failure clears tracking, does NOT send a new message."""

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_edit_failure_clears_tracking_no_send(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        mock_edit.return_value = False  # edit fails

        # Pre-populate: existing status message tracked
        _status_msg_info[SKEY] = (100, WINDOW_ID, "old text", CHAT_ID)

        bot = AsyncMock()
        await _process_status_update_task(bot, USER_ID, _status_task("new text"))

        # Tracking should be cleared
        assert SKEY not in _status_msg_info

        # No new message should be sent
        mock_send.assert_not_called()

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_edit_success_updates_tracking(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        mock_edit.return_value = True  # edit succeeds

        _status_msg_info[SKEY] = (100, WINDOW_ID, "old text", CHAT_ID)

        bot = AsyncMock()
        await _process_status_update_task(bot, USER_ID, _status_task("new text"))

        # Tracking should be updated with new text, same message id
        assert _status_msg_info[SKEY] == (100, WINDOW_ID, "new text", CHAT_ID)
        mock_send.assert_not_called()

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_status_update_appends_claude_tasks(self, mock_send, mock_tr) -> None:
        mock_tr.resolve_chat_id.return_value = CHAT_ID
        sent_msg = MagicMock()
        sent_msg.message_id = 500
        mock_send.return_value = sent_msg
        claude_task_state.apply_entries(
            WINDOW_ID,
            "session-1",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "TodoWrite",
                                "input": {
                                    "todos": [
                                        {
                                            "content": "Review changes",
                                            "status": "completed",
                                        },
                                        {
                                            "content": "Write tests",
                                            "status": "in_progress",
                                            "activeForm": "Writing tests",
                                        },
                                    ]
                                },
                            }
                        ]
                    },
                }
            ],
        )

        bot = AsyncMock()
        await _process_status_update_task(bot, USER_ID, _status_task("Working"))

        sent_text = mock_send.call_args[0][2]
        assert sent_text.startswith("Working")
        assert "2 tasks (1 done, 1 open)" in sent_text
        assert "✔ #1 Review changes" in sent_text
        assert "◔ #2 Writing tests" in sent_text

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    async def test_status_clear_renders_task_only_when_snapshot_exists(
        self, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = CHAT_ID
        mock_edit.return_value = True
        _status_msg_info[SKEY] = (100, WINDOW_ID, "old text", CHAT_ID)
        claude_task_state.apply_entries(
            WINDOW_ID,
            "session-1",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "TodoWrite",
                                "input": {
                                    "todos": [
                                        {
                                            "content": "Review changes",
                                            "status": "completed",
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            ],
        )

        bot = AsyncMock()
        await _process_status_clear_task(
            bot,
            USER_ID,
            MessageTask(
                task_type="status_clear", thread_id=THREAD_ID, window_id=WINDOW_ID
            ),
        )

        sent_text = mock_edit.call_args[0][3]
        assert sent_text.startswith("1 tasks (1 done, 0 open)")
        assert "✔ #1 Review changes" in sent_text


class TestDoSendGuard:
    """Change 3: _do_send_status_message edits existing instead of sending new."""

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_existing_status_same_window_edits_in_place(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        mock_edit.return_value = True

        _status_msg_info[SKEY] = (100, WINDOW_ID, "old text", CHAT_ID)

        bot = AsyncMock()
        await _do_send_status_message(bot, USER_ID, THREAD_ID, WINDOW_ID, "new text")

        # Should edit, not send new
        mock_edit.assert_called_once()
        mock_send.assert_not_called()
        assert _status_msg_info[SKEY] == (100, WINDOW_ID, "new text", CHAT_ID)

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_existing_status_identical_text_skips(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42

        _status_msg_info[SKEY] = (100, WINDOW_ID, "running...", CHAT_ID)

        bot = AsyncMock()
        await _do_send_status_message(bot, USER_ID, THREAD_ID, WINDOW_ID, "running...")

        # Should do nothing — identical text
        mock_edit.assert_not_called()
        mock_send.assert_not_called()

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_no_existing_status_sends_new(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        sent_msg = MagicMock()
        sent_msg.message_id = 200
        mock_send.return_value = sent_msg

        bot = AsyncMock()
        await _do_send_status_message(bot, USER_ID, THREAD_ID, WINDOW_ID, "running...")

        mock_edit.assert_not_called()
        mock_send.assert_called_once()
        assert _status_msg_info[SKEY] == (200, WINDOW_ID, "running...", CHAT_ID)

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    @patch(
        "ccgram.handlers.message_queue._do_clear_status_message", new_callable=AsyncMock
    )
    async def test_existing_status_different_window_clears_and_sends(
        self, mock_clear, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        sent_msg = MagicMock()
        sent_msg.message_id = 300
        mock_send.return_value = sent_msg

        _status_msg_info[SKEY] = (100, "@1", "running...", CHAT_ID)  # different window

        bot = AsyncMock()
        await _do_send_status_message(bot, USER_ID, THREAD_ID, WINDOW_ID, "running...")

        mock_clear.assert_called_once_with(bot, USER_ID, THREAD_ID)
        mock_send.assert_called_once()
        assert _status_msg_info[SKEY] == (300, WINDOW_ID, "running...", CHAT_ID)

    @patch("ccgram.handlers.message_queue.thread_router")
    @patch("ccgram.handlers.message_queue.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue.rate_limit_send_message", new_callable=AsyncMock
    )
    async def test_existing_status_edit_fails_falls_through_to_send(
        self, mock_send, mock_edit, mock_tr
    ) -> None:
        mock_tr.resolve_chat_id.return_value = 42
        mock_edit.return_value = False  # edit fails
        sent_msg = MagicMock()
        sent_msg.message_id = 400
        mock_send.return_value = sent_msg

        _status_msg_info[SKEY] = (100, WINDOW_ID, "old text", CHAT_ID)

        bot = AsyncMock()
        await _do_send_status_message(bot, USER_ID, THREAD_ID, WINDOW_ID, "new text")

        # Edit attempted first, then falls through to send
        mock_edit.assert_called_once()
        mock_send.assert_called_once()
        assert _status_msg_info[SKEY] == (400, WINDOW_ID, "new text", CHAT_ID)
