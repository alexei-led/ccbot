"""Toolbar callback handlers — TOML-configurable inline action buttons.

Handles all clicks on the ``/toolbar`` inline keyboard. The keyboard layout
and the action pool are loaded from ``toolbar_config`` (TOML file or
built-in defaults) — this module is the PTB-aware glue that translates a
button click into the right side effect.

Callback data scheme: ``tb:<window_id>:<action_name>``. The action_name is
looked up in the loaded ``ToolbarConfig.actions`` and dispatched by
``action_type``:

  - ``key``    → ``tmux_manager.send_keys(payload, enter=False, literal=...)``
  - ``text``   → ``tmux_manager.send_keys(payload, enter=True, literal=True)``
  - ``builtin`` → dispatched via ``_BUILTIN_DISPATCH`` to a specialized handler

Toggle actions with ``read_state=True`` (Mode/Think/YOLO) capture the pane
~250ms after sending the key, scrape the most recent mode-line, and surface
it in the ``query.answer`` toast. Falls back to the action's static toast
text when no mode-line is found or the capture fails.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path
from typing import Awaitable, Callable

import structlog
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import config
from ..session import session_manager
from ..thread_router import thread_router
from ..tmux_manager import tmux_manager
from ..toolbar_config import (
    ToolbarAction,
    ToolbarConfig,
    load_toolbar_config,
)
from .callback_data import CB_TOOLBAR
from .callback_helpers import get_thread_id, user_owns_window
from .callback_registry import register

logger = structlog.get_logger()


# ──────────────────────────────────────────────────────────────────────
# Loaded config (lazy singleton)
# ──────────────────────────────────────────────────────────────────────

_toolbar_cfg: ToolbarConfig | None = None


def _get_toolbar_config() -> ToolbarConfig:
    """Return the loaded ToolbarConfig, lazy-loading on first access."""
    global _toolbar_cfg  # noqa: PLW0603
    if _toolbar_cfg is None:
        _toolbar_cfg = load_toolbar_config(config.toolbar_config_path)
    return _toolbar_cfg


def reload_toolbar_config() -> None:
    """Force-reload of the toolbar config. Used by tests and future /reload."""
    global _toolbar_cfg  # noqa: PLW0603
    _toolbar_cfg = None


# ──────────────────────────────────────────────────────────────────────
# Keyboard builder
# ──────────────────────────────────────────────────────────────────────


def _make_button(
    action: ToolbarAction, window_id: str, style: str
) -> InlineKeyboardButton:
    """Render one ToolbarAction as a Telegram inline button."""
    label = action.render(style)  # type: ignore[arg-type]
    cb = f"{CB_TOOLBAR}{window_id}:{action.name}"[:64]
    return InlineKeyboardButton(label, callback_data=cb)


def build_toolbar_keyboard(
    window_id: str, provider_name: str = "claude"
) -> InlineKeyboardMarkup:
    """Build the inline keyboard for ``/toolbar`` from per-provider config.

    The grid shape, button identities, and rendering style all come from
    ``toolbar_config.load_toolbar_config`` (TOML file or built-in defaults).
    Unknown providers fall back to the ``claude`` layout.
    """
    cfg = _get_toolbar_config()
    layout = cfg.for_provider(provider_name)
    rows: list[list[InlineKeyboardButton]] = []
    for row_names in layout.buttons:
        cells: list[InlineKeyboardButton] = []
        for name in row_names:
            action = cfg.actions.get(name)
            if action is not None:
                cells.append(_make_button(action, window_id, layout.style))
        if cells:
            rows.append(cells)
    return InlineKeyboardMarkup(rows)


# ──────────────────────────────────────────────────────────────────────
# Mode/Think/YOLO state-readback
# ──────────────────────────────────────────────────────────────────────

# Strip ANSI escapes for plain-text mode-line scraping.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

# Heuristic patterns that match a mode-line in pane output.
_MODE_LINE_HINTS: tuple[str, ...] = (
    "auto-accept",
    "accept edits",
    "plan mode",
    "default mode",
    "extended thinking",
    "thinking on",
    "thinking off",
    "yolo",
    "auto-approve",
)

_READ_STATE_DELAY_S = 0.25
_READ_STATE_LINE_LIMIT = 80


async def _scrape_mode_toast(window_id: str, fallback: str) -> str:
    """Capture the pane after a toggle key and return the mode-line.

    Falls back to ``fallback`` if the pane capture fails or no recognized
    mode-line is found in the last ~20 lines.
    """
    await asyncio.sleep(_READ_STATE_DELAY_S)
    try:
        capture = await tmux_manager.capture_pane(window_id)
    except OSError, TelegramError:
        return fallback
    if not capture:
        return fallback
    cleaned = _ANSI_RE.sub("", capture)
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    for line in reversed(lines[-20:]):
        lower = line.lower()
        if any(hint in lower for hint in _MODE_LINE_HINTS):
            return line[:_READ_STATE_LINE_LIMIT]
    return fallback


# ──────────────────────────────────────────────────────────────────────
# Per-type dispatch
# ──────────────────────────────────────────────────────────────────────


async def _dispatch_key(
    action: ToolbarAction, query: CallbackQuery, window_id: str
) -> None:
    """Send a tmux key for a ``key`` action."""
    w = await tmux_manager.find_window_by_id(window_id)
    if w is None:
        await query.answer("Window not found", show_alert=True)
        return
    await tmux_manager.send_keys(
        w.window_id, action.payload, enter=False, literal=action.literal
    )
    fallback = f"{action.emoji} {action.text}"
    if action.read_state:
        toast = await _scrape_mode_toast(window_id, fallback)
    else:
        toast = fallback
    await query.answer(toast)


async def _dispatch_text(
    action: ToolbarAction, query: CallbackQuery, window_id: str
) -> None:
    """Send literal text + Enter for a ``text`` action."""
    w = await tmux_manager.find_window_by_id(window_id)
    if w is None:
        await query.answer("Window not found", show_alert=True)
        return
    await tmux_manager.send_keys(w.window_id, action.payload, enter=True, literal=True)
    fallback = f"{action.emoji} {action.text}"
    if action.read_state:
        toast = await _scrape_mode_toast(window_id, fallback)
    else:
        toast = fallback
    await query.answer(toast)


# ──────────────────────────────────────────────────────────────────────
# Built-in handlers
# ──────────────────────────────────────────────────────────────────────


async def _builtin_screenshot(
    _action: ToolbarAction,
    query: CallbackQuery,
    window_id: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Builtin: trigger the screenshot handler."""
    from .callback_data import CB_STATUS_SCREENSHOT
    from .screenshot_callbacks import handle_screenshot_callback

    user = update.effective_user
    if user is None:
        await query.answer("No user context", show_alert=True)
        return
    fake_data = f"{CB_STATUS_SCREENSHOT}{window_id}"
    await handle_screenshot_callback(query, user.id, fake_data, update, context)


async def _builtin_ctrlc(
    _action: ToolbarAction,
    query: CallbackQuery,
    window_id: str,
    _update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Builtin: send Ctrl-C."""
    w = await tmux_manager.find_window_by_id(window_id)
    if w is None:
        await query.answer("Window not found", show_alert=True)
        return
    await tmux_manager.send_keys(w.window_id, "C-c", enter=False, literal=False)
    await query.answer("\u23f9 Ctrl-C sent")


async def _builtin_live(
    _action: ToolbarAction,
    query: CallbackQuery,
    window_id: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Builtin: start the live view via the existing screenshot dispatcher."""
    from .callback_data import CB_LIVE_START
    from .screenshot_callbacks import handle_screenshot_callback

    user = update.effective_user
    if user is None:
        await query.answer("No user context", show_alert=True)
        return
    fake_data = f"{CB_LIVE_START}{window_id}"
    await handle_screenshot_callback(query, user.id, fake_data, update, context)


async def _builtin_send(
    _action: ToolbarAction,
    query: CallbackQuery,
    window_id: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Builtin: open the /send file browser."""
    user = update.effective_user
    if user is None:
        await query.answer("No user context", show_alert=True)
        return
    user_id = user.id
    view = session_manager.view_window(window_id)
    cwd = Path(view.cwd) if view and view.cwd else None
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


async def _builtin_dismiss(
    _action: ToolbarAction,
    query: CallbackQuery,
    _window_id: str,
    _update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Builtin: delete the toolbar message."""
    with contextlib.suppress(TelegramError):
        await query.delete_message()
    await query.answer()


_BuiltinHandler = Callable[
    [ToolbarAction, CallbackQuery, str, Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[None],
]

_BUILTIN_DISPATCH: dict[str, _BuiltinHandler] = {
    "screenshot": _builtin_screenshot,
    "ctrlc": _builtin_ctrlc,
    "live": _builtin_live,
    "send": _builtin_send,
    "dismiss": _builtin_dismiss,
}


# ──────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ──────────────────────────────────────────────────────────────────────


def _parse_callback_data(data: str) -> tuple[str, str] | None:
    """Parse ``tb:<window_id>:<action_name>`` into ``(window_id, name)``.

    Returns None if the format is invalid. Window IDs may themselves
    contain a colon (foreign emdash IDs like ``emdash-claude-main-x:@0``),
    so the action_name is the substring after the LAST colon.
    """
    if not data.startswith(CB_TOOLBAR):
        return None
    suffix = data[len(CB_TOOLBAR) :]
    sep = suffix.rfind(":")
    if sep <= 0:
        return None
    return suffix[:sep], suffix[sep + 1 :]


async def handle_toolbar_callback(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Single entry point for all toolbar button clicks."""
    parsed = _parse_callback_data(data)
    if parsed is None:
        await query.answer("Bad toolbar callback", show_alert=True)
        return
    window_id, action_name = parsed
    if not user_owns_window(user_id, window_id):
        await query.answer("Not your session", show_alert=True)
        return
    cfg = _get_toolbar_config()
    action = cfg.actions.get(action_name)
    if action is None:
        await query.answer(f"Unknown action: {action_name}", show_alert=True)
        return
    if action.action_type == "key":
        await _dispatch_key(action, query, window_id)
    elif action.action_type == "text":
        await _dispatch_text(action, query, window_id)
    elif action.action_type == "builtin":
        handler = _BUILTIN_DISPATCH.get(action.payload)
        if handler is None:
            await query.answer(f"Unknown builtin: {action.payload}", show_alert=True)
            return
        await handler(action, query, window_id, update, context)
    else:
        await query.answer("Unsupported action type", show_alert=True)


@register(CB_TOOLBAR)
async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single registered handler for all CB_TOOLBAR clicks."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    user = update.effective_user
    if user is None:
        return
    await handle_toolbar_callback(query, user.id, query.data, update, context)
