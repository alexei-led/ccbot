"""Per-user per-topic command history for recall buttons.

Stores recently sent commands in memory (no disk persistence).
History resets on bot restart.

Functions:
  - record_command: Store a command in history
  - get_history: Retrieve recent commands (newest-first)
  - clear_history: Remove history for a topic (cleanup)
  - truncate_for_display: Truncate text for button labels
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from ..topic_state_registry import topic_state

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

HISTORY_MAX = 20

# Telegram switch_inline_query_current_chat limit (256 UTF-8 chars)
INLINE_QUERY_MAX = 256

# (user_id, thread_id) -> deque of commands (oldest-first in deque)
_history: dict[tuple[int, int], deque[str]] = {}


def record_command(user_id: int, thread_id: int, text: str) -> None:
    """Append a command to the user's topic history.

    Deduplicates consecutive identical commands. Caps at HISTORY_MAX.
    """
    key = (user_id, thread_id)
    dq = _history.get(key)
    if dq is None:
        dq = deque(maxlen=HISTORY_MAX)
        _history[key] = dq

    # Deduplicate consecutive identical
    if dq and dq[-1] == text:
        return

    dq.append(text)


def get_history(user_id: int, thread_id: int, *, limit: int = 20) -> list[str]:
    """Return recent commands, newest-first."""
    key = (user_id, thread_id)
    dq = _history.get(key)
    if not dq:
        return []
    # Reverse to get newest-first, then slice
    return list(reversed(dq))[:limit]


@topic_state.register("topic")
def clear_history(user_id: int, thread_id: int) -> None:
    """Remove history entry for a topic."""
    _history.pop((user_id, thread_id), None)


def truncate_for_display(text: str, max_len: int) -> str:
    """Truncate text for button labels, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


_RECALL_LABEL_MAX = 40


async def recall_command(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show recent command history for the current topic."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from ..config import config
    from ..utils import handle_general_topic_message, is_general_topic
    from .callback_helpers import get_thread_id
    from .message_sender import safe_reply

    user = update.effective_user
    if not user or not config.is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        if (
            update.message
            and update.effective_chat
            and is_general_topic(update.message)
        ):
            await handle_general_topic_message(
                update.get_bot(), update.message, update.effective_chat.id
            )
        else:
            await safe_reply(update.message, "\u274c Use this command inside a topic.")
        return

    history = get_history(user.id, thread_id, limit=10)
    if not history:
        await safe_reply(update.message, "\U0001f4cb No command history yet.")
        return

    rows = []
    for cmd in history:
        label = truncate_for_display(cmd, _RECALL_LABEL_MAX)
        query = cmd[:INLINE_QUERY_MAX]
        rows.append(
            [InlineKeyboardButton(label, switch_inline_query_current_chat=query)]
        )
    keyboard = InlineKeyboardMarkup(rows)
    await safe_reply(
        update.message, "\U0001f4cb Recent commands:", reply_markup=keyboard
    )
