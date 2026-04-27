"""Claude tool-use batching — state machine, formatting, edit-in-place delivery.

Accumulates consecutive tool_use / tool_result messages into compact batch
messages displayed as a single Telegram message that is edited in place as
results arrive.  Overflow (entry count or character budget) triggers a flush
and a new batch.

Key components:
  - ToolBatchEntry / ToolBatch: batch state dataclasses
  - process_tool_event: state-machine entry point (add tool_use or tool_result)
  - flush_batch: finalize and send the last edit for a batch
  - is_batch_eligible: predicate combining task eligibility and window mode
  - format_batch_message: render batch entries as compact text
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
from telegram import Bot

from ..telegram_draft import DraftStream
from ..thread_router import thread_router
from ..topic_state_registry import topic_state
from ..window_query import get_batch_mode
from .message_task import ContentTask, thread_key

logger = structlog.get_logger()

BATCH_MAX_LENGTH = 2800
BATCH_MAX_ENTRIES = 9


@dataclass
class ToolBatchEntry:
    """A single tool call entry within a batch."""

    tool_use_id: str | None
    tool_use_text: str  # Formatted summary from build_response_parts
    tool_result_text: str | None = None  # None until result arrives
    tool_name: str | None = None


@dataclass
class ToolBatch:
    """Accumulator for consecutive tool calls to batch into one Telegram message."""

    window_id: str
    thread_id: int  # thread_id_or_0
    entries: list[ToolBatchEntry] = field(default_factory=list)
    telegram_msg_id: int | None = None
    total_length: int = 0
    draft: DraftStream | None = None


# Active tool batches: (user_id, thread_id_or_0) -> ToolBatch
_active_batches: dict[tuple[int, int], ToolBatch] = {}

_MARKDOWN_TOOL_PREFIX_RE = re.compile(r"^\*\*([^*]+)\*\*(.*)$")
_PLAIN_TASK_CREATE_RE = re.compile(r"^TaskCreate\s+(.+)$")
_TASK_TOOL_NAMES = frozenset({"TaskCreate", "TaskUpdate", "TaskList"})
_MIN_BACKTICK_WRAPPED_LENGTH = 2

_BATCH_ERROR_RE = re.compile(
    r"\b(error|FAILED|fail(ed|ure[s]?)?|Exception|Traceback|exit code [1-9]\d*)\b",
    re.IGNORECASE,
)
_BATCH_SUCCESS_RE = re.compile(r"\b(passed|success|exit code 0)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public predicates
# ---------------------------------------------------------------------------


def is_batch_eligible(task: ContentTask) -> bool:
    """Check if a task should go through the batching pipeline."""
    return (
        task.content_type in ("tool_use", "tool_result")
        and get_batch_mode(task.window_id) == "batched"
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_batch_message(
    entries: list[ToolBatchEntry], subagent_label: str | None = None
) -> str:
    """Render a batch of tool calls as a single compact message.

    Format:
        ⚡ 3 tool calls [🤖 write-tests]
        📖 Read  src/foo.py       ⎿  42 lines
        ✏️ Edit  src/foo.py       ⎿  +3 −1
        ⚡ Bash  make test        ⏳
    """
    task_create_message = _format_task_create_batch(entries, subagent_label)
    if task_create_message is not None:
        return task_create_message

    count = len(entries)
    label = "tool call" if count == 1 else "tool calls"
    header = f"\u26a1 {count} {label}"
    has_task_tools = any(entry.tool_name in _TASK_TOOL_NAMES for entry in entries)
    if subagent_label and not has_task_tools:
        header = f"{header} [{subagent_label}]"
    lines = [header]
    if subagent_label and has_task_tools:
        lines.append(subagent_label)

    lines.extend(_format_mixed_batch_lines(entries))

    return "\n".join(lines)


def _format_task_create_batch(
    entries: list[ToolBatchEntry], subagent_label: str | None
) -> str | None:
    """Render TaskCreate bursts as a numbered task list."""
    if not entries or any(entry.tool_name != "TaskCreate" for entry in entries):
        return None

    titles = [_extract_task_create_title(entry) for entry in entries]
    if any(not title for title in titles):
        return None

    action = (
        "Created"
        if all(entry.tool_result_text is not None for entry in entries)
        else "Creating"
    )
    task_label = "task" if len(entries) == 1 else "tasks"
    lines: list[str] = []
    if subagent_label:
        lines.append(subagent_label)
    if action == "Creating":
        lines.append(f"{action} {len(entries)} {task_label}\u2026")
    else:
        lines.append(f"{action} {len(entries)} {task_label}")
    lines.extend(f"{index}. {title}" for index, title in enumerate(titles, start=1))
    return "\n".join(lines)


def _format_mixed_batch_lines(entries: list[ToolBatchEntry]) -> list[str]:
    """Render batch body lines, grouping task-tool runs into task sections."""
    lines: list[str] = []
    index = 0

    while index < len(entries):
        entry = entries[index]
        if entry.tool_name == "TaskCreate":
            task_entries: list[ToolBatchEntry] = []
            while index < len(entries) and entries[index].tool_name == "TaskCreate":
                task_entries.append(entries[index])
                index += 1
            section = _format_task_create_section(task_entries)
            if section:
                lines.extend(section)
            else:
                lines.extend(_format_batch_entry(task) for task in task_entries)
            continue
        if entry.tool_name == "TaskUpdate":
            update_entries: list[ToolBatchEntry] = []
            while index < len(entries) and entries[index].tool_name == "TaskUpdate":
                update_entries.append(entries[index])
                index += 1
            section = _format_task_update_section(update_entries)
            if section:
                lines.extend(section)
            else:
                lines.extend(_format_batch_entry(task) for task in update_entries)
            continue
        if entry.tool_name == "TaskList":
            lines.extend(_format_task_list_section(entry))
            index += 1
            continue

        lines.append(_format_batch_entry(entry))
        index += 1

    return lines


def _format_task_create_section(entries: list[ToolBatchEntry]) -> list[str]:
    """Render a contiguous TaskCreate run inside a mixed batch."""
    if not entries:
        return []

    titles = [_extract_task_create_title(entry) for entry in entries]
    if any(not title for title in titles):
        return []

    action = (
        "Created"
        if all(entry.tool_result_text is not None for entry in entries)
        else "Creating"
    )
    task_label = "task" if len(entries) == 1 else "tasks"
    heading = (
        f"{action} {len(entries)} {task_label}\u2026"
        if action == "Creating"
        else f"{action} {len(entries)} {task_label}"
    )
    return [
        heading,
        *(f"{index}. {title}" for index, title in enumerate(titles, start=1)),
    ]


def _format_task_update_section(entries: list[ToolBatchEntry]) -> list[str]:
    """Render a contiguous TaskUpdate run inside a mixed batch."""
    if not entries:
        return []

    labels = [_extract_task_tool_suffix(entry) for entry in entries]
    if any(not label for label in labels):
        return []

    action = (
        "Updated"
        if all(entry.tool_result_text is not None for entry in entries)
        else "Updating"
    )
    task_label = "task" if len(entries) == 1 else "tasks"
    heading = (
        f"{action} {len(entries)} {task_label}\u2026"
        if action == "Updating"
        else f"{action} {len(entries)} {task_label}"
    )
    return [heading, *(f"- {label}" for label in labels)]


def _format_task_list_section(entry: ToolBatchEntry) -> list[str]:
    """Render TaskList as task-list sync progress."""
    summary = _extract_task_tool_suffix(entry)
    heading = (
        "Synced task list"
        if entry.tool_result_text is not None
        else "Refreshing task list\u2026"
    )
    if summary and summary != "refresh":
        heading = f"{heading} ({summary})"
    return [heading]


def _batch_result_prefix(result_text: str) -> str:
    """Choose a result indicator prefix based on content."""
    if _BATCH_ERROR_RE.search(result_text):
        return "\u274c"
    if _BATCH_SUCCESS_RE.search(result_text):
        return "\u2705"
    return "\u23bf"


def _format_batch_entry(entry: ToolBatchEntry) -> str:
    """Render one standard batch row."""
    line = entry.tool_use_text
    if entry.tool_result_text is not None:
        prefix = _batch_result_prefix(entry.tool_result_text)
        return f"{line}  {prefix}  {entry.tool_result_text}"
    return f"{line}  \u23f3"


def _extract_task_create_title(entry: ToolBatchEntry) -> str:
    """Extract the visible title from a TaskCreate summary."""
    return _extract_task_tool_suffix(entry)


def _extract_task_tool_suffix(entry: ToolBatchEntry) -> str:
    """Extract the summary text after a markdown/plain task-tool prefix."""
    text = entry.tool_use_text.strip()
    if not text:
        return ""

    markdown_match = _MARKDOWN_TOOL_PREFIX_RE.match(text)
    if markdown_match:
        _tool_name, suffix = markdown_match.groups()
        stripped = suffix.strip()
        if (
            stripped.startswith("`")
            and stripped.endswith("`")
            and len(stripped) >= _MIN_BACKTICK_WRAPPED_LENGTH
        ):
            stripped = stripped[1:-1].strip()
        return stripped

    plain_match = _PLAIN_TASK_CREATE_RE.match(text)
    if plain_match:
        return plain_match.group(1).strip()

    return text


# ---------------------------------------------------------------------------
# State machine — process_tool_event / flush_batch
# ---------------------------------------------------------------------------


async def _send_or_edit_batch(
    bot: Bot,
    user_id: int,
    batch: ToolBatch,
    chat_id: int,
    raw_thread_id: int | None,
    thread_id_or_0: int,
) -> None:
    """Send a new batch message or replace the existing draft text."""
    from ..claude_task_state import build_subagent_label, get_subagent_names
    from .status_bubble import clear_status_message

    subagent_label = build_subagent_label(get_subagent_names(batch.window_id))
    batch_text = format_batch_message(batch.entries, subagent_label=subagent_label)

    if batch.draft is None:
        await clear_status_message(bot, user_id, thread_id_or_0)
        await _rate_limit_chat(chat_id)
        batch.draft = DraftStream(
            bot,
            chat_id,
            message_thread_id=raw_thread_id,
        )
        msg_id = await batch.draft.start(batch_text)
        if msg_id is not None:
            batch.telegram_msg_id = msg_id
        else:
            batch.draft = None
    else:
        await batch.draft.replace(batch_text)


async def _rate_limit_chat(chat_id: int) -> None:
    """Acquire the per-chat rate-limit slot before opening a new draft."""
    from .message_sender import rate_limit_send

    await rate_limit_send(chat_id)


async def _handle_tool_result(
    bot: Bot,
    user_id: int,
    task: ContentTask,
    batch: ToolBatch | None,
    thread_id_or_0: int,
) -> tuple[ToolBatch | None, ContentTask | None]:
    """Process a tool_result event, updating the matching batch entry.

    Returns (updated_batch, followup) — followup is non-None when the result
    could not be absorbed into the batch and should be delivered as content.
    """
    if not task.tool_use_id or not batch:
        return None, task
    for entry in batch.entries:
        if entry.tool_use_id == task.tool_use_id:
            text = "\n".join(task.parts) if task.parts else ""
            first_line = text.split("\n", 1)[0][:200]
            entry.tool_result_text = first_line
            return batch, None
    await flush_batch(bot, user_id, thread_id_or_0)
    return None, task


def _add_tool_use_entry(
    task: ContentTask,
    batch: ToolBatch,
) -> bool:
    """Append a tool_use entry to the batch. Returns True if overflow occurred."""
    entry_text = "\n".join(task.parts) if task.parts else "tool call"
    if (
        len(batch.entries) >= BATCH_MAX_ENTRIES
        or batch.total_length + len(entry_text) > BATCH_MAX_LENGTH
    ):
        return True
    entry = ToolBatchEntry(
        tool_use_id=task.tool_use_id,
        tool_use_text=entry_text,
        tool_name=task.tool_name,
    )
    batch.entries.append(entry)
    batch.total_length += len(entry_text)
    return False


async def process_tool_event(
    bot: Bot,
    user_id: int,
    task: ContentTask,
) -> ContentTask | None:
    """Add a tool_use or tool_result to the active batch, send/edit the batch message.

    Returns None if absorbed into the batch; returns a ContentTask if the queue
    worker should deliver it as regular content (overflow, unmatched result, etc).
    """
    window_id = task.window_id
    thread_id_or_0 = thread_key(task.thread_id)
    bkey = (user_id, thread_id_or_0)
    chat_id = thread_router.resolve_chat_id(user_id, task.thread_id)
    batch = _active_batches.get(bkey)

    if task.content_type == "tool_result":
        batch, followup = await _handle_tool_result(
            bot, user_id, task, batch, thread_id_or_0
        )
        if batch is None:
            return followup
    elif task.content_type == "tool_use":
        result = await _handle_tool_use_event(
            bot, user_id, task, batch, window_id, thread_id_or_0, bkey
        )
        if isinstance(result, ContentTask):
            return result
        if result is None:
            return None
        batch = result
    else:
        return task

    await _send_or_edit_batch(
        bot, user_id, batch, chat_id, task.thread_id, thread_id_or_0
    )
    return None


async def _handle_tool_use_event(
    bot: Bot,
    user_id: int,
    task: ContentTask,
    batch: ToolBatch | None,
    window_id: str,
    thread_id_or_0: int,
    bkey: tuple[int, int],
) -> ToolBatch | ContentTask | None:
    """Process a tool_use event, creating/flushing batches as needed.

    Returns a ToolBatch to continue with send/edit, a ContentTask if the caller
    should deliver it as regular content (double-overflow), or None on error.
    """
    if batch and batch.window_id != window_id:
        await flush_batch(bot, user_id, thread_id_or_0)
        batch = None

    if not batch:
        batch = ToolBatch(window_id=window_id, thread_id=thread_id_or_0)
        _active_batches[bkey] = batch

    overflow = _add_tool_use_entry(task, batch)
    if overflow:
        await flush_batch(bot, user_id, thread_id_or_0)
        batch = ToolBatch(window_id=window_id, thread_id=thread_id_or_0)
        still_overflow = _add_tool_use_entry(task, batch)
        _active_batches[bkey] = batch
        if still_overflow:
            _active_batches.pop(bkey, None)
            return task

    return batch


async def flush_if_active(bot: Bot, user_id: int, task: ContentTask) -> None:
    """Flush any active batch for the same topic before delivering non-batchable content."""
    thread_id_or_0 = thread_key(task.thread_id)
    if has_active_batch(user_id, thread_id_or_0):
        await flush_batch(bot, user_id, thread_id_or_0)


async def flush_batch(bot: Bot, user_id: int, thread_id_or_0: int) -> None:
    """Finalize the active batch: do a final edit and clear state."""
    from telegram.error import TelegramError

    bkey = (user_id, thread_id_or_0)
    batch = _active_batches.pop(bkey, None)
    if not batch or not batch.entries:
        return

    thread_id: int | None = thread_id_or_0 if thread_id_or_0 != 0 else None
    chat_id = thread_router.resolve_chat_id(user_id, thread_id)

    from ..claude_task_state import build_subagent_label, get_subagent_names

    subagent_label = build_subagent_label(get_subagent_names(batch.window_id))
    batch_text = format_batch_message(batch.entries, subagent_label=subagent_label)

    if batch.draft is not None and not batch.draft.closed:
        try:
            await batch.draft.finalize(batch_text)
        except TelegramError as exc:
            logger.warning("flush_batch finalize failed: %s", exc)
        return

    if batch.telegram_msg_id is not None:
        # Existing message but no active draft (e.g. batch built before
        # adoption, or draft already closed).  Edit the message in place.
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=batch.telegram_msg_id,
                text=batch_text,
            )
        except TelegramError as exc:
            logger.warning("flush_batch edit failed: %s", exc)
        return

    # No prior message at all — open a fresh draft and finalize immediately.
    await _rate_limit_chat(chat_id)
    draft = DraftStream(bot, chat_id, message_thread_id=thread_id)
    try:
        await draft.start(batch_text)
        await draft.finalize()
    except TelegramError as exc:
        logger.warning("flush_batch start+finalize failed: %s", exc)


def has_active_batch(user_id: int, thread_id_or_0: int) -> bool:
    """Check if there is an active batch for a (user, thread) pair."""
    return (user_id, thread_id_or_0) in _active_batches


@topic_state.register("topic")
def clear_batch_for_topic(user_id: int, thread_id: int | None = None) -> None:
    """Clear active batch for a specific topic (called on topic cleanup)."""
    _active_batches.pop((user_id, thread_key(thread_id)), None)


def clear_all_batches() -> None:
    """Clear all active batches (called on shutdown)."""
    _active_batches.clear()
