"""Status-bubble rendering, send/edit/clear, and task-status formatting.

Owns the per-topic status message lifecycle: keyboard layout, send/edit/clear
I/O, Claude task-list formatting, and status-to-content conversion.  The queue
worker in ``message_queue`` delegates ``StatusUpdateTask`` / ``StatusClearTask``
here; ``convert_status_to_content`` is defined here and imported by
``message_queue._process_content_task``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from ..claude_task_state import get_claude_task_snapshot, get_claude_wait_header
from ..window_query import get_notification_mode
from ..thread_router import thread_router
from .callback_data import (
    CB_STATUS_ESC,
    CB_STATUS_NOTIFY,
    CB_STATUS_RECALL,
    CB_STATUS_REMOTE,
    CB_STATUS_SCREENSHOT,
    NOTIFY_MODE_ICONS,
)
from .message_sender import edit_with_fallback, rate_limit_send_message, send_kwargs
from .message_task import StatusClearTask, StatusUpdateTask, thread_key

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# RC-active provider (dependency injection — severs polling_strategies import)
# ---------------------------------------------------------------------------


def _rc_active_default(_window_id: str) -> bool:
    return False


_rc_active_fn: Callable[[str], bool] = _rc_active_default


def register_rc_active_provider(fn: Callable[[str], bool]) -> None:
    """Wire the polling-layer RC-active lookup (called once from bot.py setup).

    Avoids a direct status_bubble → polling_strategies import by accepting
    a callable rather than importing terminal_screen_buffer directly.
    """
    global _rc_active_fn
    _rc_active_fn = fn


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# Status message tracking: (user_id, thread_key) -> (message_id, window_id, last_text, chat_id)
_status_msg_info: dict[tuple[int, int], tuple[int, str, str, int]] = {}


# ---------------------------------------------------------------------------
# Keyboard builder
# ---------------------------------------------------------------------------


def build_status_keyboard(
    window_id: str,
    history: list[str] | None = None,
    *,
    rc_active: bool = False,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for status messages.

    Layout:
      Row 1 (optional): up to 2 history-recall buttons
      Row 2: [Esc] [Screenshot] [Bell] [RC]
    """
    from .command_history import truncate_for_display

    rows: list[list[InlineKeyboardButton]] = []

    if history:
        hist_row: list[InlineKeyboardButton] = []
        for idx, cmd in enumerate(history[:2]):
            label = truncate_for_display(cmd, 20)
            hist_row.append(
                InlineKeyboardButton(
                    f"\u2191 {label}",
                    callback_data=f"{CB_STATUS_RECALL}{window_id}:{idx}"[:64],
                )
            )
        rows.append(hist_row)

    mode = get_notification_mode(window_id)
    bell = NOTIFY_MODE_ICONS.get(mode, "\U0001f514")
    rc_label = "📡✓" if rc_active else "📡"
    rows.append(
        [
            InlineKeyboardButton(
                "\u238b Esc",
                callback_data=f"{CB_STATUS_ESC}{window_id}"[:64],
            ),
            InlineKeyboardButton(
                "\U0001f4f8",
                callback_data=f"{CB_STATUS_SCREENSHOT}{window_id}"[:64],
            ),
            InlineKeyboardButton(
                bell,
                callback_data=f"{CB_STATUS_NOTIFY}{window_id}"[:64],
            ),
            InlineKeyboardButton(
                rc_label,
                callback_data=f"{CB_STATUS_REMOTE}{window_id}"[:64],
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_idle_history(
    user_id: int, thread_id_or_0: int, status_text: str
) -> list[str] | None:
    """Return history list if the status is idle, else None."""
    from .callback_data import IDLE_STATUS_TEXT
    from .command_history import get_history

    first_line = status_text.split("\n", 1)[0]
    if first_line != IDLE_STATUS_TEXT:
        return None
    return get_history(user_id, thread_id_or_0, limit=2) or None


# ---------------------------------------------------------------------------
# Claude task-status formatting
# ---------------------------------------------------------------------------


def format_claude_task_status(window_id: str, base_text: str | None) -> str | None:
    """Compose Claude wait/task state into the status bubble text."""
    snapshot = get_claude_task_snapshot(window_id)
    wait_header = get_claude_wait_header(window_id)
    if snapshot is None and not wait_header:
        return base_text

    lines: list[str] = []
    header = wait_header or base_text
    if header:
        lines.append(header)

    if snapshot is not None:
        lines.append(
            f"{snapshot.total_count} tasks ({snapshot.done_count} done, {snapshot.open_count} open)"
        )
        visible_items = snapshot.items[:8]
        for item in visible_items:
            if item.status == "completed":
                glyph = "\u2714"
            elif item.status == "in_progress":
                glyph = "\u25d4"
            else:
                glyph = "\u25fb"

            label = (
                item.active_form
                if item.status == "in_progress" and item.active_form
                else item.subject
            )
            if item.owner:
                label = f"{label} ({item.owner})"
            line = f"{glyph} #{item.task_id} {label}".rstrip()
            if item.blocked_by:
                blocked = ", ".join(f"#{task_id}" for task_id in item.blocked_by)
                line = f"{line} blocked by {blocked}"
            lines.append(line)

        hidden_count = snapshot.total_count - len(visible_items)
        if hidden_count > 0:
            lines.append(f"+{hidden_count} more")

    return "\n".join(lines) if lines else base_text


# ---------------------------------------------------------------------------
# Status I/O — send / edit / clear
# ---------------------------------------------------------------------------


async def send_status_text(
    bot: Bot,
    user_id: int,
    thread_id_or_0: int,
    window_id: str,
    text: str,
) -> None:
    """Send a new status message with action buttons and track it.

    If a status message already exists for this (user, thread), edit it
    in-place instead of sending a new one.
    """
    skey = (user_id, thread_id_or_0)
    thread_id: int | None = thread_id_or_0 if thread_id_or_0 != 0 else None
    chat_id = thread_router.resolve_chat_id(user_id, thread_id)

    history = _get_idle_history(user_id, thread_id_or_0, text)
    keyboard = build_status_keyboard(
        window_id,
        history=history,
        rc_active=_rc_active_fn(window_id),
    )

    existing = _status_msg_info.get(skey)
    if existing:
        msg_id, stored_wid, last_text, stored_chat_id = existing
        if stored_wid == window_id and text == last_text:
            return
        if stored_wid == window_id:
            success = await edit_with_fallback(
                bot, stored_chat_id, msg_id, text, reply_markup=keyboard
            )
            if success:
                _status_msg_info[skey] = (msg_id, window_id, text, stored_chat_id)
                return
            _status_msg_info.pop(skey, None)
        else:
            await clear_status_message(bot, user_id, thread_id_or_0)

    sent = await rate_limit_send_message(
        bot, chat_id, text, reply_markup=keyboard, **send_kwargs(thread_id)
    )
    if sent:
        _status_msg_info[skey] = (sent.message_id, window_id, text, chat_id)


async def clear_status_message(
    bot: Bot,
    user_id: int,
    thread_id_or_0: int = 0,
) -> None:
    """Delete the status message for a user."""
    skey = (user_id, thread_id_or_0)
    info = _status_msg_info.pop(skey, None)
    if info:
        msg_id, _, _, chat_id = info
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramError as e:
            logger.debug("Failed to delete status message %s: %s", msg_id, e)


async def convert_status_to_content(
    bot: Bot,
    user_id: int,
    thread_id_or_0: int,
    window_id: str,
    content_text: str,
) -> int | None:
    """Convert status message to content message by editing it.

    Returns the message_id if converted successfully, None otherwise.
    """
    skey = (user_id, thread_id_or_0)
    info = _status_msg_info.pop(skey, None)
    if not info:
        return None

    msg_id, stored_wid, _, chat_id = info
    if stored_wid != window_id:
        with contextlib.suppress(TelegramError):
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        return None

    success = await edit_with_fallback(
        bot,
        chat_id,
        msg_id,
        content_text,
        reply_markup=None,
    )
    if success:
        return msg_id
    return None


# ---------------------------------------------------------------------------
# Status task processors (called by message_queue worker)
# ---------------------------------------------------------------------------


async def process_status_update(
    bot: Bot,
    user_id: int,
    task: StatusUpdateTask,
) -> None:
    """Update the status bubble in place."""
    tkey = thread_key(task.thread_id)
    status_text = format_claude_task_status(task.window_id, task.text)

    if not status_text:
        await clear_status_message(bot, user_id, tkey)
        return

    await send_status_text(bot, user_id, tkey, task.window_id, status_text)


async def process_status_clear(
    bot: Bot,
    user_id: int,
    task: StatusClearTask,
) -> None:
    """Clear the status bubble — re-render with task list or delete."""
    window_id = task.window_id or ""
    tkey = thread_key(task.thread_id)
    status_text = format_claude_task_status(window_id, None)
    if status_text and window_id:
        await send_status_text(bot, user_id, tkey, window_id, status_text)
        return
    await clear_status_message(bot, user_id, tkey)


# ---------------------------------------------------------------------------
# Cleanup (non-registry — see docstring)
# ---------------------------------------------------------------------------


def clear_status_msg_info(user_id: int, thread_id: int | None = None) -> None:
    """Clear status message tracking for a user (and optionally a specific thread).

    NOT registered with TopicStateRegistry — must only be called explicitly
    from cleanup.py in the ``bot is None`` path.  When a bot is available,
    ``clear_status_message`` (via the queued ``status_clear`` task) pops
    the entry *and* deletes the Telegram message.  Registering this function
    with the registry would pop the entry before the worker runs, preventing
    the actual Telegram delete.
    """
    skey = (user_id, thread_key(thread_id))
    _status_msg_info.pop(skey, None)
