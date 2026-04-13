"""Status-bubble keyboard rendering for per-window status messages.

The status bubble is a pinned Telegram message per topic that displays the
current agent state (running / idle / interactive) along with a control
keyboard. This module owns the keyboard layout. The send/edit logic and
queue plumbing live in ``message_queue``.

Extracted from ``message_queue`` to break the circular dependency between
status rendering and queue primitives, and to give the keyboard a single
home consumed by polling, hook events, and screenshot handlers alike.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..session import session_manager
from .callback_data import (
    CB_STATUS_ESC,
    CB_STATUS_NOTIFY,
    CB_STATUS_RECALL,
    CB_STATUS_REMOTE,
    CB_STATUS_SCREENSHOT,
    NOTIFY_MODE_ICONS,
)


def build_status_keyboard(
    window_id: str, history: list[str] | None = None
) -> InlineKeyboardMarkup:
    """Build inline keyboard for status messages.

    Layout:
      Row 1 (optional): up to 2 history-recall buttons
      Row 2: [Esc] [Screenshot] [Bell] [RC]
    """
    # Lazy imports avoid circular dependencies between status_bubble and
    # the modules that own command history / polling state.
    from .command_history import truncate_for_display
    from .polling_strategies import is_rc_active

    rows: list[list[InlineKeyboardButton]] = []

    # History recall row (up to 2 buttons)
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

    # Control row
    mode = session_manager.get_notification_mode(window_id)
    bell = NOTIFY_MODE_ICONS.get(mode, "\U0001f514")
    rc_label = "\U0001f4e1\u2713" if is_rc_active(window_id) else "\U0001f4e1"
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
