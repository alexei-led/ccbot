"""Polling coordinator for terminal status monitoring.

Orchestrates the per-topic polling cycle: iterates thread bindings, delegates
to strategy classes for state, and handles terminal status parsing, interactive
UI detection, shell relay, and dead window notification.

Periodic tasks (broker delivery, autoclose, topic probing) are in
periodic_tasks.py. Transcript discovery is in transcript_discovery.py.

Key components:
  - status_poll_loop: Background polling task (entry point for bot.py)
  - update_status_message: Poll and enqueue status updates
"""

import asyncio
import contextlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from telegram import Bot
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError

from ..claude_task_state import claude_task_state
from ..providers import get_provider_for_window
from ..providers.base import StatusUpdate
from ..session import session_manager
from ..session_monitor import get_active_monitor
from ..thread_router import thread_router
from ..tmux_manager import tmux_manager
from ..utils import log_throttled
from .cleanup import clear_topic_state
from .interactive_ui import (
    clear_interactive_mode,
    clear_interactive_msg,
    get_interactive_window,
    handle_interactive_ui,
    set_interactive_mode,
)
from .message_queue import (
    clear_tool_msg_ids_for_topic,
    enqueue_status_update,
    get_message_queue,
)
from .message_sender import rate_limit_send_message
from .periodic_tasks import run_lifecycle_tasks, run_periodic_tasks
from .polling_strategies import (
    interactive_strategy,
    is_shell_prompt,
    lifecycle_strategy,
    terminal_strategy,
)
from .recovery_callbacks import build_recovery_keyboard
from .topic_emoji import update_topic_emoji
from .transcript_discovery import discover_and_register_transcript

if TYPE_CHECKING:
    from ..tmux_manager import TmuxWindow

logger = structlog.get_logger()

# ── Timing constants ──────────────────────────────────────────────────────

STATUS_POLL_INTERVAL: float = (
    1.0  # overridden by config.status_poll_interval at startup
)


# Exponential backoff bounds for loop errors (seconds)
_BACKOFF_MIN = 2.0
_BACKOFF_MAX = 30.0

# Top-level loop resilience: catch any error to keep polling alive
_LoopError = (TelegramError, OSError, RuntimeError, ValueError)


# ── Typing throttle ─────────────────────────────────────────────────────


async def _send_typing_throttled(bot: Bot, user_id: int, thread_id: int | None) -> None:
    """Send typing indicator if enough time has elapsed since the last one."""
    if thread_id is None:
        return
    if lifecycle_strategy.is_typing_throttled(user_id, thread_id):
        return
    lifecycle_strategy.record_typing_sent(user_id, thread_id)
    chat_id = thread_router.resolve_chat_id(user_id, thread_id)
    with contextlib.suppress(TelegramError):
        await bot.send_chat_action(
            chat_id=chat_id,
            message_thread_id=thread_id,
            action=ChatAction.TYPING,
        )


# ── RC state / pyte parsing ─────────────────────────────────────────────


def _parse_with_pyte(
    window_id: str,
    pane_text: str,
    columns: int = 0,
    rows: int = 0,
) -> StatusUpdate | None:
    """Parse terminal via pyte screen buffer for status and interactive UI."""
    return terminal_strategy.parse_with_pyte(window_id, pane_text, columns, rows)


# ── Transcript activity check ───────────────────────────────────────────


def _check_transcript_activity(window_id: str) -> bool:
    """Check if recent transcript writes indicate an active agent."""
    session_id = session_manager.get_session_id_for_window(window_id)
    if not session_id:
        return False

    mon = get_active_monitor()
    if not mon:
        return False
    last_activity = mon.get_last_activity(session_id)
    return terminal_strategy.is_recently_active(window_id, last_activity)


# ── Idle / no-status transitions ────────────────────────────────────────


async def _transition_to_idle(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int,
    chat_id: int,
    display: str,
    notif_mode: str,
) -> None:
    """Transition a window to idle state (emoji, autoclose, typing, status)."""
    terminal_strategy.cancel_startup_timer(window_id)
    await update_topic_emoji(bot, chat_id, thread_id, "idle", display)
    lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)
    lifecycle_strategy.clear_typing_state(user_id, thread_id)
    if notif_mode not in ("muted", "errors_only"):
        from .callback_data import IDLE_STATUS_TEXT

        await enqueue_status_update(
            bot, user_id, window_id, IDLE_STATUS_TEXT, thread_id=thread_id
        )
    else:
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)


async def _handle_no_status(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int | None,
    pane_current_command: str,
    notif_mode: str,
) -> None:
    """Handle a window with no provider-detected terminal status."""
    now = time.monotonic()
    is_active = _check_transcript_activity(window_id)

    if is_active:
        claude_task_state.clear_wait_header(window_id)
        await _send_typing_throttled(bot, user_id, thread_id)
        if thread_id is not None:
            chat_id = thread_router.resolve_chat_id(user_id, thread_id)
            display = thread_router.get_display_name(window_id)
            await update_topic_emoji(bot, chat_id, thread_id, "active", display)
            lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)
        return

    if thread_id is None:
        return

    chat_id = thread_router.resolve_chat_id(user_id, thread_id)
    display = thread_router.get_display_name(window_id)

    if is_shell_prompt(pane_current_command):
        terminal_strategy.cancel_startup_timer(window_id)
        state = session_manager.get_window_state(window_id)
        raw_provider = getattr(state, "provider_name", "")
        provider_name = raw_provider.lower() if isinstance(raw_provider, str) else ""
        if provider_name in ("codex", "gemini", "shell"):
            terminal_strategy.mark_seen_status(window_id)
            await _transition_to_idle(
                bot, user_id, window_id, thread_id, chat_id, display, notif_mode
            )
            return

        await update_topic_emoji(bot, chat_id, thread_id, "done", display)
        lifecycle_strategy.start_autoclose_timer(user_id, thread_id, "done", now)
        lifecycle_strategy.clear_typing_state(user_id, thread_id)
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)
    elif terminal_strategy.check_seen_status(window_id):
        await _transition_to_idle(
            bot, user_id, window_id, thread_id, chat_id, display, notif_mode
        )
    elif terminal_strategy.get_state(window_id).startup_time is None:
        terminal_strategy.begin_startup_timer(window_id, now)
        await _send_typing_throttled(bot, user_id, thread_id)
        await update_topic_emoji(bot, chat_id, thread_id, "active", display)
        lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)
    elif terminal_strategy.is_startup_expired(window_id):
        terminal_strategy.mark_seen_status(window_id)
        await _transition_to_idle(
            bot, user_id, window_id, thread_id, chat_id, display, notif_mode
        )
    else:
        await _send_typing_throttled(bot, user_id, thread_id)
        await update_topic_emoji(bot, chat_id, thread_id, "active", display)
        lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)


# ── Multi-pane scanning (agent teams) ─────────────────────────────────


async def _scan_window_panes(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int,
) -> None:
    """Scan non-active panes for interactive prompts and surface alerts."""
    if terminal_strategy.is_single_pane_cached(window_id):
        return

    now = time.monotonic()
    panes = await tmux_manager.list_panes(window_id)
    terminal_strategy.update_pane_count_cache(window_id, len(panes))
    live_pane_ids = {p.pane_id for p in panes}

    interactive_strategy.prune_stale_pane_alerts(window_id, live_pane_ids)

    if len(panes) <= 1:
        return

    now = time.monotonic()

    for pane in panes:
        if pane.active:
            continue

        pane_text = await tmux_manager.capture_pane_by_id(
            pane.pane_id, window_id=window_id
        )
        if not pane_text:
            continue

        provider = get_provider_for_window(window_id)
        status = provider.parse_terminal_status(pane_text, pane_title="")
        if status is None or not status.is_interactive:
            interactive_strategy.remove_pane_alert(pane.pane_id)
            continue

        prompt_text = status.raw_text or ""

        existing = interactive_strategy.get_pane_alert(pane.pane_id)
        if existing and existing[0] == prompt_text:
            continue

        interactive_strategy.set_pane_alert(pane.pane_id, prompt_text, now, window_id)
        logger.info(
            "Pane %s in window %s has interactive UI, surfacing alert",
            pane.pane_id,
            window_id,
        )
        await handle_interactive_ui(
            bot, user_id, window_id, thread_id, pane_id=pane.pane_id
        )


# ── Interactive-only check ───────────────────────────────────────────────


async def _check_interactive_only(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int,
    *,
    _window: "TmuxWindow | None" = None,
) -> None:
    """Check for interactive UI without enqueuing status updates."""
    w = _window or await tmux_manager.find_window_by_id(window_id)
    if not w:
        return

    if get_interactive_window(user_id, thread_id) == window_id:
        return

    pane_text = await tmux_manager.capture_pane(w.window_id, with_ansi=True)
    if not pane_text:
        return

    status = _parse_with_pyte(
        window_id, pane_text, columns=w.pane_width, rows=w.pane_height
    )

    if status is None:
        clean_text = terminal_strategy.get_rendered_text(window_id, pane_text)
        provider = get_provider_for_window(window_id)
        pane_title = ""
        if provider.capabilities.uses_pane_title:
            pane_title = await tmux_manager.get_pane_title(w.window_id)
        status = provider.parse_terminal_status(clean_text, pane_title=pane_title)

    if status is not None and status.is_interactive:
        set_interactive_mode(user_id, window_id, thread_id)
        handled = await handle_interactive_ui(bot, user_id, window_id, thread_id)
        if not handled:
            clear_interactive_mode(user_id, thread_id)


# ── Passive shell relay ──────────────────────────────────────────────────


async def _maybe_check_passive_shell(
    bot: Bot, user_id: int, window_id: str, thread_id: int
) -> None:
    """Relay shell output from direct tmux interaction to Telegram."""
    state = session_manager.get_window_state(window_id)
    if not state or state.provider_name != "shell":
        return
    ws = terminal_strategy.get_state(window_id)
    rendered = ws.last_rendered_text
    if rendered is None:
        raw = await tmux_manager.capture_pane(window_id)
        if not raw:
            return
        rendered = raw
    from .shell_capture import check_passive_shell_output

    await check_passive_shell_output(bot, user_id, thread_id, window_id, rendered)


# ── Dead window notification ─────────────────────────────────────────────


async def _handle_dead_window_notification(
    bot: Bot, user_id: int, thread_id: int, wid: str
) -> None:
    """Send proactive recovery notification for a dead window (once per death)."""
    if lifecycle_strategy.is_dead_notified(user_id, thread_id, wid):
        return
    terminal_strategy.clear_seen_status(wid)

    clear_tool_msg_ids_for_topic(user_id, thread_id)
    chat_id = thread_router.resolve_chat_id(user_id, thread_id)
    display = thread_router.get_display_name(wid)
    await update_topic_emoji(bot, chat_id, thread_id, "dead", display)
    lifecycle_strategy.start_autoclose_timer(
        user_id, thread_id, "dead", time.monotonic()
    )

    window_state = session_manager.get_window_state(wid)
    cwd = window_state.cwd or ""
    try:
        dir_exists = bool(cwd) and await asyncio.to_thread(Path(cwd).is_dir)
    except OSError:
        dir_exists = False
    if dir_exists:
        keyboard = build_recovery_keyboard(wid)
        text = (
            f"\u26a0 Session `{display}` ended.\n"
            f"\U0001f4c2 `{cwd}`\n\n"
            "Tap a button or send a message to recover."
        )
    else:
        text = f"\u26a0 Session `{display}` ended."
        keyboard = None
    sent = await rate_limit_send_message(
        bot,
        chat_id,
        text,
        message_thread_id=thread_id,
        reply_markup=keyboard,
    )
    if sent is None:
        try:
            await bot.unpin_all_forum_topic_messages(
                chat_id=chat_id, message_thread_id=thread_id
            )
        except BadRequest as probe_err:
            if (
                "thread not found" in probe_err.message.lower()
                or "topic_id_invalid" in probe_err.message.lower()
            ):
                terminal_strategy.reset_probe_failures(wid)
                await clear_topic_state(
                    user_id,
                    thread_id,
                    bot,
                    window_id=wid,
                    window_dead=True,
                )
                thread_router.unbind_thread(user_id, thread_id)
                logger.info(
                    "Topic deleted: unbound window %s for thread %d, user %d",
                    wid,
                    thread_id,
                    user_id,
                )
        except TelegramError:
            pass
    lifecycle_strategy.mark_dead_notified(user_id, thread_id, wid)


# ── Main orchestration ──────────────────────────────────────────────────


async def update_status_message(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int | None = None,
    *,
    _window: "TmuxWindow | None" = None,
) -> None:
    """Poll terminal and enqueue status update for user's active window."""
    w = _window or await tmux_manager.find_window_by_id(window_id)
    if not w:
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)
        return

    pane_text = await tmux_manager.capture_pane(w.window_id, with_ansi=True)
    if not pane_text:
        return

    interactive_window = get_interactive_window(user_id, thread_id)
    should_check_new_ui = True

    status = _parse_with_pyte(
        window_id, pane_text, columns=w.pane_width, rows=w.pane_height
    )

    # Passive vim INSERT mode tracking
    from ..tmux_manager import _has_insert_indicator, notify_vim_insert_seen

    vim_text = terminal_strategy.get_rendered_text(window_id, pane_text)
    if _has_insert_indicator(vim_text):
        notify_vim_insert_seen(w.window_id)

    if status is None:
        clean_text = terminal_strategy.get_rendered_text(window_id, pane_text)
        provider = get_provider_for_window(window_id)
        pane_title = ""
        if provider.capabilities.uses_pane_title:
            pane_title = await tmux_manager.get_pane_title(w.window_id)
        status = provider.parse_terminal_status(clean_text, pane_title=pane_title)

    if interactive_window == window_id:
        if status is not None and status.is_interactive:
            return
        await clear_interactive_msg(user_id, bot, thread_id)
        should_check_new_ui = False
    elif interactive_window is not None:
        await clear_interactive_msg(user_id, bot, thread_id)

    if should_check_new_ui and status is not None and status.is_interactive:
        await handle_interactive_ui(bot, user_id, window_id, thread_id)
        return

    status_line = None
    if status and not status.is_interactive:
        if "\n" in status.raw_text:
            status_line = status.raw_text
        else:
            from ..terminal_parser import status_emoji_prefix

            emoji = status_emoji_prefix(status.raw_text)
            status_line = f"{emoji} {status.raw_text}"

    notif_mode = session_manager.get_notification_mode(window_id)

    if status_line:
        claude_task_state.clear_wait_header(window_id)
        claude_task_state.set_last_status(window_id, status_line)
        terminal_strategy.mark_seen_status(window_id)
        await _send_typing_throttled(bot, user_id, thread_id)
        if notif_mode not in ("muted", "errors_only"):
            from .hook_events import build_subagent_label, get_subagent_names

            subagent_names = get_subagent_names(window_id)
            display_status = status_line
            if subagent_names:
                label = build_subagent_label(subagent_names)
                display_status = f"{status_line} ({label})"
            await enqueue_status_update(
                bot,
                user_id,
                window_id,
                display_status,
                thread_id=thread_id,
            )
        if thread_id is not None:
            chat_id = thread_router.resolve_chat_id(user_id, thread_id)
            display = thread_router.get_display_name(window_id)
            await update_topic_emoji(bot, chat_id, thread_id, "active", display)
            lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)
    else:
        await _handle_no_status(
            bot, user_id, window_id, thread_id, w.pane_current_command, notif_mode
        )


# ── Main loop ─────────────────────────────────────────────────────────────


async def status_poll_loop(bot: Bot) -> None:
    """Background task to poll terminal status for all thread-bound windows."""
    global STATUS_POLL_INTERVAL  # noqa: PLW0603
    from ..config import config as _cfg

    STATUS_POLL_INTERVAL = _cfg.status_poll_interval
    logger.info("Status polling started (interval: %ss)", STATUS_POLL_INTERVAL)
    timers = {"topic_check": 0.0, "broker": 0.0, "sweep": 0.0, "live_view": 0.0}
    _error_streak = 0
    while True:
        try:
            all_windows = await tmux_manager.list_windows()
            external_windows = await tmux_manager.discover_external_sessions()
            all_windows.extend(external_windows)
            window_lookup: dict[str, "TmuxWindow"] = {
                w.window_id: w for w in all_windows
            }

            await run_periodic_tasks(bot, all_windows, timers)

            for user_id, thread_id, wid in list(thread_router.iter_thread_bindings()):
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(window_id=wid)
                try:
                    if lifecycle_strategy.is_dead_notified(user_id, thread_id, wid):
                        continue

                    w = window_lookup.get(wid)
                    if not w:
                        await _handle_dead_window_notification(
                            bot, user_id, thread_id, wid
                        )
                        continue

                    await discover_and_register_transcript(
                        wid,
                        _window=w,
                        bot=bot,
                        user_id=user_id,
                        thread_id=thread_id,
                    )

                    queue = get_message_queue(user_id)
                    if queue and not queue.empty():
                        await _check_interactive_only(
                            bot, user_id, wid, thread_id, _window=w
                        )
                        await _scan_window_panes(bot, user_id, wid, thread_id)
                        await _maybe_check_passive_shell(bot, user_id, wid, thread_id)
                        continue
                    await update_status_message(
                        bot,
                        user_id,
                        wid,
                        thread_id=thread_id,
                        _window=w,
                    )
                    await _scan_window_panes(bot, user_id, wid, thread_id)
                    await _maybe_check_passive_shell(bot, user_id, wid, thread_id)
                except (TelegramError, OSError) as e:
                    log_throttled(
                        logger,
                        f"status-update:{user_id}:{thread_id}",
                        "Status update error for user %s thread %s: %s",
                        user_id,
                        thread_id,
                        e,
                    )

            await run_lifecycle_tasks(bot, all_windows)

        except _LoopError:
            logger.exception("Status poll loop error")
            backoff_delay = min(_BACKOFF_MAX, _BACKOFF_MIN * (2**_error_streak))
            _error_streak += 1
            await asyncio.sleep(backoff_delay)
            continue
        except Exception:
            logger.exception("Unexpected error in status poll loop")
            backoff_delay = min(_BACKOFF_MAX, _BACKOFF_MIN * (2**_error_streak))
            _error_streak += 1
            await asyncio.sleep(backoff_delay)
            continue

        _error_streak = 0
        await asyncio.sleep(STATUS_POLL_INTERVAL)
