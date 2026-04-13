"""Per-user message queue management for ordered message delivery.

Queue primitives (FIFO ordering, merging, coalescing) and the worker loop
that dispatches tasks to ``tool_batch`` and ``status_bubble``.  Status I/O,
task-list formatting, and keyboard rendering live in ``status_bubble``;
tool-use batching lives in ``tool_batch``.
"""

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Literal

import structlog
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from ..thread_router import thread_router
from ..topic_state_registry import topic_state
from ..utils import task_done_callback
from .message_sender import edit_with_fallback, rate_limit_send_message
from .status_bubble import (
    clear_status_message,
    convert_status_to_content,
    process_status_clear_task,
    process_status_update_task,
)
from .tool_batch import (
    _active_batches,
    flush_batch,
    is_batch_eligible,
    process_tool_event,
)

logger = structlog.get_logger()

MERGE_MAX_LENGTH = 3800  # Leave room within Telegram's 4096 char message limit


@dataclass
class MessageTask:
    """Message task for queue processing."""

    task_type: Literal["content", "status_update", "status_clear"]
    text: str | None = None
    window_id: str | None = None
    # content type fields
    parts: list[str] = field(default_factory=list)
    tool_use_id: str | None = None
    tool_name: str | None = None
    content_type: str = "text"
    thread_id: int | None = None  # Telegram topic thread_id for targeted send


# Per-user message queues and worker tasks
_message_queues: dict[int, asyncio.Queue[MessageTask]] = {}
_queue_workers: dict[int, asyncio.Task[None]] = {}
_queue_locks: dict[int, asyncio.Lock] = {}  # Protect drain/refill operations

# Map (tool_use_id, user_id, thread_id_or_0) -> telegram message_id
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


def _inspect_queue(queue: asyncio.Queue[MessageTask]) -> list[MessageTask]:
    """Non-destructively inspect all items in queue.

    Drains the queue and returns all items. Caller must refill.
    """
    items: list[MessageTask] = []
    while not queue.empty():
        try:
            item = queue.get_nowait()
            items.append(item)
        except asyncio.QueueEmpty:
            break
    return items


def _can_merge_tasks(base: MessageTask, candidate: MessageTask) -> bool:
    """Check if two content tasks can be merged."""
    if base.window_id != candidate.window_id:
        return False
    if candidate.task_type != "content":
        return False
    # tool_use/tool_result break merge chain
    # - tool_use: will be edited later by tool_result
    # - tool_result: edits previous message, merging would cause order issues
    if base.content_type in ("tool_use", "tool_result"):
        return False
    return candidate.content_type not in ("tool_use", "tool_result")


async def _merge_content_tasks(
    queue: asyncio.Queue[MessageTask],
    first: MessageTask,
    lock: asyncio.Lock,
) -> tuple[MessageTask, int]:
    """Merge consecutive content tasks from queue.

    Returns: (merged_task, merge_count) where merge_count is the number of
    additional tasks merged (0 if no merging occurred).

    Note on queue counter management:
        When we put items back, we call task_done() to compensate for the
        internal counter increment caused by put_nowait(). This is necessary
        because the items were already counted when originally enqueued.
        Without this compensation, queue.join() would wait indefinitely.
    """
    merged_parts = list(first.parts)
    current_length = sum(len(p) for p in merged_parts)
    merge_count = 0

    async with lock:
        items = _inspect_queue(queue)
        remaining: list[MessageTask] = []

        for i, task in enumerate(items):
            if not _can_merge_tasks(first, task):
                # Can't merge, keep this and all remaining items
                remaining = items[i:]
                break

            # Check length before merging
            task_length = sum(len(p) for p in task.parts)
            if current_length + task_length > MERGE_MAX_LENGTH:
                # Too long, stop merging
                remaining = items[i:]
                break

            merged_parts.extend(task.parts)
            current_length += task_length
            merge_count += 1

        # Put remaining items back into the queue
        for item in remaining:
            queue.put_nowait(item)
            # Compensate: this item was already counted when first enqueued,
            # put_nowait adds a duplicate count that must be removed
            queue.task_done()

    if merge_count == 0:
        return first, 0

    return (
        MessageTask(
            task_type="content",
            window_id=first.window_id,
            parts=merged_parts,
            tool_use_id=first.tool_use_id,
            content_type=first.content_type,
            thread_id=first.thread_id,
        ),
        merge_count,
    )


async def _coalesce_status_updates(
    queue: asyncio.Queue[MessageTask],
    first: MessageTask,
    lock: asyncio.Lock,
) -> tuple[MessageTask, int]:
    """Keep only the latest pending status_update for the same topic/window.

    Returns: (selected_task, dropped_count) where dropped_count is the number
    of queued tasks removed and already accounted for.
    """
    if first.task_type != "status_update":
        return first, 0

    selected = first
    dropped = 0
    key = (first.thread_id or 0, first.window_id or "")

    async with lock:
        items = _inspect_queue(queue)
        remaining: list[MessageTask] = []

        for task in items:
            if task.task_type != "status_update":
                remaining.append(task)
                continue
            task_key = (task.thread_id or 0, task.window_id or "")
            if task_key == key:
                # Same topic/window status update; keep latest only.
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
    task: MessageTask,
    queue: asyncio.Queue[MessageTask],
    lock: asyncio.Lock,
) -> int:
    """Route a content task through batching or normal processing.

    Returns the number of additional merged tasks (caller must call task_done for each).
    """
    if task.window_id and is_batch_eligible(task, task.window_id):
        await process_tool_event(bot, user_id, task)
        return 0

    # Non-tool content: flush any active batch first
    thread_id = task.thread_id or 0
    bkey = (user_id, thread_id)
    if bkey in _active_batches:
        await flush_batch(bot, user_id, thread_id)

    # Try to merge consecutive content tasks
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
                        if task.task_type == "content":
                            extra = await _handle_content_task(
                                bot, user_id, task, queue, lock
                            )
                            for _ in range(extra):
                                queue.task_done()
                        elif task.task_type == "status_update":
                            # Flush batch before status
                            thread_id = task.thread_id or 0
                            bkey = (user_id, thread_id)
                            if bkey in _active_batches:
                                await flush_batch(bot, user_id, thread_id)
                            collapsed_task, dropped = await _coalesce_status_updates(
                                queue, task, lock
                            )
                            if dropped > 0:
                                for _ in range(dropped):
                                    queue.task_done()
                            await process_status_update_task(
                                bot, user_id, collapsed_task
                            )
                        elif task.task_type == "status_clear":
                            thread_id = task.thread_id or 0
                            bkey = (user_id, thread_id)
                            if bkey in _active_batches:
                                await flush_batch(bot, user_id, thread_id)
                            await process_status_clear_task(bot, user_id, task)
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
                    task.thread_id,
                )
            finally:
                queue.task_done()
        except asyncio.CancelledError:
            logger.debug("Message queue worker cancelled for user %s", user_id)
            break
        except Exception:
            # Catch-all: any error (network, programming, etc.) must not kill
            # the queue worker — log and continue processing next message.
            logger.exception(
                "Unexpected error in queue worker for user %s",
                user_id,
            )


def _send_kwargs(thread_id: int | None) -> dict[str, int]:
    """Build message_thread_id kwargs for bot.send_message()."""
    if thread_id is not None:
        return {"message_thread_id": thread_id}
    return {}


async def _process_content_task(bot: Bot, user_id: int, task: MessageTask) -> None:
    """Process a content message task."""
    window_id = task.window_id or ""
    thread_id = task.thread_id or 0
    chat_id = thread_router.resolve_chat_id(user_id, task.thread_id)

    # 1. Handle tool_result editing (merged parts are edited together)
    if task.content_type == "tool_result" and task.tool_use_id:
        _tkey = (task.tool_use_id, user_id, thread_id)
        edit_msg_id = _tool_msg_ids.pop(_tkey, None)
        if edit_msg_id is not None:
            # Clear status message first
            await clear_status_message(bot, user_id, thread_id)
            # Join all parts for editing (merged content goes together)
            full_text = "\n\n".join(task.parts)
            success = await edit_with_fallback(
                bot,
                chat_id,
                edit_msg_id,
                full_text,
            )
            if success:
                # Status will be recreated by the poll loop — no eager send.
                return
            logger.debug("Failed to edit tool msg %s, sending new", edit_msg_id)
            # Fall through to send as new message

    # 2. Send content messages, converting status message to first content part
    first_part = True
    last_msg_id: int | None = None
    for part in task.parts:
        sent = None

        # For first part, try to convert status message to content (edit instead of delete)
        if first_part:
            first_part = False
            converted_msg_id = await convert_status_to_content(
                bot,
                user_id,
                thread_id,
                window_id,
                part,
            )
            if converted_msg_id is not None:
                last_msg_id = converted_msg_id
                continue

        sent = await rate_limit_send_message(
            bot,
            chat_id,
            part,
            **_send_kwargs(task.thread_id),  # type: ignore[arg-type]
        )

        if sent:
            last_msg_id = sent.message_id

    # 3. Record tool_use message ID for later editing
    if last_msg_id and task.tool_use_id and task.content_type == "tool_use":
        _tool_msg_ids[(task.tool_use_id, user_id, thread_id)] = last_msg_id

    # Status will be recreated by the 1-second poll loop — no need to
    # eagerly send a new status message here (doing so caused pile-up).


async def enqueue_content_message(
    bot: Bot,
    user_id: int,
    window_id: str,
    parts: list[str],
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    content_type: str = "text",
    text: str | None = None,
    thread_id: int | None = None,
) -> None:
    """Enqueue a content message task."""
    if _is_ghost_window_task_at_enqueue(window_id):
        return
    queue = get_or_create_queue(bot, user_id)

    task = MessageTask(
        task_type="content",
        text=text,
        window_id=window_id,
        parts=parts,
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
    """Enqueue status update."""
    queue = get_or_create_queue(bot, user_id)

    if status_text:
        task = MessageTask(
            task_type="status_update",
            text=status_text,
            window_id=window_id,
            thread_id=thread_id,
        )
    else:
        task = MessageTask(
            task_type="status_clear",
            window_id=window_id,
            thread_id=thread_id,
        )

    queue.put_nowait(task)


@topic_state.register("topic")
def clear_tool_msg_ids_for_topic(user_id: int, thread_id: int | None = None) -> None:
    """Clear tool message ID tracking for a specific topic.

    Removes all entries in _tool_msg_ids that match the given user and thread.
    """
    thread_id_or_0 = thread_id or 0
    # Find and remove all matching keys
    keys_to_remove = [
        key for key in _tool_msg_ids if key[1] == user_id and key[2] == thread_id_or_0
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
    _active_batches.clear()
    logger.info("Message queue workers stopped")
