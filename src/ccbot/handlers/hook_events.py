"""Hook event dispatcher — routes structured events to handlers.

Receives HookEvent objects from the session monitor's event reader and
dispatches them to the appropriate handler based on event type. This
provides instant, structured notification of agent state changes instead
of relying solely on terminal scraping.

Key function: dispatch_hook_event().
"""

import structlog
from dataclasses import dataclass
from typing import Any

from telegram import Bot

from ..session import session_manager

logger = structlog.get_logger()

_WINDOW_KEY_PARTS = 2


@dataclass
class HookEvent:
    """A structured event from the hook event log."""

    event_type: str  # "Notification", "Stop", etc.
    window_key: str  # "ccbot:@0"
    session_id: str
    data: dict[str, Any]
    timestamp: float


def _resolve_users_for_window_key(
    window_key: str,
) -> list[tuple[int, int, str]]:
    """Resolve window_key to list of (user_id, thread_id, window_id).

    The window_key format is "tmux_session:window_id" (e.g. "ccbot:@0").
    We extract the window_id part and look up thread bindings.
    """
    # Extract window_id from key (e.g. "ccbot:@0" -> "@0")
    parts = window_key.rsplit(":", 1)
    if len(parts) < _WINDOW_KEY_PARTS:
        return []
    window_id = parts[1]

    results: list[tuple[int, int, str]] = []
    for user_id, thread_id, bound_wid in session_manager.iter_thread_bindings():
        if bound_wid == window_id:
            results.append((user_id, thread_id, window_id))
    return results


async def _handle_notification(event: HookEvent, bot: Bot) -> None:
    """Handle a Notification event — render interactive UI."""
    from .interactive_ui import (
        get_interactive_window,
        handle_interactive_ui,
        set_interactive_mode,
    )

    users = _resolve_users_for_window_key(event.window_key)
    if not users:
        logger.debug(
            "No users bound for notification event window_key=%s", event.window_key
        )
        return

    tool_name = event.data.get("tool_name", "")
    logger.info(
        "Hook notification: tool_name=%s, window_key=%s",
        tool_name,
        event.window_key,
    )

    for user_id, thread_id, window_id in users:
        # Skip if already in interactive mode for this window
        existing = get_interactive_window(user_id, thread_id)
        if existing == window_id:
            logger.debug(
                "Interactive mode already set for user=%d window=%s, skipping",
                user_id,
                window_id,
            )
            continue

        # Set interactive mode before rendering to prevent racing with terminal scraping
        set_interactive_mode(user_id, window_id, thread_id)

        # Wait briefly for Claude Code to render the UI in the terminal
        import asyncio

        await asyncio.sleep(0.3)

        handled = await handle_interactive_ui(bot, user_id, window_id, thread_id)
        if not handled:
            from .interactive_ui import clear_interactive_mode

            clear_interactive_mode(user_id, thread_id)


async def _handle_stop(event: HookEvent, bot: Bot) -> None:
    """Handle a Stop event — instant done detection."""
    from .status_polling import (
        _start_autoclose_timer,
        clear_seen_status,
    )
    from .message_queue import enqueue_status_update
    from .topic_emoji import update_topic_emoji

    users = _resolve_users_for_window_key(event.window_key)
    if not users:
        return

    import time

    now = time.monotonic()
    stop_reason = event.data.get("stop_reason", "")
    logger.info(
        "Hook stop: window_key=%s, stop_reason=%s",
        event.window_key,
        stop_reason,
    )

    for user_id, thread_id, window_id in users:
        clear_seen_status(window_id)
        chat_id = session_manager.resolve_chat_id(user_id, thread_id)
        display = session_manager.get_display_name(window_id)
        await update_topic_emoji(bot, chat_id, thread_id, "done", display)
        _start_autoclose_timer(user_id, thread_id, "done", now)
        await enqueue_status_update(bot, user_id, window_id, None, thread_id=thread_id)


# Track active subagents per window: window_id -> list of subagent descriptions
_active_subagents: dict[str, list[dict[str, str]]] = {}


def get_subagent_count(window_id: str) -> int:
    """Return the number of active subagents for a window."""
    return len(_active_subagents.get(window_id, []))


def clear_subagents(window_id: str) -> None:
    """Clear all subagent tracking for a window."""
    _active_subagents.pop(window_id, None)


async def _handle_subagent_start(event: HookEvent, bot: Bot) -> None:  # noqa: ARG001
    """Handle SubagentStart — track active subagent."""
    users = _resolve_users_for_window_key(event.window_key)
    if not users:
        return

    window_id = users[0][2]  # all users share the same window_id
    subagent_info = {
        "subagent_id": event.data.get("subagent_id", ""),
        "description": event.data.get("description", ""),
        "name": event.data.get("name", ""),
    }

    if window_id not in _active_subagents:
        _active_subagents[window_id] = []
    _active_subagents[window_id].append(subagent_info)

    count = len(_active_subagents[window_id])
    logger.info(
        "Subagent started: window=%s, count=%d, name=%s",
        window_id,
        count,
        subagent_info.get("name", ""),
    )


async def _handle_subagent_stop(event: HookEvent, bot: Bot) -> None:  # noqa: ARG001
    """Handle SubagentStop — remove subagent from tracking."""
    users = _resolve_users_for_window_key(event.window_key)
    if not users:
        return

    window_id = users[0][2]
    subagent_id = event.data.get("subagent_id", "")

    agents = _active_subagents.get(window_id, [])
    _active_subagents[window_id] = [
        a for a in agents if a.get("subagent_id") != subagent_id
    ]
    if not _active_subagents[window_id]:
        _active_subagents.pop(window_id, None)

    count = get_subagent_count(window_id)
    logger.info(
        "Subagent stopped: window=%s, remaining=%d, id=%s",
        window_id,
        count,
        subagent_id,
    )


async def dispatch_hook_event(event: HookEvent, bot: Bot) -> None:
    """Route hook events to appropriate handlers."""
    match event.event_type:
        case "Notification":
            await _handle_notification(event, bot)
        case "Stop":
            await _handle_stop(event, bot)
        case "SubagentStart":
            await _handle_subagent_start(event, bot)
        case "SubagentStop":
            await _handle_subagent_stop(event, bot)
        case _:
            logger.debug("Ignoring unknown hook event type: %s", event.event_type)
