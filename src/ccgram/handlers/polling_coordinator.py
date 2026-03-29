"""Thin polling coordinator loop for terminal status monitoring.

Orchestrates the polling cycle by iterating thread bindings and delegating
to domain-specific functions in status_polling.py and strategy classes in
polling_strategies.py. Owns the loop timing, error backoff, and periodic
maintenance tasks (topic probing, display name sync, autoclose, unbound TTL).

Key components:
  - status_poll_loop: Background polling task (entry point for bot.py)
  - STATUS_POLL_INTERVAL / TOPIC_CHECK_INTERVAL: Timing constants
  - Periodic tasks: autoclose timers, unbound window TTL, topic existence probes
"""

import asyncio
import structlog
import time
from pathlib import Path
from typing import TYPE_CHECKING

from telegram import Bot

if TYPE_CHECKING:
    from ..tmux_manager import TmuxWindow
from telegram.error import BadRequest, TelegramError

from ..config import config
from ..session import session_manager
from ..thread_router import thread_router
from ..tmux_manager import tmux_manager
from ..utils import log_throttle_sweep, log_throttled
from .cleanup import clear_topic_state
from .message_queue import (
    clear_tool_msg_ids_for_topic,
    get_message_queue,
)
from .message_sender import rate_limit_send_message
from .polling_strategies import (
    _MAX_PROBE_FAILURES,
    lifecycle_strategy,
    terminal_strategy,
)
from .recovery_callbacks import build_recovery_keyboard
from .topic_emoji import update_topic_emoji

logger = structlog.get_logger()

# ── Timing constants ──────────────────────────────────────────────────────

STATUS_POLL_INTERVAL = 1.0  # seconds
TOPIC_CHECK_INTERVAL = 60.0  # seconds

# Exponential backoff bounds for loop errors (seconds)
_BACKOFF_MIN = 2.0
_BACKOFF_MAX = 30.0

# Top-level loop resilience: catch any error to keep polling alive
_LoopError = (TelegramError, OSError, RuntimeError, ValueError)


# ── Autoclose timer management ────────────────────────────────────────────


async def _check_autoclose_timers(bot: Bot) -> None:
    """Close topics whose done/dead timers have expired."""
    topic_states = lifecycle_strategy._states
    if not topic_states:
        return

    now = time.monotonic()
    expired: list[tuple[int, int]] = []
    for (user_id, thread_id), ts in topic_states.items():
        if ts.autoclose is None:
            continue
        state, entered_at = ts.autoclose
        if state == "done":
            timeout = config.autoclose_done_minutes * 60
        elif state == "dead":
            timeout = config.autoclose_dead_minutes * 60
        else:
            continue
        if timeout > 0 and now - entered_at >= timeout:
            expired.append((user_id, thread_id))

    for user_id, thread_id in expired:
        await _close_expired_topic(bot, user_id, thread_id)


async def _close_expired_topic(bot: Bot, user_id: int, thread_id: int) -> None:
    """Attempt to close/delete an expired topic and clean up state."""
    chat_id = thread_router.resolve_chat_id(user_id, thread_id)
    window_id = thread_router.get_window_for_thread(user_id, thread_id)
    removed = False
    try:
        await bot.delete_forum_topic(chat_id=chat_id, message_thread_id=thread_id)
        removed = True
    except TelegramError:
        try:
            await bot.close_forum_topic(chat_id=chat_id, message_thread_id=thread_id)
            removed = True
        except TelegramError as e:
            logger.debug("Failed to auto-close topic thread=%d: %s", thread_id, e)
    if removed:
        ts = lifecycle_strategy._states.get((user_id, thread_id))
        if ts:
            ts.autoclose = None
        logger.info(
            "Auto-removed topic: chat=%d thread=%d (user=%d)",
            chat_id,
            thread_id,
            user_id,
        )
        await clear_topic_state(user_id, thread_id, bot=bot, window_id=window_id)
        thread_router.unbind_thread(user_id, thread_id)


# ── Unbound window TTL ────────────────────────────────────────────────────


async def _check_unbound_window_ttl(live_windows: list | None = None) -> None:
    """Kill unbound tmux windows whose TTL has expired."""
    timeout = config.autoclose_done_minutes * 60
    if timeout <= 0:
        return

    bound_ids: set[str] = set()
    for _, _, wid in thread_router.iter_thread_bindings():
        bound_ids.add(wid)

    if live_windows is None:
        live_windows = await tmux_manager.list_windows()
    live_ids = {w.window_id for w in live_windows}

    window_states = terminal_strategy._states
    for wid, ws in list(window_states.items()):
        if ws.unbound_timer is not None and (wid in bound_ids or wid not in live_ids):
            ws.unbound_timer = None

    now = time.monotonic()
    for w in live_windows:
        if w.window_id not in bound_ids:
            ws = terminal_strategy.get_state(w.window_id)
            if ws.unbound_timer is None:
                ws.unbound_timer = now

    _kill_expired_unbound(now, timeout)
    _prune_orphaned_poll_state(live_ids, bound_ids)


def _kill_expired_unbound(now: float, timeout: float) -> None:
    """Find and kill unbound windows past their TTL (sync helper)."""
    from .status_polling import clear_window_poll_state

    expired = [
        wid
        for wid, ws in terminal_strategy._states.items()
        if ws.unbound_timer is not None and now - ws.unbound_timer >= timeout
    ]
    for wid in expired:
        from ..tmux_manager import clear_vim_state

        clear_vim_state(wid)
        clear_window_poll_state(wid)
        logger.info("Auto-killed unbound window %s (TTL expired)", wid)


def _prune_orphaned_poll_state(live_ids: set[str], bound_ids: set[str]) -> None:
    """Remove poll state for windows that are neither live nor bound."""
    from .status_polling import clear_window_poll_state

    stale = [
        wid
        for wid in terminal_strategy._states
        if wid not in live_ids and wid not in bound_ids
    ]
    for wid in stale:
        clear_window_poll_state(wid)


# ── Dead window notification ──────────────────────────────────────────────


async def _handle_dead_window_notification(
    bot: Bot, user_id: int, thread_id: int, wid: str
) -> None:
    """Send proactive recovery notification for a dead window (once per death)."""
    dead_notified = lifecycle_strategy._dead_notified
    dead_key = (user_id, thread_id, wid)
    if dead_key in dead_notified:
        return
    terminal_strategy.get_state(wid).has_seen_status = False

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
                terminal_strategy.get_state(wid).probe_failures = 0
                await clear_topic_state(user_id, thread_id, bot, window_id=wid)
                thread_router.unbind_thread(user_id, thread_id)
                logger.info(
                    "Topic deleted: unbound window %s for thread %d, user %d",
                    wid,
                    thread_id,
                    user_id,
                )
        except TelegramError:
            pass
    dead_notified.add(dead_key)


# ── Display name sync / state pruning ─────────────────────────────────────


async def _prune_stale_state(live_windows: list) -> None:
    """Sync display names and prune orphaned state entries."""
    live_ids = {w.window_id for w in live_windows}
    live_pairs = [(w.window_id, w.window_name) for w in live_windows]
    thread_router.sync_display_names(live_pairs)
    session_manager.prune_stale_state(live_ids)


# ── Topic existence probing ───────────────────────────────────────────────


async def _probe_topic_existence(bot: Bot) -> None:
    """Probe all bound topics via Telegram API; detect deleted topics."""
    for user_id, thread_id, wid in list(thread_router.iter_thread_bindings()):
        if terminal_strategy.get_state(wid).probe_failures >= _MAX_PROBE_FAILURES:
            continue
        try:
            await bot.unpin_all_forum_topic_messages(
                chat_id=thread_router.resolve_chat_id(user_id, thread_id),
                message_thread_id=thread_id,
            )
            terminal_strategy.get_state(wid).probe_failures = 0
        except TelegramError as e:
            if isinstance(e, BadRequest) and (
                "Topic_id_invalid" in e.message
                or "thread not found" in e.message.lower()
            ):
                w = await tmux_manager.find_window_by_id(wid)
                if w:
                    await tmux_manager.kill_window(w.window_id)
                terminal_strategy.get_state(wid).probe_failures = 0
                await clear_topic_state(user_id, thread_id, bot, window_id=wid)
                thread_router.unbind_thread(user_id, thread_id)
                logger.info(
                    "Topic deleted: killed window_id '%s' and "
                    "unbound thread %d for user %d",
                    wid,
                    thread_id,
                    user_id,
                )
            else:
                count = lifecycle_strategy.record_probe_failure(wid)
                if count < _MAX_PROBE_FAILURES:
                    log_throttled(
                        logger,
                        f"topic-probe:{wid}",
                        "Topic probe error for %s: %s",
                        wid,
                        e,
                    )


# ── Main loop ─────────────────────────────────────────────────────────────


async def status_poll_loop(bot: Bot) -> None:
    """Background task to poll terminal status for all thread-bound windows."""
    from .status_polling import (
        _check_interactive_only,
        _maybe_check_passive_shell,
        _maybe_discover_transcript,
        _scan_window_panes,
        update_status_message,
    )

    logger.info("Status polling started (interval: %ss)", STATUS_POLL_INTERVAL)
    last_topic_check = 0.0
    _error_streak = 0
    dead_notified = lifecycle_strategy._dead_notified
    while True:
        try:
            all_windows = await tmux_manager.list_windows()
            external_windows = await tmux_manager.discover_external_sessions()
            all_windows.extend(external_windows)
            window_lookup: dict[str, "TmuxWindow"] = {
                w.window_id: w for w in all_windows
            }

            now = time.monotonic()
            if now - last_topic_check >= TOPIC_CHECK_INTERVAL:
                last_topic_check = now
                await _prune_stale_state(all_windows)
                await _probe_topic_existence(bot)
                log_throttle_sweep()

            for user_id, thread_id, wid in list(thread_router.iter_thread_bindings()):
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(window_id=wid)
                try:
                    if (user_id, thread_id, wid) in dead_notified:
                        continue

                    w = window_lookup.get(wid)
                    if not w:
                        await _handle_dead_window_notification(
                            bot, user_id, thread_id, wid
                        )
                        continue

                    await _maybe_discover_transcript(
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

            await _check_autoclose_timers(bot)
            await _check_unbound_window_ttl(all_windows)

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
