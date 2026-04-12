"""Toolbar callback handlers — provider-specific inline action buttons.

Handles all CB_TOOLBAR_* callbacks dispatched from the /toolbar command keyboard:
  - CB_TOOLBAR_CTRLC: Send Ctrl-C
  - CB_TOOLBAR_DISMISS: Delete toolbar message
  - CB_TOOLBAR_SEND: Open /send file browser
  - CB_TOOLBAR_MODE: Send Shift+Tab (mode cycle)
  - CB_TOOLBAR_THINK: Send Tab (think toggle)
  - CB_TOOLBAR_YOLO: Send Ctrl+Y (YOLO toggle)
  - CB_TOOLBAR_EOF: Send Ctrl+D (EOF)
  - CB_TOOLBAR_SUSPEND: Send Ctrl+Z (suspend)
  - CB_TOOLBAR_ESC: Send Escape
  - CB_TOOLBAR_ENTER: Send Enter
  - CB_TOOLBAR_TAB: Send Tab
"""

import contextlib
from pathlib import Path

import structlog
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..session import session_manager
from ..thread_router import thread_router
from ..tmux_manager import tmux_manager
from .callback_data import (
    CB_LIVE_START,
    CB_STATUS_SCREENSHOT,
    CB_TOOLBAR_CTRLC,
    CB_TOOLBAR_DISMISS,
    CB_TOOLBAR_ENTER,
    CB_TOOLBAR_EOF,
    CB_TOOLBAR_ESC,
    CB_TOOLBAR_MODE,
    CB_TOOLBAR_SEND,
    CB_TOOLBAR_SUSPEND,
    CB_TOOLBAR_TAB,
    CB_TOOLBAR_THINK,
    CB_TOOLBAR_YOLO,
)
from .callback_helpers import get_thread_id, user_owns_window
from .callback_registry import register

logger = structlog.get_logger()

# Map toolbar key prefixes to (tmux_key, toast_text, literal)
_TOOLBAR_KEY_MAP: dict[str, tuple[str, str, bool]] = {
    CB_TOOLBAR_MODE: ("\x1b[Z", "\U0001f500 Mode cycled", True),
    CB_TOOLBAR_THINK: (
        "Tab",
        "\U0001f4ad Think toggled",
        False,
    ),  # Tab = toggle extended thinking (Claude)
    CB_TOOLBAR_YOLO: ("C-y", "\U0001f1fe YOLO toggled", False),
    CB_TOOLBAR_EOF: ("C-d", "^D Sent", False),
    CB_TOOLBAR_SUSPEND: ("C-z", "^Z Sent", False),
    CB_TOOLBAR_ESC: ("Escape", "\u238b Esc", False),
    CB_TOOLBAR_ENTER: ("Enter", "\u23ce Enter", False),
    CB_TOOLBAR_TAB: ("Tab", "\u21e5 Tab", False),  # Tab = literal Tab key (Codex row2)
}

# Provider-specific row-2 button definitions: (label, CB prefix or None=dismiss)
_PROVIDER_ROW2: dict[str, list[tuple[str, str | None]]] = {
    "claude": [
        ("\U0001f500 Mode", CB_TOOLBAR_MODE),
        ("\U0001f4ad Think", CB_TOOLBAR_THINK),
        ("\u238b Esc", CB_TOOLBAR_ESC),
        ("\u2716 Close", None),
    ],
    "codex": [
        ("\u238b Esc", CB_TOOLBAR_ESC),
        ("\u23ce Enter", CB_TOOLBAR_ENTER),
        ("\u21e5 Tab", CB_TOOLBAR_TAB),
        ("\u2716 Close", None),
    ],
    "gemini": [
        ("\U0001f500 Mode", CB_TOOLBAR_MODE),
        ("\U0001f1fe YOLO", CB_TOOLBAR_YOLO),
        ("\u238b Esc", CB_TOOLBAR_ESC),
        ("\u2716 Close", None),
    ],
    "shell": [
        ("\u23ce Enter", CB_TOOLBAR_ENTER),
        ("^D EOF", CB_TOOLBAR_EOF),
        ("^Z Susp", CB_TOOLBAR_SUSPEND),
        ("\u2716 Close", None),
    ],
}


def build_toolbar_keyboard(
    window_id: str, provider_name: str = "claude"
) -> InlineKeyboardMarkup:
    """Build inline keyboard for /toolbar command.

    Row 1 is universal across all providers: Screenshot, Ctrl-C, Live, Send.
    Row 2 is provider-specific: mode/think/esc/close for Claude, etc.
    """
    row1 = [
        InlineKeyboardButton(
            "\U0001f4f7 Screenshot",
            callback_data=f"{CB_STATUS_SCREENSHOT}{window_id}"[:64],
        ),
        InlineKeyboardButton(
            "\u23f9 Ctrl-C",
            callback_data=f"{CB_TOOLBAR_CTRLC}{window_id}"[:64],
        ),
        InlineKeyboardButton(
            "\U0001f4fa Live",
            callback_data=f"{CB_LIVE_START}{window_id}"[:64],
        ),
        InlineKeyboardButton(
            "\U0001f4e4 Send",
            callback_data=f"{CB_TOOLBAR_SEND}{window_id}"[:64],
        ),
    ]

    row2_spec = _PROVIDER_ROW2.get(provider_name, _PROVIDER_ROW2["claude"])
    row2 = []
    for label, prefix in row2_spec:
        if prefix is None:
            row2.append(InlineKeyboardButton(label, callback_data=CB_TOOLBAR_DISMISS))
        else:
            row2.append(
                InlineKeyboardButton(label, callback_data=f"{prefix}{window_id}"[:64])
            )

    return InlineKeyboardMarkup([row1, row2])


# ------------------------------------------------------------------
# Individual toolbar handlers
# ------------------------------------------------------------------


async def _handle_toolbar_ctrlc(query: CallbackQuery, user_id: int, data: str) -> None:
    """Handle CB_TOOLBAR_CTRLC: send Ctrl-C to window."""
    window_id = data[len(CB_TOOLBAR_CTRLC) :]
    if not user_owns_window(user_id, window_id):
        await query.answer("Not your session", show_alert=True)
        return
    w = await tmux_manager.find_window_by_id(window_id)
    if w:
        await tmux_manager.send_keys(w.window_id, "C-c", enter=False, literal=False)
        await query.answer("^C Sent")
    else:
        await query.answer("Window not found", show_alert=True)


async def _handle_toolbar_dismiss(query: CallbackQuery) -> None:
    """Handle CB_TOOLBAR_DISMISS: delete the toolbar message."""
    with contextlib.suppress(TelegramError):
        await query.delete_message()
    await query.answer()


async def _handle_toolbar_send(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_TOOLBAR_SEND: open file browser for the window's CWD."""
    window_id = data[len(CB_TOOLBAR_SEND) :]
    if not user_owns_window(user_id, window_id):
        await query.answer("Not your session", show_alert=True)
        return
    ws = session_manager.get_window_state(window_id)
    cwd = Path(ws.cwd) if ws and ws.cwd else None
    if not cwd or not cwd.is_dir():
        await query.answer("Working directory not available", show_alert=True)
        return
    if context.user_data is None:
        await query.answer("State error", show_alert=True)
        return
    thread_id = get_thread_id(update)
    chat_id = thread_router.resolve_chat_id(user_id, thread_id) if thread_id else None
    if chat_id is None:
        await query.answer("Use in a topic", show_alert=True)
        return
    from .send_command import open_file_browser

    await open_file_browser(
        query.get_bot(), chat_id, thread_id, context.user_data, window_id, cwd
    )
    await query.answer()


async def _send_toolbar_key(
    query: CallbackQuery,
    user_id: int,
    data: str,
    prefix: str,
    tmux_key: str,
    toast: str,
    *,
    literal: bool = False,
) -> None:
    """Generic handler for toolbar buttons that send a tmux key."""
    window_id = data[len(prefix) :]
    if not user_owns_window(user_id, window_id):
        await query.answer("Not your session", show_alert=True)
        return
    w = await tmux_manager.find_window_by_id(window_id)
    if w:
        await tmux_manager.send_keys(
            w.window_id, tmux_key, enter=False, literal=literal
        )
        await query.answer(toast)
    else:
        await query.answer("Window not found", show_alert=True)


# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------


async def handle_toolbar_callback(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle all toolbar callback queries."""
    if data.startswith(CB_TOOLBAR_SEND):
        await _handle_toolbar_send(query, user_id, data, update, context)
        return

    if data.startswith(CB_TOOLBAR_CTRLC):
        await _handle_toolbar_ctrlc(query, user_id, data)
        return

    for prefix, (tmux_key, toast, literal) in _TOOLBAR_KEY_MAP.items():
        if data.startswith(prefix):
            await _send_toolbar_key(
                query, user_id, data, prefix, tmux_key, toast, literal=literal
            )
            return

    if data == CB_TOOLBAR_DISMISS:
        await _handle_toolbar_dismiss(query)


@register(
    CB_TOOLBAR_CTRLC,
    CB_TOOLBAR_DISMISS,
    CB_TOOLBAR_SEND,
    CB_TOOLBAR_MODE,
    CB_TOOLBAR_THINK,
    CB_TOOLBAR_YOLO,
    CB_TOOLBAR_EOF,
    CB_TOOLBAR_SUSPEND,
    CB_TOOLBAR_ESC,
    CB_TOOLBAR_ENTER,
    CB_TOOLBAR_TAB,
)
async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    assert query is not None and query.data is not None and user is not None
    await handle_toolbar_callback(query, user.id, query.data, update, context)
