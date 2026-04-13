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
from ..topic_state_registry import topic_state
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


# Per-window per-action label overrides populated by state readback.
# Example: {"@5": {"mode": "Edit"}} — when the toolbar is (re)built for
# window @5, the "mode" action's label is replaced with "Edit" instead
# of the default "Mode". This lets the button itself show the current
# state — no popups, no ephemeral toasts.
_window_action_labels: dict[str, dict[str, str]] = {}


def _set_action_label(window_id: str, action_name: str, label: str) -> None:
    _window_action_labels.setdefault(window_id, {})[action_name] = label


def _get_action_label(window_id: str, action_name: str) -> str | None:
    return _window_action_labels.get(window_id, {}).get(action_name)


def _clear_window_labels(window_id: str) -> None:
    """Drop all label overrides for a window (on teardown)."""
    _window_action_labels.pop(window_id, None)


# Register with the topic_state registry so window teardown clears the
# label cache automatically (same pattern as other per-window state).


@topic_state.register("window")
def _clear_toolbar_labels(window_id: str) -> None:
    _clear_window_labels(window_id)


# ──────────────────────────────────────────────────────────────────────
# Keyboard builder
# ──────────────────────────────────────────────────────────────────────


def _make_button(
    action: ToolbarAction, window_id: str, style: str
) -> InlineKeyboardButton:
    """Render one ToolbarAction as a Telegram inline button.

    If there is a label override stored for (window, action), use it —
    this is how toggle buttons display their current state (e.g. Mode
    shows "Edit" / "Plan" / "Auto" instead of the static "Mode").
    """
    override = _get_action_label(window_id, action.name)
    if override is not None:
        # Preserve emoji for emoji_text style; bare label for text/emoji.
        label = f"{action.emoji} {override}" if style == "emoji_text" else override
    else:
        label = action.render(style)  # type: ignore[arg-type]
    cb = f"{CB_TOOLBAR}{window_id}:{action.name}"[:64]
    return InlineKeyboardButton(label, callback_data=cb)


def build_toolbar_keyboard(
    window_id: str, provider_name: str = "claude"
) -> InlineKeyboardMarkup:
    """Build the inline keyboard for ``/toolbar`` from per-provider config.

    The grid shape, button identities, and rendering style all come from
    ``toolbar_config.load_toolbar_config`` (TOML file or built-in defaults).
    Per-window label overrides (populated by state readback) are honored
    so toggle buttons show their current state. Unknown providers fall
    back to the ``claude`` layout.
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

# Claude Code's mode indicator appears in the bottom chrome with one of
# two marker glyphs depending on the mode:
#   ⏵⏵ auto mode on            (U+23F5 ⏵ — play)
#   ⏵⏵ accept edits on
#   ⏵⏵ bypass permissions…
#   ⏸  plan mode on            (U+23F8 ⏸ — pause)
# Default mode has no indicator line at all.
_CLAUDE_MODE_MARKERS: tuple[str, ...] = ("\u23f5\u23f5", "\u23f8")

# Fallback substring hints for other providers (Gemini YOLO, etc.) when
# Claude renders a mode-line without the marker glyphs.
_MODE_LINE_HINTS: tuple[str, ...] = (
    "auto mode",
    "auto-accept",
    "accept edits",
    "plan mode",
    "bypass permissions",
    "yolo",
    "auto-approve",
)

# Compact labels for button text. The button label IS the state indicator —
# no popups, no toast. User clicks Mode and the button text cycles through
# Def → Edit → Plan → Auto → YOLO. Fits the mobile keyboard budget.
#
# Per anthropic.com/blog/auto-mode, Claude Code has FIVE distinct modes:
#   default                 — asks for each tool call             → "Def"
#   accept edits            — auto-accepts file writes only       → "Edit"
#   plan mode               — read-only, no tool execution        → "Plan"
#   auto mode               — classifier-guarded auto-approve     → "Auto"
#   bypass permissions      — skips ALL checks (YOLO)             → "YOLO"
#
# Auto ≠ YOLO: Auto uses a safety classifier; YOLO skips everything.
# Gemini CLI's own "YOLO mode" and "auto-approve" both map to YOLO here.
_MODE_SHORT_LABELS: tuple[tuple[str, str], ...] = (
    ("accept edits", "Edit"),
    ("auto-accept", "Edit"),
    ("plan", "Plan"),
    ("auto mode", "Auto"),
    ("bypass", "YOLO"),
    ("yolo", "YOLO"),
    ("auto-approve", "YOLO"),
)

# Default fallback label used when no recognized mode-line is found —
# Claude's default mode has no indicator, so "no line" means "default".
_DEFAULT_MODE_LABEL = "Def"

_READ_STATE_DELAY_S = 0.35  # long enough for Claude to re-render its chrome
_READ_STATE_LINE_LIMIT = 80


def _mode_short_label(mode_line: str | None, default: str) -> str:
    """Map a scraped mode line to a compact button label.

    Returns ``default`` (e.g. the action's static text) when no known
    mode can be matched — that covers default mode (no indicator),
    scrape failures, and unknown formats.
    """
    if not mode_line:
        return default
    lower = mode_line.lower()
    for pattern, label in _MODE_SHORT_LABELS:
        if pattern in lower:
            return label
    return default


def _find_mode_line(capture: str) -> str | None:
    """Find the mode-indicator line in a pane capture.

    Uses ``find_chrome_boundary`` to locate Claude Code's bottom chrome
    block, then scans it for the ⏵⏵ / ⏸ markers. Falls back to substring
    hints for providers without the marker.
    """
    from ..terminal_parser import find_chrome_boundary

    cleaned = _ANSI_RE.sub("", capture)
    lines = cleaned.splitlines()

    # Chrome block first — always where Claude renders the mode indicator.
    boundary = find_chrome_boundary(lines)
    chrome_lines = lines[boundary + 1 :] if boundary is not None else lines[-20:]
    for line in reversed(chrome_lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(marker in stripped for marker in _CLAUDE_MODE_MARKERS):
            return stripped[:_READ_STATE_LINE_LIMIT]

    # Fallback: scan the bottom 25 lines for any provider's mode hint.
    for line in reversed(lines[-25:]):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(hint in lower for hint in _MODE_LINE_HINTS):
            return stripped[:_READ_STATE_LINE_LIMIT]
    return None


# ──────────────────────────────────────────────────────────────────────
# Per-type dispatch
# ──────────────────────────────────────────────────────────────────────


async def _scrape_current_mode(window_id: str) -> str:
    """Capture the pane and return the current mode as a short label.

    Returns ``_DEFAULT_MODE_LABEL`` ("Def") when:
      - pane capture fails
      - pane is empty
      - no recognized mode-indicator line is found (default mode)
    """
    try:
        capture = await tmux_manager.capture_pane(window_id)
    except (OSError, TelegramError) as exc:
        logger.warning("Mode scrape: capture_pane failed %s (%s)", window_id, exc)
        return _DEFAULT_MODE_LABEL
    if not capture:
        return _DEFAULT_MODE_LABEL
    mode_line = _find_mode_line(capture)
    return _mode_short_label(mode_line, _DEFAULT_MODE_LABEL)


async def seed_button_states(window_id: str) -> None:
    """Populate toggle-button label overrides with the actual current state.

    Called from ``/toolbar`` handler BEFORE rendering the keyboard, so the
    initial button text reflects the real mode (Edit/Plan/Full/Def) rather
    than the static "Mode" placeholder. Best-effort — failures are silent.
    """
    cfg = _get_toolbar_config()
    # Only seed the "mode" action — it's the single toggle whose readable
    # state matches _scrape_current_mode's Claude-style mode-line output.
    # YOLO/Think (or user-defined toggles) need their own readback logic
    # and are left with their static default label until first click.
    mode_action = cfg.actions.get("mode")
    if mode_action is None or not mode_action.read_state:
        return
    label = await _scrape_current_mode(window_id)
    _set_action_label(window_id, "mode", label)


async def _refresh_button_label(
    action: ToolbarAction, query: CallbackQuery, window_id: str
) -> str:
    """Scrape the pane, update the button label, rebuild the keyboard.

    This is how toggle actions (Mode) show their current state: the button
    text itself becomes the indicator. No popups, no ephemeral toasts.
    Returns the short label used so the caller can echo it in the toast.
    """
    await asyncio.sleep(_READ_STATE_DELAY_S)
    short_label = await _scrape_current_mode(window_id)
    _set_action_label(window_id, action.name, short_label)

    # Rebuild the keyboard for the same provider and edit the message.
    view = session_manager.view_window(window_id)
    provider_name = view.provider_name if view else "claude"
    new_kb = build_toolbar_keyboard(window_id, provider_name)
    try:
        await query.edit_message_reply_markup(reply_markup=new_kb)
    except TelegramError as exc:
        logger.debug("Toolbar reply_markup edit failed: %s", exc)
    return short_label


async def _dispatch_key(
    action: ToolbarAction, query: CallbackQuery, window_id: str
) -> None:
    """Send a tmux key for a ``key`` action.

    Toggle actions (``read_state=True``) rewrite the clicked button's
    label in place to reflect the new state — the button text is the
    state indicator. No popups, no disruptive dialogs.
    """
    w = await tmux_manager.find_window_by_id(window_id)
    if w is None:
        await query.answer("Window not found", show_alert=True)
        return
    await tmux_manager.send_keys(
        w.window_id, action.payload, enter=False, literal=action.literal
    )
    if action.read_state:
        short_label = await _refresh_button_label(action, query, window_id)
        await query.answer(f"{action.emoji} {short_label}")
    else:
        await query.answer(f"{action.emoji} {action.text}")


async def _dispatch_text(
    action: ToolbarAction, query: CallbackQuery, window_id: str
) -> None:
    """Send literal text + Enter for a ``text`` action."""
    w = await tmux_manager.find_window_by_id(window_id)
    if w is None:
        await query.answer("Window not found", show_alert=True)
        return
    await tmux_manager.send_keys(w.window_id, action.payload, enter=True, literal=True)
    if action.read_state:
        short_label = await _refresh_button_label(action, query, window_id)
        await query.answer(f"{action.emoji} {short_label}")
    else:
        await query.answer(f"{action.emoji} {action.text}")


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
