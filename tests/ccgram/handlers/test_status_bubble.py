import ast
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.message_task import StatusClearTask, StatusUpdateTask
from ccgram.handlers.status_bubble import (
    _status_msg_info,
    clear_status_message,
    clear_status_msg_info,
    convert_status_to_content,
    format_claude_task_status,
    process_status_clear,
    process_status_update,
    send_status_text,
)

USER_ID = 1
THREAD_ID = 10
WINDOW_ID = "@0"
CHAT_ID = 42


@pytest.fixture(autouse=True)
def _clear_status_tracking():
    _status_msg_info.clear()
    yield
    _status_msg_info.clear()


class TestSendStatusText:
    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.status_bubble.rate_limit_send_message",
        new_callable=AsyncMock,
    )
    async def test_sends_new_message(self, mock_send, mock_edit, mock_router):
        mock_router.resolve_chat_id.return_value = CHAT_ID
        sent = MagicMock()
        sent.message_id = 99
        mock_send.return_value = sent

        bot = AsyncMock()
        await send_status_text(bot, USER_ID, THREAD_ID, WINDOW_ID, "running...")

        mock_send.assert_called_once()
        assert _status_msg_info[(USER_ID, THREAD_ID)] == (
            99,
            WINDOW_ID,
            "running...",
            CHAT_ID,
        )

    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.status_bubble.rate_limit_send_message",
        new_callable=AsyncMock,
    )
    async def test_edits_existing_same_window(self, mock_send, mock_edit, mock_router):
        mock_router.resolve_chat_id.return_value = CHAT_ID
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "old", CHAT_ID)
        mock_edit.return_value = True

        bot = AsyncMock()
        await send_status_text(bot, USER_ID, THREAD_ID, WINDOW_ID, "new text")

        mock_edit.assert_called_once()
        mock_send.assert_not_called()
        assert _status_msg_info[(USER_ID, THREAD_ID)][2] == "new text"

    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.status_bubble.rate_limit_send_message",
        new_callable=AsyncMock,
    )
    async def test_dedup_identical_content(self, mock_send, mock_edit, mock_router):
        mock_router.resolve_chat_id.return_value = CHAT_ID
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "same", CHAT_ID)

        bot = AsyncMock()
        await send_status_text(bot, USER_ID, THREAD_ID, WINDOW_ID, "same")

        mock_edit.assert_not_called()
        mock_send.assert_not_called()


class TestClearStatusMessage:
    async def test_deletes_tracked_message(self):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "text", CHAT_ID)

        bot = AsyncMock()
        await clear_status_message(bot, USER_ID, THREAD_ID)

        bot.delete_message.assert_called_once_with(chat_id=CHAT_ID, message_id=50)
        assert (USER_ID, THREAD_ID) not in _status_msg_info

    async def test_noop_when_no_tracking(self):
        bot = AsyncMock()
        await clear_status_message(bot, USER_ID, THREAD_ID)

        bot.delete_message.assert_not_called()


class TestConvertStatusToContent:
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    async def test_converts_status_to_content(self, mock_edit):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "old", CHAT_ID)
        mock_edit.return_value = True

        bot = AsyncMock()
        result = await convert_status_to_content(
            bot, USER_ID, THREAD_ID, WINDOW_ID, "content text"
        )

        assert result == 50
        mock_edit.assert_called_once()
        assert (USER_ID, THREAD_ID) not in _status_msg_info

    async def test_returns_none_when_no_status(self):
        bot = AsyncMock()
        result = await convert_status_to_content(
            bot, USER_ID, THREAD_ID, WINDOW_ID, "content"
        )

        assert result is None

    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    async def test_deletes_status_from_different_window(self, mock_edit):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, "@1", "old", CHAT_ID)

        bot = AsyncMock()
        result = await convert_status_to_content(
            bot, USER_ID, THREAD_ID, WINDOW_ID, "content"
        )

        assert result is None
        bot.delete_message.assert_called_once_with(chat_id=CHAT_ID, message_id=50)


class TestFormatClaudeTaskStatus:
    @patch("ccgram.handlers.status_bubble.get_claude_task_snapshot", return_value=None)
    @patch("ccgram.handlers.status_bubble.get_claude_wait_header", return_value=None)
    def test_no_tasks_returns_base_text(self, mock_wait, mock_snap):
        result = format_claude_task_status(WINDOW_ID, "Running")
        assert result == "Running"

    @patch("ccgram.handlers.status_bubble.get_claude_task_snapshot", return_value=None)
    @patch(
        "ccgram.handlers.status_bubble.get_claude_wait_header",
        return_value="Waiting for input...",
    )
    def test_with_wait_header(self, mock_wait, mock_snap):
        result = format_claude_task_status(WINDOW_ID, "Running")
        assert result == "Waiting for input..."

    @patch("ccgram.handlers.status_bubble.get_claude_task_snapshot")
    @patch("ccgram.handlers.status_bubble.get_claude_wait_header", return_value=None)
    def test_with_task_list(self, mock_wait, mock_snap):
        item = MagicMock()
        item.status = "in_progress"
        item.active_form = "writing tests"
        item.subject = "Task A"
        item.task_id = 1
        item.owner = None
        item.blocked_by = []
        snapshot = MagicMock()
        snapshot.total_count = 1
        snapshot.done_count = 0
        snapshot.open_count = 1
        snapshot.items = [item]
        mock_snap.return_value = snapshot

        result = format_claude_task_status(WINDOW_ID, "Running")
        assert result is not None
        assert "1 tasks (0 done, 1 open)" in result
        assert "writing tests" in result


class TestClearStatusMsgInfo:
    def test_clears_specific_thread(self):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "text", CHAT_ID)
        _status_msg_info[(USER_ID, 20)] = (51, WINDOW_ID, "text", CHAT_ID)

        clear_status_msg_info(USER_ID, THREAD_ID)

        assert (USER_ID, THREAD_ID) not in _status_msg_info
        assert (USER_ID, 20) in _status_msg_info

    def test_noop_when_not_tracked(self):
        clear_status_msg_info(USER_ID, THREAD_ID)


class TestProcessStatusUpdate:
    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch(
        "ccgram.handlers.status_bubble.rate_limit_send_message",
        new_callable=AsyncMock,
    )
    async def test_returns_none_when_absorbed(self, mock_send, mock_router):
        mock_router.resolve_chat_id.return_value = CHAT_ID
        sent = MagicMock()
        sent.message_id = 99
        mock_send.return_value = sent

        bot = AsyncMock()
        task = StatusUpdateTask(
            window_id=WINDOW_ID, text="thinking", thread_id=THREAD_ID
        )
        result = await process_status_update(bot, USER_ID, task)

        assert result is None
        mock_send.assert_called_once()

    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.status_bubble.rate_limit_send_message",
        new_callable=AsyncMock,
    )
    async def test_clears_when_no_status_text(self, mock_send, mock_edit, mock_router):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "old", CHAT_ID)

        bot = AsyncMock()
        task = StatusUpdateTask(window_id=WINDOW_ID, text=None, thread_id=THREAD_ID)
        with patch(
            "ccgram.handlers.status_bubble.format_claude_task_status", return_value=None
        ):
            result = await process_status_update(bot, USER_ID, task)

        assert result is None
        assert (USER_ID, THREAD_ID) not in _status_msg_info

    async def test_uses_thread_key_for_none_thread(self):
        task = StatusUpdateTask(window_id=WINDOW_ID, text="running", thread_id=None)
        from ccgram.handlers.message_task import thread_key

        assert thread_key(task.thread_id) == 0


class TestProcessStatusClear:
    @patch("ccgram.handlers.status_bubble.thread_router")
    @patch("ccgram.handlers.status_bubble.edit_with_fallback", new_callable=AsyncMock)
    async def test_re_renders_with_task_snapshot(self, mock_edit, mock_router):
        mock_router.resolve_chat_id.return_value = CHAT_ID
        mock_edit.return_value = True
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "old", CHAT_ID)

        bot = AsyncMock()
        task = StatusClearTask(window_id=WINDOW_ID, thread_id=THREAD_ID)
        with patch(
            "ccgram.handlers.status_bubble.format_claude_task_status",
            return_value="1 tasks (1 done, 0 open)",
        ):
            await process_status_clear(bot, USER_ID, task)

        mock_edit.assert_called_once()

    async def test_deletes_when_no_snapshot(self):
        _status_msg_info[(USER_ID, THREAD_ID)] = (50, WINDOW_ID, "old", CHAT_ID)

        bot = AsyncMock()
        task = StatusClearTask(window_id=WINDOW_ID, thread_id=THREAD_ID)
        with patch(
            "ccgram.handlers.status_bubble.format_claude_task_status",
            return_value=None,
        ):
            await process_status_clear(bot, USER_ID, task)

        bot.delete_message.assert_called_once_with(chat_id=CHAT_ID, message_id=50)
        assert (USER_ID, THREAD_ID) not in _status_msg_info


class TestNoImportFromMessageQueue:
    def test_no_import_from_message_queue(self) -> None:
        import ccgram.handlers.status_bubble as mod

        source = inspect.getsource(mod)
        tree = ast.parse(source)
        violations: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "message_queue" in node.module
            ):
                violations.append(f"line {node.lineno}: from {node.module} import ...")
        assert violations == [], (
            f"status_bubble imports from message_queue: {violations}"
        )
