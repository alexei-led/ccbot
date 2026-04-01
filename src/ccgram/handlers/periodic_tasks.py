"""Periodic task orchestration for the polling subsystem.

Orchestrates time-gated tasks within the poll loop: message broker delivery,
mailbox sweep, spawn request processing, topic lifecycle management, and
state pruning.

Key components:
  - run_periodic_tasks: time-gated broker, sweep, and topic check
  - run_lifecycle_tasks: per-tick autoclose and unbound window management
  - run_broker_cycle: message broker delivery (also called from hook_events)
"""

import time
from typing import TYPE_CHECKING

import structlog
from telegram import Bot
from telegram.error import TelegramError

from ..config import config
from ..session import session_manager
from ..tmux_manager import tmux_manager
from ..utils import log_throttle_sweep
from .msg_broker import BROKER_CYCLE_INTERVAL, SWEEP_INTERVAL
from .topic_lifecycle import (
    check_autoclose_timers,
    check_unbound_window_ttl,
    probe_topic_existence,
    prune_stale_state,
)

if TYPE_CHECKING:
    from ..tmux_manager import TmuxWindow

logger = structlog.get_logger()

# ── Timing constants ──────────────────────────────────────────────────────

TOPIC_CHECK_INTERVAL = 60.0  # seconds


# ── Broker integration ────────────────────────────────────────────────────


async def run_broker_cycle(
    bot: Bot | None = None,
    idle_windows: frozenset[str] = frozenset(),
) -> None:
    """Run one broker delivery cycle (called from poll loop and hook_events)."""
    from ..mailbox import Mailbox

    from .msg_broker import broker_delivery_cycle

    mailbox = Mailbox(config.mailbox_dir)
    await broker_delivery_cycle(
        mailbox=mailbox,
        tmux_mgr=tmux_manager,
        window_states=session_manager.window_states,
        tmux_session=config.tmux_session_name,
        msg_rate_limit=config.msg_rate_limit,
        bot=bot,
        idle_windows=idle_windows,
    )
    if bot is not None:
        await _run_spawn_cycle(bot)


async def _run_spawn_cycle(bot: Bot) -> None:
    """Scan for file-based spawn requests and post approval keyboards or auto-approve."""
    from ..spawn_request import pop_pending, scan_spawn_requests
    from .msg_spawn import (
        handle_spawn_approval,
        post_spawn_approval_keyboard,
    )

    new_requests = scan_spawn_requests(spawn_timeout=config.msg_spawn_timeout)
    for req in new_requests:
        try:
            if req.auto or config.msg_auto_spawn:
                await handle_spawn_approval(
                    req.id, bot, spawn_timeout=config.msg_spawn_timeout
                )
            else:
                posted = await post_spawn_approval_keyboard(
                    bot, req.requester_window, req
                )
                if not posted:
                    pop_pending(req.id)
        except OSError, TelegramError:
            pop_pending(req.id)
            logger.debug("Failed to process spawn request", request_id=req.id)


def _run_mailbox_sweep() -> None:
    """Run periodic mailbox sweep."""
    from ..mailbox import Mailbox

    mailbox = Mailbox(config.mailbox_dir)
    removed = mailbox.sweep()
    if removed:
        logger.debug("Mailbox sweep removed %d messages", removed)


# ── Orchestration ──────────────────────────────────────────────────────────


async def run_periodic_tasks(
    bot: Bot,
    all_windows: list["TmuxWindow"],
    timers: dict[str, float],
) -> None:
    """Run time-gated periodic tasks (topic check, broker, sweep)."""
    now = time.monotonic()
    if now - timers["topic_check"] >= TOPIC_CHECK_INTERVAL:
        timers["topic_check"] = now
        await prune_stale_state(all_windows)
        await probe_topic_existence(bot)
        log_throttle_sweep()

    if now - timers["broker"] >= BROKER_CYCLE_INTERVAL:
        timers["broker"] = now
        await run_broker_cycle(bot)

    if now - timers["sweep"] >= SWEEP_INTERVAL:
        timers["sweep"] = now
        _run_mailbox_sweep()


async def run_lifecycle_tasks(bot: Bot, all_windows: list["TmuxWindow"]) -> None:
    """Run per-tick lifecycle tasks (autoclose timers, unbound window TTL)."""
    await check_autoclose_timers(bot)
    await check_unbound_window_ttl(all_windows)
