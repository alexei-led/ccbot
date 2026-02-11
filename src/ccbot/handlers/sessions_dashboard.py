"""Sessions dashboard — /sessions command showing all bound sessions.

Displays a summary of all thread-bound sessions for the current user
with alive/dead status indicators and refresh/new-session actions.

Key functions: sessions_command(), handle_sessions_refresh().
"""

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..config import config
from ..session import session_manager
from ..tmux_manager import tmux_manager
from .callback_data import CB_SESSIONS_NEW, CB_SESSIONS_REFRESH
from .message_sender import safe_edit, safe_reply

_REFRESH_BTN = InlineKeyboardButton("🔄 Refresh", callback_data=CB_SESSIONS_REFRESH)
_NEW_BTN = InlineKeyboardButton("➕ New Session", callback_data=CB_SESSIONS_NEW)
_KEYBOARD = InlineKeyboardMarkup([[_REFRESH_BTN, _NEW_BTN]])


async def _build_dashboard(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build dashboard text and keyboard for a user's sessions."""
    bindings = session_manager.get_all_thread_windows(user_id)

    if not bindings:
        return (
            "No active sessions.\n\nCreate a new topic to start a session.",
            _KEYBOARD,
        )

    all_windows = await tmux_manager.list_windows()
    live_ids = {w.window_id for w in all_windows}

    lines: list[str] = []
    for _thread_id, window_id in sorted(bindings.items()):
        display_name = session_manager.get_display_name(window_id)
        status = "🟢" if window_id in live_ids else "⚫"
        lines.append(f"{status} {display_name}")

    text = "Sessions\n\n" + "\n".join(lines)
    return text, _KEYBOARD


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sessions — show dashboard of all bound sessions."""
    user = update.effective_user
    if not user or not update.message:
        return

    if not config.is_user_allowed(user.id):
        await safe_reply(update.message, "You are not authorized to use this bot.")
        return

    text, keyboard = await _build_dashboard(user.id)
    await safe_reply(update.message, text, reply_markup=keyboard)


async def handle_sessions_refresh(query: CallbackQuery, user_id: int) -> None:
    """Handle refresh button — re-render the dashboard in-place."""
    text, keyboard = await _build_dashboard(user_id)
    await safe_edit(query, text, reply_markup=keyboard)
