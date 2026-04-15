"""Per-window poll cycle — one tick for one thread-bound tmux window.

Owns all per-window decisions that the polling coordinator delegates:
dead-window detection, transcript discovery, interactive UI checks,
status updates, multi-pane scanning, and passive shell relay.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError

from ..claude_task_state import claude_task_state
from ..providers import get_provider_for_window
from ..providers.base import StatusUpdate
from ..session import session_manager
from ..session_monitor import get_active_monitor
from ..thread_router import thread_router
from ..tmux_manager import tmux_manager
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
from .polling_strategies import (
    interactive_strategy,
    is_shell_prompt,
    lifecycle_strategy,
    terminal_poll_state,
    terminal_screen_buffer,
)
from .recovery_callbacks import build_recovery_keyboard
from .topic_emoji import update_topic_emoji
from .transcript_discovery import discover_and_register_transcript

if TYPE_CHECKING:
    from telegram import Bot

    from ..tmux_manager import TmuxWindow

logger = structlog.get_logger()


# ── Typing throttle ─────────────────────────────────────────────────────


async def _send_typing_throttled(bot: Bot, user_id: int, thread_id: int | None) -> None:
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


# ── Pyte parsing ────────────────────────────────────────────────────────


def _parse_with_pyte(
    window_id: str,
    pane_text: str,
    columns: int = 0,
    rows: int = 0,
) -> StatusUpdate | None:
    return terminal_screen_buffer.parse_with_pyte(window_id, pane_text, columns, rows)


# ── Transcript activity check ───────────────────────────────────────────


def _check_transcript_activity(window_id: str) -> bool:
    session_id = session_manager.get_session_id_for_window(window_id)
    if not session_id:
        return False

    mon = get_active_monitor()
    if not mon:
        return False
    last_activity = mon.get_last_activity(session_id)
    return terminal_poll_state.is_recently_active(window_id, last_activity)


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
    terminal_poll_state.cancel_startup_timer(window_id)
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
        terminal_poll_state.cancel_startup_timer(window_id)
        if not get_provider_for_window(window_id).capabilities.supports_hook:
            terminal_poll_state.mark_seen_status(window_id)
            await _transition_to_idle(
                bot, user_id, window_id, thread_id, chat_id, display, notif_mode
            )
            return

        await update_topic_emoji(bot, chat_id, thread_id, "done", display)
        lifecycle_strategy.start_autoclose_timer(user_id, thread_id, "done", now)
        lifecycle_strategy.clear_typing_state(user_id, thread_id)
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)
    elif terminal_poll_state.check_seen_status(window_id):
        await _transition_to_idle(
            bot, user_id, window_id, thread_id, chat_id, display, notif_mode
        )
    elif terminal_poll_state.get_state(window_id).startup_time is None:
        terminal_poll_state.begin_startup_timer(window_id, now)
        await _send_typing_throttled(bot, user_id, thread_id)
        await update_topic_emoji(bot, chat_id, thread_id, "active", display)
        lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)
    elif terminal_poll_state.is_startup_expired(window_id):
        terminal_poll_state.mark_seen_status(window_id)
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
    if terminal_screen_buffer.is_single_pane_cached(window_id):
        return

    panes = await tmux_manager.list_panes(window_id)
    terminal_screen_buffer.update_pane_count_cache(window_id, len(panes))
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
    _window: TmuxWindow | None = None,
) -> None:
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
        clean_text = terminal_screen_buffer.get_rendered_text(window_id, pane_text)
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
    if not get_provider_for_window(window_id).capabilities.chat_first_command_path:
        return
    ws = terminal_poll_state.get_state(window_id)
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
    if lifecycle_strategy.is_dead_notified(user_id, thread_id, wid):
        return
    terminal_poll_state.clear_seen_status(wid)

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
                terminal_poll_state.reset_probe_failures(wid)
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


# ── Status resolution helpers ──────────────────────────────────────────


async def _resolve_status(
    window_id: str, pane_text: str, w: TmuxWindow
) -> StatusUpdate | None:
    status = _parse_with_pyte(
        window_id, pane_text, columns=w.pane_width, rows=w.pane_height
    )
    if status is not None:
        return status
    clean_text = terminal_screen_buffer.get_rendered_text(window_id, pane_text)
    provider = get_provider_for_window(window_id)
    pane_title = ""
    if provider.capabilities.uses_pane_title:
        pane_title = await tmux_manager.get_pane_title(w.window_id)
    return provider.parse_terminal_status(clean_text, pane_title=pane_title)


def _check_vim_insert(window_id: str, pane_text: str, w: TmuxWindow) -> None:
    from ..tmux_manager import _has_insert_indicator, notify_vim_insert_seen

    vim_text = terminal_screen_buffer.get_rendered_text(window_id, pane_text)
    if _has_insert_indicator(vim_text):
        notify_vim_insert_seen(w.window_id)


def _build_status_line(status: StatusUpdate | None) -> str | None:
    if not status or status.is_interactive:
        return None
    if "\n" in status.raw_text:
        return status.raw_text
    from ..terminal_parser import status_emoji_prefix

    return f"{status_emoji_prefix(status.raw_text)} {status.raw_text}"


async def _emit_active_status(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int | None,
    status_line: str,
    notif_mode: str,
) -> None:
    claude_task_state.clear_wait_header(window_id)
    claude_task_state.set_last_status(window_id, status_line)
    terminal_poll_state.mark_seen_status(window_id)
    await _send_typing_throttled(bot, user_id, thread_id)
    if notif_mode not in ("muted", "errors_only"):
        from ..claude_task_state import build_subagent_label, get_subagent_names

        subagent_names = get_subagent_names(window_id)
        display_status = status_line
        if subagent_names:
            label = build_subagent_label(subagent_names)
            display_status = f"{status_line} ({label})"
        await enqueue_status_update(
            bot, user_id, window_id, display_status, thread_id=thread_id
        )
    if thread_id is not None:
        chat_id = thread_router.resolve_chat_id(user_id, thread_id)
        display = thread_router.get_display_name(window_id)
        await update_topic_emoji(bot, chat_id, thread_id, "active", display)
        lifecycle_strategy.clear_autoclose_timer(user_id, thread_id)


# ── Main per-window orchestration ──────────────────────────────────────


async def _update_status(
    bot: Bot,
    user_id: int,
    window_id: str,
    thread_id: int | None = None,
    *,
    _window: TmuxWindow | None = None,
) -> None:
    w = _window or await tmux_manager.find_window_by_id(window_id)
    if not w:
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)
        return

    pane_text = await tmux_manager.capture_pane(w.window_id, with_ansi=True)
    if not pane_text:
        return

    _check_vim_insert(window_id, pane_text, w)
    status = await _resolve_status(window_id, pane_text, w)

    interactive_window = get_interactive_window(user_id, thread_id)
    should_check_new_ui = True

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

    status_line = _build_status_line(status)
    notif_mode = session_manager.get_notification_mode(window_id)

    if status_line:
        await _emit_active_status(
            bot, user_id, window_id, thread_id, status_line, notif_mode
        )
    else:
        await _handle_no_status(
            bot, user_id, window_id, thread_id, w.pane_current_command, notif_mode
        )


# ── Entry point ──────────────────────────────────────────────────────────


async def tick_window(
    bot: Bot,
    user_id: int,
    thread_id: int,
    window_id: str,
    window: TmuxWindow | None,
) -> None:
    """Run one poll cycle for one window."""
    if lifecycle_strategy.is_dead_notified(user_id, thread_id, window_id):
        return

    if window is None:
        await _handle_dead_window_notification(bot, user_id, thread_id, window_id)
        return

    await discover_and_register_transcript(
        window_id,
        _window=window,
        bot=bot,
        user_id=user_id,
        thread_id=thread_id,
    )

    queue = get_message_queue(user_id)
    if queue and not queue.empty():
        await _check_interactive_only(
            bot, user_id, window_id, thread_id, _window=window
        )
        await _scan_window_panes(bot, user_id, window_id, thread_id)
        await _maybe_check_passive_shell(bot, user_id, window_id, thread_id)
        return

    await _update_status(bot, user_id, window_id, thread_id=thread_id, _window=window)
    await _scan_window_panes(bot, user_id, window_id, thread_id)
    await _maybe_check_passive_shell(bot, user_id, window_id, thread_id)
