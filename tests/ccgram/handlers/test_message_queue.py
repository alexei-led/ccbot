import asyncio
from unittest.mock import MagicMock

import pytest

from ccgram.handlers.message_queue import (
    MERGE_MAX_LENGTH,
    MessageTask,
    _can_merge_tasks,
    _coalesce_status_updates,
    _merge_content_tasks,
    get_or_create_queue,
    shutdown_workers,
)


@pytest.fixture
def bot():
    return MagicMock(spec_set=["_do_post"])


@pytest.fixture
def queue():
    return asyncio.Queue()


@pytest.fixture
def lock():
    return asyncio.Lock()


def _content_task(
    text: str = "hello",
    window_id: str = "@0",
    content_type: str = "text",
    thread_id: int | None = 42,
    tool_use_id: str | None = None,
) -> MessageTask:
    return MessageTask(
        task_type="content",
        window_id=window_id,
        parts=[text],
        content_type=content_type,
        thread_id=thread_id,
        tool_use_id=tool_use_id,
    )


def _status_task(
    text: str = "Thinking...",
    window_id: str = "@0",
    thread_id: int | None = 42,
) -> MessageTask:
    return MessageTask(
        task_type="status_update",
        text=text,
        window_id=window_id,
        thread_id=thread_id,
    )


class TestGetOrCreateQueue:
    async def test_creates_queue_and_worker(self, bot):
        user_id = 99990
        from ccgram.handlers.message_queue import _message_queues, _queue_workers

        _message_queues.pop(user_id, None)
        _queue_workers.pop(user_id, None)

        try:
            q = get_or_create_queue(bot, user_id)
            assert q is not None
            assert user_id in _queue_workers
        finally:
            await shutdown_workers()

    async def test_reuses_existing_queue(self, bot):
        user_id = 99991
        from ccgram.handlers.message_queue import _message_queues, _queue_workers

        _message_queues.pop(user_id, None)
        _queue_workers.pop(user_id, None)

        try:
            q1 = get_or_create_queue(bot, user_id)
            q2 = get_or_create_queue(bot, user_id)
            assert q1 is q2
        finally:
            await shutdown_workers()


class TestCanMergeTasks:
    def test_same_window_text_tasks_merge(self):
        a = _content_task("hello")
        b = _content_task("world")
        assert _can_merge_tasks(a, b)

    def test_different_window_blocks_merge(self):
        a = _content_task("hello", window_id="@0")
        b = _content_task("world", window_id="@1")
        assert not _can_merge_tasks(a, b)

    def test_tool_use_base_blocks_merge(self):
        a = _content_task("hello", content_type="tool_use")
        b = _content_task("world")
        assert not _can_merge_tasks(a, b)

    def test_tool_result_candidate_blocks_merge(self):
        a = _content_task("hello")
        b = _content_task("world", content_type="tool_result")
        assert not _can_merge_tasks(a, b)

    def test_non_content_candidate_blocks_merge(self):
        a = _content_task("hello")
        b = _status_task()
        assert not _can_merge_tasks(a, b)


class TestMergeContentTasks:
    async def test_merges_consecutive_text_tasks(self, queue, lock):
        queue.put_nowait(_content_task("second"))
        queue.put_nowait(_content_task("third"))
        first = _content_task("first")

        merged, count = await _merge_content_tasks(queue, first, lock)

        assert count == 2
        assert merged.parts == ["first", "second", "third"]

    async def test_stops_on_tool_use(self, queue, lock):
        queue.put_nowait(_content_task("second"))
        queue.put_nowait(_content_task("tool", content_type="tool_use"))
        queue.put_nowait(_content_task("after"))
        first = _content_task("first")

        merged, count = await _merge_content_tasks(queue, first, lock)

        assert count == 1
        assert merged.parts == ["first", "second"]
        assert queue.qsize() == 2

    async def test_stops_at_length_limit(self, queue, lock):
        big_text = "x" * MERGE_MAX_LENGTH
        queue.put_nowait(_content_task("overflow"))
        first = _content_task(big_text)

        merged, count = await _merge_content_tasks(queue, first, lock)

        assert count == 0
        assert merged.parts == [big_text]
        assert queue.qsize() == 1

    async def test_no_merge_returns_zero(self, queue, lock):
        first = _content_task("solo")

        merged, count = await _merge_content_tasks(queue, first, lock)

        assert count == 0
        assert merged is first


class TestCoalesceStatusUpdates:
    async def test_keeps_latest_status(self, queue, lock):
        queue.put_nowait(_status_task("Thinking..."))
        queue.put_nowait(_status_task("Writing..."))
        first = _status_task("Reading...")

        selected, dropped = await _coalesce_status_updates(queue, first, lock)

        assert selected.text == "Writing..."
        assert dropped == 2

    async def test_non_status_passthrough(self, queue, lock):
        task = _content_task("hello")

        selected, dropped = await _coalesce_status_updates(queue, task, lock)

        assert selected is task
        assert dropped == 0
