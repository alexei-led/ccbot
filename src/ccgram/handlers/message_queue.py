"""Per-user message queue management for ordered message delivery.

Queue primitives (FIFO ordering, merging, coalescing) and the worker loop
that dispatches tasks to ``tool_batch`` and ``status_bubble``.  Status I/O,
task-list formatting, and keyboard rendering live in ``status_bubble``;
tool-use batching lives in ``tool_batch``.
"""

import asyncio
import contextlib
from typing import assert_never

import structlog
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from ..thread_router import thread_router
from ..topic_state_registry import topic_state
from ..utils import task_done_callback
from ..window_query import is_tool_calls_hidden
from .message_sender import edit_with_fallback, rate_limit_send_message, send_kwargs
from .message_task import (
    ContentTask,
    ContentType,
    MessageTask,
    StatusClearTask,
    StatusUpdateTask,
    thread_key,
)
from .status_bubble import (
    clear_status_message,
    convert_status_to_content,
    process_status_clear,
    process_status_update,
)
from .tool_batch import (
    clear_all_batches,
    flush_batch,
    flush_if_active,
    has_active_batch,
    is_batch_eligible,
    process_tool_event,
)

logger = structlog.get_logger()

MERGE_MAX_LENGTH = 3800  # Leave room within Telegram's 4096 char message limit

# Per-user message queues and worker tasks
_message_queues: dict[int, asyncio.Queue[MessageTask]] = {}
_queue_workers: dict[int, asyncio.Task[None]] = {}
_queue_locks: dict[int, asyncio.Lock] = {}  # Protect drain/refill operations

# Map (tool_use_id, user_id, thread_key) -> telegram message_id
# for editing tool_use messages with results
_tool_msg_ids: dict[tuple[str, int, int], int] = {}


def get_message_queue(user_id: int) -> asyncio.Queue[MessageTask] | None:
    """Get the message queue for a user (if exists)."""
    return _message_queues.get(user_id)


def get_or_create_queue(bot: Bot, user_id: int) -> asyncio.Queue[MessageTask]:
    """Get or create message queue and worker for a user.

    Also detects dead workers and respawns them so messages are not lost.
    """
    if user_id not in _message_queues:
        _message_queues[user_id] = asyncio.Queue()
        _queue_locks[user_id] = asyncio.Lock()

    # Respawn dead workers (can happen if an uncaught exception killed the task)
    existing = _queue_workers.get(user_id)
    if existing is None or existing.done():
        if existing is not None:
            logger.warning("Respawning dead queue worker for user %s", user_id)
        task = asyncio.create_task(_message_queue_worker(bot, user_id))
        task.add_done_callback(task_done_callback)
        _queue_workers[user_id] = task
    return _message_queues[user_id]


def _drain_queue(queue: asyncio.Queue[MessageTask]) -> list[MessageTask]:
    """Drain all items from the queue and return them as a list.

    Destructive: the queue is empty after this call. Caller is responsible
    for re-enqueueing any items that should not be discarded.
    """
    items: list[MessageTask] = []
    while not queue.empty():
        try:
            item = queue.get_nowait()
            items.append(item)
        except asyncio.QueueEmpty:
            break
    return items


def _can_merge_tasks(base: ContentTask, candidate: MessageTask) -> bool:
    """Check if two content tasks can be merged."""
    if not isinstance(candidate, ContentTask):
        return False
    if base.window_id != candidate.window_id:
        return False
    if base.content_type in ("tool_use", "tool_result"):
        return False
    return candidate.content_type not in ("tool_use", "tool_result")


async def _merge_content_tasks(
    queue: asyncio.Queue[MessageTask],
    first: ContentTask,
    lock: asyncio.Lock,
) -> tuple[ContentTask, int]:
    """Merge consecutive content tasks from queue.

    Returns: (merged_task, merge_count) where merge_count is the number of
    additional tasks merged (0 if no merging occurred).

    Note on queue counter management:
        put_nowait() on re-enqueued items increments the internal task counter
        again; task_done() compensates so the net count stays correct.
        Without this compensation, queue.join() would wait indefinitely.
    """
    merged_parts = list(first.parts)
    current_length = sum(len(p) for p in merged_parts)
    merge_count = 0

    async with lock:
        items = _drain_queue(queue)
        remaining: list[MessageTask] = []

        for i, task in enumerate(items):
            if not _can_merge_tasks(first, task):
                remaining = items[i:]
                break

            assert isinstance(task, ContentTask)
            task_length = sum(len(p) for p in task.parts)
            if current_length + task_length > MERGE_MAX_LENGTH:
                remaining = items[i:]
                break

            merged_parts.extend(task.parts)
            current_length += task_length
            merge_count += 1

        for item in remaining:
            queue.put_nowait(item)
            queue.task_done()

    if merge_count == 0:
        return first, 0

    return (
        ContentTask(
            window_id=first.window_id,
            parts=tuple(merged_parts),
            tool_use_id=first.tool_use_id,
            content_type=first.content_type,
            thread_id=first.thread_id,
        ),
        merge_count,
    )


async def _coalesce_status_updates(
    queue: asyncio.Queue[MessageTask],
    first: StatusUpdateTask,
    lock: asyncio.Lock,
) -> tuple[StatusUpdateTask, int]:
    """Keep only the latest pending status_update for the same topic/window.

    Returns: (selected_task, dropped_count) where dropped_count is the number
    of queued tasks removed and already accounted for.
    """
    selected = first
    dropped = 0
    key = (thread_key(first.thread_id), first.window_id)

    async with lock:
        items = _drain_queue(queue)
        remaining: list[MessageTask] = []

        for task in items:
            if not isinstance(task, StatusUpdateTask):
                remaining.append(task)
                continue
            task_key = (thread_key(task.thread_id), task.window_id)
            if task_key == key:
                selected = task
                dropped += 1
            else:
                remaining.append(task)

        for item in remaining:
            queue.put_nowait(item)
            queue.task_done()

    return selected, dropped


async def _handle_content_task(
    bot: Bot,
    user_id: int,
    task: ContentTask,
    queue: asyncio.Queue[MessageTask],
    lock: asyncio.Lock,
) -> int:
    """Route a content task through batching or normal processing.

    Returns the number of additional merged tasks (caller must call task_done for each).
    """
    if task.content_type in ("tool_use", "tool_result") and is_tool_calls_hidden(
        task.window_id
    ):
        return 0

    if is_batch_eligible(task):
        followup = await process_tool_event(bot, user_id, task)
        if followup is not None:
            await _process_content_task(bot, user_id, followup)
        return 0

    await flush_if_active(bot, user_id, task)

    merged_task, merge_count = await _merge_content_tasks(queue, task, lock)
    if merge_count > 0:
        logger.debug("Merged %d tasks for user %s", merge_count, user_id)
    await _process_content_task(bot, user_id, merged_task)
    return merge_count


def _is_ghost_window_task_at_enqueue(window_id: str) -> bool:
    """Return True if the window is no longer bound to any topic."""
    if window_id and not thread_router.has_window(window_id):
        logger.debug("Skipping enqueue for unbound window %s", window_id)
        return True
    return False


async def _flush_batch_for_task(user_id: int, task: MessageTask, bot: Bot) -> None:
    """Flush any active batch for the topic that owns this task."""
    tkey = thread_key(task.thread_id)
    if has_active_batch(user_id, tkey):
        await flush_batch(bot, user_id, tkey)


async def _dispatch(
    bot: Bot,
    user_id: int,
    task: MessageTask,
    queue: asyncio.Queue[MessageTask],
    lock: asyncio.Lock,
) -> int:
    """Dispatch a task by type. Returns extra task_done count for merged tasks."""
    match task:
        case ContentTask() as ct:
            return await _handle_content_task(bot, user_id, ct, queue, lock)
        case StatusUpdateTask() as st:
            await _flush_batch_for_task(user_id, st, bot)
            collapsed_task, dropped = await _coalesce_status_updates(queue, st, lock)
            if dropped > 0:
                for _ in range(dropped):
                    queue.task_done()
            await process_status_update(bot, user_id, collapsed_task)
            return 0
        case StatusClearTask() as cl:
            await _flush_batch_for_task(user_id, cl, bot)
            await process_status_clear(bot, user_id, cl)
            return 0
        case _ as unreachable:
            assert_never(unreachable)


async def _message_queue_worker(bot: Bot, user_id: int) -> None:
    """Process message tasks for a user sequentially."""
    queue = _message_queues[user_id]
    lock = _queue_locks[user_id]
    logger.debug("Message queue worker started for user %s", user_id)

    while True:
        try:
            task = await queue.get()
            try:
                while True:
                    try:
                        extra = await _dispatch(bot, user_id, task, queue, lock)
                        for _ in range(extra):
                            queue.task_done()
                        break
                    except RetryAfter as e:
                        retry_secs = min(
                            60,
                            (
                                e.retry_after
                                if isinstance(e.retry_after, int)
                                else int(e.retry_after.total_seconds())
                            ),
                        )
                        logger.warning(
                            "Flood control for user %s, pausing %ss",
                            user_id,
                            retry_secs,
                        )
                        await asyncio.sleep(retry_secs)
            except (TelegramError, OSError):  # fmt: skip
                logger.exception(
                    "Error processing message task for user %s (thread %s)",
                    user_id,
                    getattr(task, "thread_id", None),
                )
            finally:
                queue.task_done()
        except asyncio.CancelledError:
            logger.debug("Message queue worker cancelled for user %s", user_id)
            break
        except Exception:
            logger.exception(
                "Unexpected error in queue worker for user %s",
                user_id,
            )


async def _process_content_task(bot: Bot, user_id: int, task: ContentTask) -> None:
    """Process a content message task."""
    tkey = thread_key(task.thread_id)
    chat_id = thread_router.resolve_chat_id(user_id, task.thread_id)

    if task.content_type == "tool_result" and task.tool_use_id:
        _tkey = (task.tool_use_id, user_id, tkey)
        edit_msg_id = _tool_msg_ids.pop(_tkey, None)
        if edit_msg_id is not None:
            await clear_status_message(bot, user_id, tkey)
            full_text = "\n\n".join(task.parts)
            success = await edit_with_fallback(
                bot,
                chat_id,
                edit_msg_id,
                full_text,
            )
            if success:
                return
            logger.debug("Failed to edit tool msg %s, sending new", edit_msg_id)

    first_part = True
    last_msg_id: int | None = None
    for part in task.parts:
        sent = None

        if first_part:
            first_part = False
            converted_msg_id = await convert_status_to_content(
                bot,
                user_id,
                tkey,
                task.window_id,
                part,
            )
            if converted_msg_id is not None:
                last_msg_id = converted_msg_id
                continue

        sent = await rate_limit_send_message(
            bot, chat_id, part, **send_kwargs(task.thread_id)
        )

        if sent:
            last_msg_id = sent.message_id

    if last_msg_id and task.tool_use_id and task.content_type == "tool_use":
        _tool_msg_ids[(task.tool_use_id, user_id, tkey)] = last_msg_id


async def enqueue_content_message(
    bot: Bot,
    user_id: int,
    window_id: str,
    parts: list[str],
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    content_type: ContentType = "text",
    thread_id: int | None = None,
) -> None:
    """Enqueue a content message task."""
    if _is_ghost_window_task_at_enqueue(window_id):
        return
    queue = get_or_create_queue(bot, user_id)

    task = ContentTask(
        window_id=window_id,
        parts=tuple(parts),
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content_type=content_type,
        thread_id=thread_id,
    )
    queue.put_nowait(task)


async def enqueue_status_update(
    bot: Bot,
    user_id: int,
    window_id: str,
    status_text: str | None,
    thread_id: int | None = None,
) -> None:
    """Enqueue status update or clear."""
    queue = get_or_create_queue(bot, user_id)

    if status_text is not None:
        task: MessageTask = StatusUpdateTask(
            window_id=window_id,
            text=status_text,
            thread_id=thread_id,
        )
    else:
        task = StatusClearTask(
            window_id=window_id,
            thread_id=thread_id,
        )

    queue.put_nowait(task)


@topic_state.register("topic")
def clear_tool_msg_ids_for_topic(user_id: int, thread_id: int | None = None) -> None:
    """Clear tool message ID tracking for a specific topic.

    Removes all entries in _tool_msg_ids that match the given user and thread.
    """
    tkey = thread_key(thread_id)
    keys_to_remove = [
        key for key in _tool_msg_ids if key[1] == user_id and key[2] == tkey
    ]
    for key in keys_to_remove:
        _tool_msg_ids.pop(key, None)


async def shutdown_workers() -> None:
    """Stop all queue workers (called during bot shutdown)."""
    for _, worker in list(_queue_workers.items()):
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    _queue_workers.clear()
    _message_queues.clear()
    _queue_locks.clear()
    clear_all_batches()
    logger.info("Message queue workers stopped")
