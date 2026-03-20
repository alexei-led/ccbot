"""Unit tests for tool call batching in message queue."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.message_queue import (
    BATCH_MAX_ENTRIES,
    BATCH_MAX_LENGTH,
    MessageTask,
    ToolBatch,
    ToolBatchEntry,
    _active_batches,
    _flush_batch,
    _handle_content_task,
    _is_batch_eligible,
    _process_batch_task,
    format_batch_message,
)

# --- format_batch_message tests ---


class TestFormatBatchMessage:
    def test_single_entry_pending(self) -> None:
        entries = [ToolBatchEntry(tool_use_id="t1", tool_use_text="Read src/foo.py")]
        result = format_batch_message(entries)
        assert result.startswith("\u26a1 1 tool call")
        assert "Read src/foo.py" in result
        assert "\u23f3" in result  # hourglass for pending

    def test_single_entry_with_result(self) -> None:
        entries = [
            ToolBatchEntry(
                tool_use_id="t1",
                tool_use_text="Read src/foo.py",
                tool_result_text="42 lines",
            )
        ]
        result = format_batch_message(entries)
        assert "1 tool call" in result
        assert "42 lines" in result
        assert "\u23f3" not in result  # no hourglass when result present

    def test_multiple_entries(self) -> None:
        entries = [
            ToolBatchEntry("t1", "Read src/a.py", "10 lines"),
            ToolBatchEntry("t2", "Edit src/a.py", "+3 -1"),
            ToolBatchEntry("t3", "Bash make test"),
        ]
        result = format_batch_message(entries)
        assert "3 tool calls" in result
        assert "Read src/a.py" in result
        assert "Edit src/a.py" in result
        assert "Bash make test" in result
        # Last entry has no result -> hourglass
        lines = result.split("\n")
        assert "\u23f3" in lines[-1]
        assert "\u23f3" not in lines[1]  # first entry has result

    def test_header_pluralization(self) -> None:
        single = format_batch_message([ToolBatchEntry("t1", "Read x")])
        assert "tool call\n" in single

        multi = format_batch_message(
            [ToolBatchEntry("t1", "Read x"), ToolBatchEntry("t2", "Edit y")]
        )
        assert "tool calls\n" in multi


# --- _is_batch_eligible tests ---


class TestIsBatchEligible:
    def test_tool_use_eligible(self) -> None:
        task = MessageTask(task_type="content", content_type="tool_use", parts=["x"])
        assert _is_batch_eligible(task) is True

    def test_tool_result_eligible(self) -> None:
        task = MessageTask(task_type="content", content_type="tool_result", parts=["x"])
        assert _is_batch_eligible(task) is True

    def test_text_not_eligible(self) -> None:
        task = MessageTask(task_type="content", content_type="text", parts=["x"])
        assert _is_batch_eligible(task) is False

    def test_thinking_not_eligible(self) -> None:
        task = MessageTask(task_type="content", content_type="thinking", parts=["x"])
        assert _is_batch_eligible(task) is False

    def test_status_update_not_eligible(self) -> None:
        task = MessageTask(task_type="status_update", text="working")
        assert _is_batch_eligible(task) is False


# --- Batch overflow detection ---


class TestBatchOverflow:
    def test_max_entries_constant(self) -> None:
        assert BATCH_MAX_ENTRIES == 20

    def test_max_length_constant(self) -> None:
        assert BATCH_MAX_LENGTH == 3800

    def test_batch_entry_accumulation(self) -> None:
        batch = ToolBatch(window_id="@0", thread_id=0)
        for i in range(5):
            entry = ToolBatchEntry(f"t{i}", f"Read file{i}.py")
            batch.entries.append(entry)
            batch.total_length += len(entry.tool_use_text)
        assert len(batch.entries) == 5
        assert batch.total_length == sum(len(f"Read file{i}.py") for i in range(5))


# --- _process_batch_task tests ---


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock(spec=["send_message", "edit_message_text"])
    msg = MagicMock()
    msg.message_id = 100
    bot.send_message.return_value = msg
    return bot


@pytest.fixture(autouse=True)
def _clear_batches():
    _active_batches.clear()
    yield
    _active_batches.clear()


class TestProcessBatchTask:
    @patch("ccgram.handlers.message_queue.session_manager")
    @patch("ccgram.handlers.message_queue.rate_limit_send_message")
    @patch("ccgram.handlers.message_queue._should_batch", return_value=True)
    @patch(
        "ccgram.handlers.message_queue._do_clear_status_message", new_callable=AsyncMock
    )
    async def test_tool_use_creates_batch(
        self, mock_clear, mock_should, mock_send, mock_sm
    ) -> None:
        mock_sm.resolve_chat_id.return_value = 42
        sent_msg = MagicMock()
        sent_msg.message_id = 100
        mock_send.return_value = sent_msg

        bot = AsyncMock()
        task = MessageTask(
            task_type="content",
            content_type="tool_use",
            window_id="@0",
            tool_use_id="tu1",
            text="Read src/foo.py",
            parts=["Read src/foo.py"],
            thread_id=10,
        )
        await _process_batch_task(bot, 1, task)

        bkey = (1, 10)
        assert bkey in _active_batches
        batch = _active_batches[bkey]
        assert len(batch.entries) == 1
        assert batch.entries[0].tool_use_id == "tu1"
        assert batch.telegram_msg_id == 100

    @patch("ccgram.handlers.message_queue.session_manager")
    @patch("ccgram.handlers.message_queue.rate_limit_send_message")
    @patch("ccgram.handlers.message_queue._should_batch", return_value=True)
    @patch(
        "ccgram.handlers.message_queue._do_clear_status_message", new_callable=AsyncMock
    )
    async def test_tool_result_updates_entry(
        self, mock_clear, mock_should, mock_send, mock_sm
    ) -> None:
        mock_sm.resolve_chat_id.return_value = 42
        sent_msg = MagicMock()
        sent_msg.message_id = 100
        mock_send.return_value = sent_msg

        bot = AsyncMock()
        # First: tool_use
        task1 = MessageTask(
            task_type="content",
            content_type="tool_use",
            window_id="@0",
            tool_use_id="tu1",
            text="Read src/foo.py",
            parts=["Read src/foo.py"],
            thread_id=10,
        )
        await _process_batch_task(bot, 1, task1)

        # Then: tool_result
        task2 = MessageTask(
            task_type="content",
            content_type="tool_result",
            window_id="@0",
            tool_use_id="tu1",
            text="42 lines of code",
            parts=["42 lines of code"],
            thread_id=10,
        )
        await _process_batch_task(bot, 1, task2)

        batch = _active_batches[(1, 10)]
        assert batch.entries[0].tool_result_text == "42 lines of code"


# --- _handle_content_task integration tests ---


class TestHandleContentTask:
    @patch("ccgram.handlers.message_queue.session_manager")
    @patch("ccgram.handlers.message_queue._should_batch", return_value=True)
    @patch("ccgram.handlers.message_queue._process_batch_task", new_callable=AsyncMock)
    async def test_batch_eligible_routes_to_batch(
        self, mock_batch, mock_should, mock_sm
    ) -> None:
        bot = AsyncMock()
        queue: asyncio.Queue[MessageTask] = asyncio.Queue()
        lock = asyncio.Lock()
        task = MessageTask(
            task_type="content",
            content_type="tool_use",
            window_id="@0",
            parts=["Read x"],
        )
        extra = await _handle_content_task(bot, 1, task, queue, lock)
        assert extra == 0
        mock_batch.assert_awaited_once()

    @patch("ccgram.handlers.message_queue.session_manager")
    @patch("ccgram.handlers.message_queue._should_batch", return_value=False)
    @patch(
        "ccgram.handlers.message_queue._process_content_task", new_callable=AsyncMock
    )
    async def test_verbose_mode_skips_batch(
        self, mock_process, mock_should, mock_sm
    ) -> None:
        bot = AsyncMock()
        queue: asyncio.Queue[MessageTask] = asyncio.Queue()
        lock = asyncio.Lock()
        task = MessageTask(
            task_type="content",
            content_type="tool_use",
            window_id="@0",
            parts=["Read x"],
        )
        extra = await _handle_content_task(bot, 1, task, queue, lock)
        assert extra == 0
        mock_process.assert_awaited_once()

    @patch("ccgram.handlers.message_queue.session_manager")
    @patch("ccgram.handlers.message_queue._flush_batch", new_callable=AsyncMock)
    @patch(
        "ccgram.handlers.message_queue._process_content_task", new_callable=AsyncMock
    )
    async def test_text_flushes_active_batch(
        self, mock_process, mock_flush, mock_sm
    ) -> None:
        # Set up an active batch
        _active_batches[(1, 0)] = ToolBatch(window_id="@0", thread_id=0, entries=[])

        bot = AsyncMock()
        queue: asyncio.Queue[MessageTask] = asyncio.Queue()
        lock = asyncio.Lock()
        task = MessageTask(
            task_type="content",
            content_type="text",
            window_id="@0",
            parts=["Hello"],
        )
        await _handle_content_task(bot, 1, task, queue, lock)
        mock_flush.assert_awaited_once_with(bot, 1, 0)
        mock_process.assert_awaited_once()


# --- _flush_batch tests ---


class TestFlushBatch:
    @patch("ccgram.handlers.message_queue.session_manager")
    async def test_flush_removes_batch(self, mock_sm) -> None:
        mock_sm.resolve_chat_id.return_value = 42
        _active_batches[(1, 10)] = ToolBatch(
            window_id="@0",
            thread_id=10,
            entries=[ToolBatchEntry("t1", "Read x", "ok")],
            telegram_msg_id=100,
        )

        bot = AsyncMock()
        await _flush_batch(bot, 1, 10)
        assert (1, 10) not in _active_batches

    async def test_flush_noop_when_no_batch(self) -> None:
        bot = AsyncMock()
        await _flush_batch(bot, 1, 10)  # should not raise

    @patch("ccgram.handlers.message_queue.session_manager")
    async def test_flush_edits_final_message(self, mock_sm) -> None:
        mock_sm.resolve_chat_id.return_value = 42
        _active_batches[(1, 0)] = ToolBatch(
            window_id="@0",
            thread_id=0,
            entries=[
                ToolBatchEntry("t1", "Read a.py", "10 lines"),
                ToolBatchEntry("t2", "Edit a.py", "+1 -1"),
            ],
            telegram_msg_id=200,
        )

        bot = AsyncMock()
        await _flush_batch(bot, 1, 0)
        bot.edit_message_text.assert_awaited()
