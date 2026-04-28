"""Recovery UI callback handlers.

Handles inline keyboard callbacks for dead window recovery:
  - CB_RECOVERY_FRESH: Create a fresh session in the same directory
  - CB_RECOVERY_CONTINUE: Continue most recent session (claude --continue)
  - CB_RECOVERY_RESUME: Show session picker, resume selected (claude --resume)
  - CB_RECOVERY_PICK: User picks a specific session from the resume list
  - CB_RECOVERY_BACK: Return to recovery options menu from session picker
  - CB_RECOVERY_CANCEL: Cancel recovery

Also exposes ``RecoveryBanner`` + ``render_banner`` — the unified text+keyboard
contract used by every entry point that surfaces the recovery UI (proactive
dead-window notification, /restore, recovery from a typed message). Keeping
the rendering in one place is what Task 1.9 of the Telegram UX overhaul plan
calls for.

Key function: handle_recovery_callback (uniform callback handler signature).
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import config
from ..providers import get_provider, get_provider_for_window, resolve_launch_command
from .. import window_query
from ..session import session_manager
from ..session_map import session_map_sync
from ..thread_router import thread_router
from ..tmux_manager import send_to_window, tmux_manager
from ..utils import read_session_metadata_from_jsonl
from ..window_state_store import CCGRAM_CREATED_WINDOW_ORIGIN
from .callback_data import (
    CB_RECOVERY_BACK,
    CB_RECOVERY_BROWSE,
    CB_RECOVERY_CANCEL,
    CB_RECOVERY_CONTINUE,
    CB_RECOVERY_FRESH,
    CB_RECOVERY_PICK,
    CB_RECOVERY_RESUME,
)
from .callback_helpers import get_thread_id
from .callback_registry import register
from .message_sender import safe_edit, safe_send
from .topic_emoji import format_topic_name_for_mode
from .user_state import (
    PENDING_THREAD_ID,
    PENDING_THREAD_TEXT,
    RECOVERY_SESSIONS,
    RECOVERY_WINDOW_ID,
)

logger = structlog.get_logger()

_MAX_RESUME_SESSIONS = 6


@dataclass
class _SessionEntry:
    """A resumable session discovered from project directories."""

    session_id: str
    summary: str
    mtime: float = 0.0


RecoveryMode = Literal["dead", "restore", "resume"]


@dataclass(frozen=True)
class RecoveryBanner:
    """Inputs for the unified recovery banner.

    The banner is the dead-window notification ccgram shows in three
    situations: a window died proactively (``dead``), the user invoked
    /restore (``restore``), or the user opened the resume picker
    (``resume``). All three flow through ``render_banner`` so the keyboard,
    subtitle, and copy stay consistent across entry points.
    """

    chat_id: int
    thread_id: int
    window_id: str
    mode: RecoveryMode
    provider: str | None = None
    display: str = ""
    cwd: str = ""


def render_banner(banner: RecoveryBanner) -> tuple[str, InlineKeyboardMarkup]:
    """Render the recovery banner text and inline keyboard.

    Returns the message body and a :class:`InlineKeyboardMarkup` ready to
    pass to ``safe_reply`` / ``rate_limit_send_message``. The keyboard is
    the provider-aware action keyboard from :func:`build_recovery_keyboard`
    in every mode — modes only differ in the surrounding copy so the user
    knows whether the banner appeared on its own or in response to a
    request.
    """

    keyboard = build_recovery_keyboard(banner.window_id)
    help_text = _recovery_help_text(banner.window_id)
    cwd_line = f"\n\U0001f4c2 `{banner.cwd}`" if banner.cwd else ""
    label = banner.display or banner.window_id

    if banner.mode == "restore":
        title = f"\U0001f504 Restore `{label}`."
        prompt = f"Choose how to continue.\n{help_text}"
    elif banner.mode == "resume":
        title = f"⏪ Resume `{label}`."
        prompt = f"Pick a session below or use the menu.\n{help_text}"
    else:
        title = f"⚠ Session `{label}` ended."
        prompt = f"Tap a button or send a message to recover.\n{help_text}"

    text = f"{title}{cwd_line}\n\n{prompt}"
    return text, keyboard


def _recovery_help_text(window_id: str) -> str:
    """Return a one-line subtitle explaining the available recovery actions.

    Mirrors the keyboard layout in ``build_recovery_keyboard`` so users can
    read what each button does without trial and error. Buttons hidden by
    the active provider's capabilities are omitted from the subtitle too.
    """

    caps = get_provider_for_window(
        window_id, provider_name=window_query.get_window_provider(window_id)
    ).capabilities
    parts = ["Start fresh"]
    if caps.supports_continue:
        parts.append("Continue last session")
    if caps.supports_resume:
        parts.append("Resume from list")
    return " · ".join(parts)


def build_recovery_keyboard(window_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for dead window recovery options.

    Buttons for Continue and Resume are only shown when the active provider
    declares support for those capabilities.
    """

    caps = get_provider_for_window(
        window_id, provider_name=window_query.get_window_provider(window_id)
    ).capabilities
    options: list[InlineKeyboardButton] = [
        InlineKeyboardButton(
            "\U0001f195 Fresh",
            callback_data=f"{CB_RECOVERY_FRESH}{window_id}"[:64],
        ),
    ]
    if caps.supports_continue:
        options.append(
            InlineKeyboardButton(
                "\u25b6 Continue",
                callback_data=f"{CB_RECOVERY_CONTINUE}{window_id}"[:64],
            )
        )
    if caps.supports_resume:
        options.append(
            InlineKeyboardButton(
                "\u23ea Resume",
                callback_data=f"{CB_RECOVERY_RESUME}{window_id}"[:64],
            )
        )
    return InlineKeyboardMarkup(
        [
            options,
            [InlineKeyboardButton("\u2716 Cancel", callback_data=CB_RECOVERY_CANCEL)],
        ]
    )


def _build_resume_picker_keyboard(
    sessions: list[_SessionEntry],
    window_id: str,
) -> InlineKeyboardMarkup:
    """Build inline keyboard listing recent sessions for resume."""
    from .resume_command import format_session_entry

    rows: list[list[InlineKeyboardButton]] = []
    for idx, entry in enumerate(sessions[:_MAX_RESUME_SESSIONS]):
        label = format_session_entry(
            summary=entry.summary,
            session_id=entry.session_id,
            mtime=entry.mtime,
        )
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{CB_RECOVERY_PICK}{idx}"[:64],
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "\u2b05 Back",
                callback_data=f"{CB_RECOVERY_BACK}{window_id}"[:64],
            ),
            InlineKeyboardButton("\u2716 Cancel", callback_data=CB_RECOVERY_CANCEL),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _build_empty_resume_keyboard(window_id: str) -> InlineKeyboardMarkup:
    """Build the inline keyboard shown when no sessions exist for the cwd.

    Offers two paths so the user is never stuck on a dead toast:
      - Browse other projects (cross-project picker via CB_RECOVERY_BROWSE)
      - Start fresh (reuses the recovery fresh handler)
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "\U0001f5c2 Browse other projects",
                    callback_data=f"{CB_RECOVERY_BROWSE}{window_id}"[:64],
                ),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f195 Start fresh",
                    callback_data=f"{CB_RECOVERY_FRESH}{window_id}"[:64],
                ),
            ],
            [InlineKeyboardButton("\u2716 Cancel", callback_data=CB_RECOVERY_CANCEL)],
        ]
    )


def scan_sessions_for_cwd(cwd: str) -> list[_SessionEntry]:
    """Scan project directories for sessions matching a working directory.

    Supports both legacy sessions-index.json and bare JSONL files
    (Claude Code >= Feb 2026 no longer writes index files).

    Returns up to _MAX_RESUME_SESSIONS entries, most-recent file first.
    """
    if not config.claude_projects_path.exists():
        return []

    try:
        resolved_cwd = str(Path(cwd).resolve())
    except OSError:
        return []

    candidates: list[tuple[float, _SessionEntry]] = []
    seen_ids: set[str] = set()

    for project_dir in config.claude_projects_path.iterdir():
        if not project_dir.is_dir():
            continue

        # Try legacy sessions-index.json first
        index_file = project_dir / "sessions-index.json"
        if index_file.exists():
            _scan_index_for_cwd(index_file, resolved_cwd, seen_ids, candidates)

        # Pick up bare JSONL files (no index required)
        _scan_bare_jsonl_for_cwd(project_dir, resolved_cwd, seen_ids, candidates)

    candidates.sort(key=lambda c: c[0], reverse=True)
    return [entry for _, entry in candidates[:_MAX_RESUME_SESSIONS]]


def _scan_index_for_cwd(
    index_file: Path,
    resolved_cwd: str,
    seen_ids: set[str],
    candidates: list[tuple[float, _SessionEntry]],
) -> None:
    """Scan a sessions-index.json for sessions matching a cwd."""
    try:
        index_data = json.loads(index_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):  # fmt: skip
        return

    original_path = index_data.get("originalPath", "")
    for entry in index_data.get("entries", []):
        session_id = entry.get("sessionId", "")
        full_path = entry.get("fullPath", "")
        project_path = entry.get("projectPath", original_path)
        if not session_id or not full_path or session_id in seen_ids:
            continue

        try:
            norm_pp = str(Path(project_path).resolve())
        except OSError:
            norm_pp = project_path

        if norm_pp != resolved_cwd:
            continue

        file_path = Path(full_path)
        if not file_path.exists():
            continue

        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = 0.0

        summary = (
            entry.get("summary", "") or entry.get("firstPrompt", "") or session_id[:12]
        )
        seen_ids.add(session_id)
        candidates.append((mtime, _SessionEntry(session_id, summary, mtime)))


def _scan_bare_jsonl_for_cwd(
    project_dir: Path,
    resolved_cwd: str,
    seen_ids: set[str],
    candidates: list[tuple[float, _SessionEntry]],
) -> None:
    """Scan bare JSONL files for sessions matching a cwd."""
    try:
        jsonl_iter = project_dir.glob("*.jsonl")
    except OSError:
        return

    for jsonl_file in jsonl_iter:
        session_id = jsonl_file.stem
        if session_id in seen_ids:
            continue

        file_cwd, summary = read_session_metadata_from_jsonl(jsonl_file)
        if not file_cwd:
            continue

        try:
            norm_cwd = str(Path(file_cwd).resolve())
        except OSError:
            norm_cwd = file_cwd

        if norm_cwd != resolved_cwd:
            continue

        try:
            mtime = jsonl_file.stat().st_mtime
        except OSError:
            mtime = 0.0

        seen_ids.add(session_id)
        candidates.append(
            (mtime, _SessionEntry(session_id, summary or session_id[:12], mtime))
        )


async def handle_recovery_callback(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle recovery UI callbacks."""
    # Order matters: CB_RECOVERY_BROWSE ("rec:br:") shares its prefix with
    # CB_RECOVERY_BACK ("rec:b:"), so BROWSE must be tested first.
    if data.startswith(CB_RECOVERY_BROWSE):
        await _handle_browse(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_BACK):
        await _handle_back(query, data, update, context)
    elif data.startswith(CB_RECOVERY_FRESH):
        await _handle_fresh(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_CONTINUE):
        await _handle_continue(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_RESUME):
        await _handle_resume(query, user_id, data, update, context)
    elif data.startswith(CB_RECOVERY_PICK):
        await _handle_resume_pick(query, user_id, data, update, context)
    elif data == CB_RECOVERY_CANCEL:
        await _handle_cancel(query, update, context)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _validate_recovery_state(
    data_suffix: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[int, str, str] | None:
    """Validate common recovery preconditions.

    Supports two paths:
      1. Text-handler path: PENDING_THREAD_ID and RECOVERY_WINDOW_ID in user_data.
      2. Proactive notification path: no user_data state, validate via binding.

    Returns (thread_id, old_window_id, cwd) on success, or None on failure
    (caller should return early and call query.answer).
    """
    thread_id = get_thread_id(update)
    if thread_id is None:
        return None

    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return None

    pending_tid = (
        context.user_data.get(PENDING_THREAD_ID) if context.user_data else None
    )
    stored_wid = (
        context.user_data.get(RECOVERY_WINDOW_ID) if context.user_data else None
    )

    if pending_tid is not None:
        # Text-handler path: validate stored state
        if thread_id != pending_tid or stored_wid != data_suffix:
            return None
    else:
        # Proactive notification path: validate via session_manager binding
        bound_wid = thread_router.get_window_for_thread(user_id, thread_id)
        if bound_wid != data_suffix:
            return None
        # Set up recovery state for downstream handlers
        if context.user_data is not None:
            context.user_data[PENDING_THREAD_ID] = thread_id
            context.user_data[RECOVERY_WINDOW_ID] = data_suffix

    view = session_manager.view_window(data_suffix)
    cwd = view.cwd if view else ""
    return thread_id, data_suffix, cwd


def _clear_recovery_state(user_data: dict | None) -> None:
    """Remove all recovery-related keys from user_data."""
    if user_data is None:
        return
    for key in (
        PENDING_THREAD_ID,
        PENDING_THREAD_TEXT,
        RECOVERY_WINDOW_ID,
        RECOVERY_SESSIONS,
    ):
        user_data.pop(key, None)


async def _create_and_bind_window(
    query: CallbackQuery,
    user_id: int,
    thread_id: int,
    cwd: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    agent_args: str = "",
    success_label: str = "Session started.",
    old_window_id: str = "",
) -> bool:
    """Create a new tmux window, bind it, rename topic, forward pending text.

    Returns True on success, False on failure.
    """
    # Unbind old dead window and clear dead-notification tracking
    thread_router.unbind_thread(user_id, thread_id)
    from .polling_strategies import lifecycle_strategy

    lifecycle_strategy.clear_dead_notification(user_id, thread_id)

    # Resolve provider from old window (falls back to global default)
    if old_window_id:
        old_view = session_manager.view_window(old_window_id)
        provider = get_provider_for_window(
            old_window_id, provider_name=old_view.provider_name if old_view else None
        )
        approval_mode = old_view.approval_mode if old_view else "normal"
    else:
        provider = get_provider()
        approval_mode = "normal"
    launch_command = resolve_launch_command(
        provider.capabilities.name, approval_mode=approval_mode
    )

    success, message, created_wname, created_wid = await tmux_manager.create_window(
        cwd, agent_args=agent_args, launch_command=launch_command
    )
    if not success:
        await safe_edit(query, f"\u274c {message}")
        _clear_recovery_state(context.user_data)
        await query.answer("Failed")
        return False

    # Only wait for session_map if provider supports hooks (avoids 5s timeout)
    if provider.capabilities.supports_hook:
        await session_map_sync.wait_for_session_map_entry(created_wid)

    # Propagate provider to new window
    session_manager.set_window_origin(created_wid, CCGRAM_CREATED_WINDOW_ORIGIN)
    session_manager.set_window_provider(created_wid, provider.capabilities.name)
    session_manager.set_window_approval_mode(created_wid, approval_mode)

    thread_router.bind_thread(
        user_id, thread_id, created_wid, window_name=created_wname
    )
    chat = query.message.chat if query.message else None
    if chat and chat.type in ("group", "supergroup"):
        thread_router.set_group_chat_id(user_id, thread_id, chat.id)

    try:
        await context.bot.edit_forum_topic(
            chat_id=thread_router.resolve_chat_id(user_id, thread_id),
            message_thread_id=thread_id,
            name=format_topic_name_for_mode(created_wname, approval_mode),
        )
    except TelegramError as e:
        logger.debug("Failed to rename topic: %s", e)

    await safe_edit(query, f"\u2705 {message}\n\n{success_label}")

    # Forward pending text
    pending_text = (
        context.user_data.get(PENDING_THREAD_TEXT) if context.user_data else None
    )
    _clear_recovery_state(context.user_data)
    if pending_text:
        send_ok, send_msg = await send_to_window(created_wid, pending_text)
        if not send_ok:
            logger.warning("Failed to forward pending text: %s", send_msg)
            await safe_send(
                context.bot,
                thread_router.resolve_chat_id(user_id, thread_id),
                f"\u274c Failed to send pending message: {send_msg}",
                message_thread_id=thread_id,
            )
    await query.answer("Created")
    return True


# ---------------------------------------------------------------------------
# Individual handlers
# ---------------------------------------------------------------------------


async def _handle_back(
    query: CallbackQuery,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_BACK: return to the recovery options menu."""
    window_id = data[len(CB_RECOVERY_BACK) :]
    validated = _validate_recovery_state(window_id, update, context)
    if validated is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return
    thread_id, _, cwd = validated
    if query.message is None or query.message.chat is None:
        await query.answer("Chat unavailable", show_alert=True)
        return
    chat_id = query.message.chat.id
    display = thread_router.get_display_name(window_id) or window_id
    banner = RecoveryBanner(
        chat_id=chat_id,
        thread_id=thread_id,
        window_id=window_id,
        mode="restore",
        provider=window_query.get_window_provider(window_id),
        display=display,
        cwd=cwd,
    )
    text, kb = render_banner(banner)
    await safe_edit(query, text, reply_markup=kb)
    await query.answer()


async def _handle_fresh(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_FRESH: create fresh session in same directory."""
    old_wid = data[len(CB_RECOVERY_FRESH) :]
    validated = _validate_recovery_state(old_wid, update, context)
    if validated is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    thread_id, _, cwd = validated
    if not cwd or not Path(cwd).is_dir():
        await safe_edit(query, "\u274c Directory no longer exists.")
        _clear_recovery_state(context.user_data)
        await query.answer("Project gone")
        return

    await _create_and_bind_window(
        query,
        user_id,
        thread_id,
        cwd,
        context,
        success_label="Fresh session started.",
        old_window_id=old_wid,
    )


async def _handle_continue(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_CONTINUE: resume most recent session via --continue.

    If there are no sessions on disk for ``cwd``, ``--continue`` would fail
    silently inside the agent. Surface the empty-state UI instead so the
    user can pick another project or start fresh.
    """
    old_wid = data[len(CB_RECOVERY_CONTINUE) :]
    validated = _validate_recovery_state(old_wid, update, context)
    if validated is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    thread_id, _, cwd = validated
    if not cwd or not Path(cwd).is_dir():
        await safe_edit(query, "\u274c Directory no longer exists.")
        _clear_recovery_state(context.user_data)
        await query.answer("Project gone")
        return

    if not await asyncio.to_thread(scan_sessions_for_cwd, cwd):
        await _send_empty_state(query, old_wid, cwd)
        return

    launch_args = get_provider_for_window(
        old_wid, provider_name=window_query.get_window_provider(old_wid)
    ).make_launch_args(use_continue=True)
    await _create_and_bind_window(
        query,
        user_id,
        thread_id,
        cwd,
        context,
        agent_args=launch_args,
        success_label="Continuing previous session.",
        old_window_id=old_wid,
    )


async def _handle_resume(
    query: CallbackQuery,
    _user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_RESUME: show session picker for --resume."""
    old_wid = data[len(CB_RECOVERY_RESUME) :]
    validated = _validate_recovery_state(old_wid, update, context)
    if validated is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    _, _, cwd = validated
    if not cwd or not Path(cwd).is_dir():
        await safe_edit(query, "\u274c Directory no longer exists.")
        _clear_recovery_state(context.user_data)
        await query.answer("Project gone")
        return

    sessions = await asyncio.to_thread(scan_sessions_for_cwd, cwd)
    if not sessions:
        await _send_empty_state(query, old_wid, cwd)
        return

    # Store session list for pick callback
    if context.user_data is not None:
        context.user_data[RECOVERY_SESSIONS] = [
            {"session_id": s.session_id, "summary": s.summary, "mtime": s.mtime}
            for s in sessions
        ]

    keyboard = _build_resume_picker_keyboard(sessions, old_wid)
    await safe_edit(
        query,
        f"\u23ea Select a session to resume:\n(`{cwd}`)",
        reply_markup=keyboard,
    )
    await query.answer()


async def _send_empty_state(
    query: CallbackQuery,
    window_id: str,
    cwd: str,
) -> None:
    """Edit the recovery message to the no-sessions empty-state UI.

    Replaces the legacy ``query.answer("No sessions ...", show_alert=True)``
    toast with an inline keyboard so the user has explicit next steps
    instead of being trapped on a dismissable alert.
    """

    keyboard = _build_empty_resume_keyboard(window_id)
    await safe_edit(
        query,
        f"\u26a0 No sessions in this folder yet.\n(`{cwd}`)",
        reply_markup=keyboard,
    )
    await query.answer()


async def _handle_browse(
    query: CallbackQuery,
    _user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_BROWSE: switch to the cross-project resume picker.

    The user explicitly chose to look outside the bound cwd, so the pending
    text \u2014 which targeted the original project \u2014 is dropped before
    delegating to the /resume cross-project flow.
    """

    from .resume_command import _build_resume_keyboard, scan_all_sessions
    from .user_state import RESUME_SESSIONS

    old_wid = data[len(CB_RECOVERY_BROWSE) :]
    validated = _validate_recovery_state(old_wid, update, context)
    if validated is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    sessions = await asyncio.to_thread(scan_all_sessions)
    if not sessions:
        await safe_edit(query, "\u26a0 No past sessions found in any project.")
        _clear_recovery_state(context.user_data)
        await query.answer("Nothing to resume")
        return

    if context.user_data is not None:
        # Switching flows: drop the recovery-specific pending text since the
        # target project may differ. Keep PENDING_THREAD_ID for /resume reuse.
        context.user_data.pop(PENDING_THREAD_TEXT, None)
        context.user_data.pop(RECOVERY_SESSIONS, None)
        context.user_data[RESUME_SESSIONS] = [
            {
                "session_id": s.session_id,
                "summary": s.summary,
                "cwd": s.cwd,
                "mtime": s.mtime,
                "msg_count": s.msg_count,
            }
            for s in sessions
        ]

    keyboard = _build_resume_keyboard(
        context.user_data[RESUME_SESSIONS] if context.user_data else [], page=0
    )
    await safe_edit(query, "\u23ea Select a session to resume:", reply_markup=keyboard)
    await query.answer()


async def _handle_resume_pick(
    query: CallbackQuery,
    user_id: int,
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_PICK: user selected a session from resume picker."""
    idx_str = data[len(CB_RECOVERY_PICK) :]
    try:
        idx = int(idx_str)
    except ValueError:
        await query.answer("Couldn't read selection", show_alert=True)
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        await query.answer("Use in a topic", show_alert=True)
        return

    pending_tid = (
        context.user_data.get(PENDING_THREAD_ID) if context.user_data else None
    )
    if pending_tid is None or thread_id != pending_tid:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    stored_sessions = (
        context.user_data.get(RECOVERY_SESSIONS) if context.user_data else None
    )
    if not stored_sessions or idx < 0 or idx >= len(stored_sessions):
        await query.answer("Session no longer in list", show_alert=True)
        return

    picked = stored_sessions[idx]
    session_id = picked["session_id"]

    old_wid = context.user_data.get(RECOVERY_WINDOW_ID) if context.user_data else None
    if not old_wid:
        await query.answer("Recovery menu expired", show_alert=True)
        return

    view = session_manager.view_window(old_wid)
    if view is None or not view.cwd or not Path(view.cwd).is_dir():
        await safe_edit(query, "\u274c Directory no longer exists.")
        _clear_recovery_state(context.user_data)
        await query.answer("Project gone")
        return
    cwd = view.cwd

    launch_args = get_provider_for_window(
        old_wid, provider_name=view.provider_name
    ).make_launch_args(resume_id=session_id)
    await _create_and_bind_window(
        query,
        user_id,
        thread_id,
        cwd,
        context,
        agent_args=launch_args,
        success_label=f"Resuming session: {picked['summary'][:40]}",
        old_window_id=old_wid,
    )


async def _handle_cancel(
    query: CallbackQuery,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle CB_RECOVERY_CANCEL: cancel recovery."""
    thread_id = get_thread_id(update)
    if thread_id is None:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    pending_tid = (
        context.user_data.get(PENDING_THREAD_ID) if context.user_data else None
    )
    if pending_tid is not None and thread_id != pending_tid:
        await query.answer("Stale recovery (topic mismatch)", show_alert=True)
        return

    _clear_recovery_state(context.user_data)
    await safe_edit(query, "Cancelled. Send a message to try again.")
    await query.answer("Cancelled")


# --- Registry dispatch entry point ---


@register(
    CB_RECOVERY_BACK,
    CB_RECOVERY_BROWSE,
    CB_RECOVERY_FRESH,
    CB_RECOVERY_CONTINUE,
    CB_RECOVERY_RESUME,
    CB_RECOVERY_PICK,
    CB_RECOVERY_CANCEL,
)
async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    assert query is not None and query.data is not None and user is not None
    await handle_recovery_callback(query, user.id, query.data, update, context)
