"""Per-window poll cycle — one tick for one thread-bound tmux window.

Owns all per-window decisions that the polling coordinator delegates:
dead-window detection, transcript discovery, interactive UI checks,
status updates, multi-pane scanning, and passive shell relay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .message_queue import get_message_queue
from .polling_coordinator import (
    _check_interactive_only,
    _handle_dead_window_notification,
    _maybe_check_passive_shell,
    _scan_window_panes,
    update_status_message,
)
from .polling_strategies import lifecycle_strategy
from .transcript_discovery import discover_and_register_transcript

if TYPE_CHECKING:
    from telegram import Bot

    from ..tmux_manager import TmuxWindow


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

    await update_status_message(
        bot, user_id, window_id, thread_id=thread_id, _window=window
    )
    await _scan_window_panes(bot, user_id, window_id, thread_id)
    await _maybe_check_passive_shell(bot, user_id, window_id, thread_id)
