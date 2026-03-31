"""Unified cleanup API for topic state.

Orchestrates topic teardown: dispatches registered cleanups via
TopicStateRegistry, then handles infrastructure and bot-specific async
cleanup that cannot be registered (log throttle, mailbox I/O, status
messages, interactive UI, user_data).

Functions:
  - clear_topic_state: Clean up all memory state for a specific topic
"""

from typing import Any

from telegram import Bot

from ..utils import log_throttle_reset
from .interactive_ui import clear_interactive_msg
from .message_queue import clear_status_msg_info, enqueue_status_update
from .user_state import PENDING_THREAD_ID, PENDING_THREAD_TEXT, VOICE_PENDING


async def clear_topic_state(
    user_id: int,
    thread_id: int,
    bot: Bot | None = None,
    user_data: dict[str, Any] | None = None,
    window_id: str | None = None,
    *,
    window_dead: bool = True,
) -> None:
    """Clear all memory state associated with a topic.

    Dispatches registered cleanups via TopicStateRegistry, then handles
    bot-specific async cleanup and infrastructure I/O that cannot be
    registered as simple callbacks.

    Args:
        window_dead: When False, skip qualified-scope cleanup (delivery state,
            peer metadata, spawn requests) because the tmux window is still
            alive.  Callers that keep the window running (topic close, /unbind)
            should pass ``window_dead=False``.
    """
    from ..config import config
    from ..thread_router import thread_router
    from ..window_resolver import is_foreign_window
    from .topic_state_registry import topic_state

    chat_id = thread_router.resolve_chat_id(user_id, thread_id)

    qualified_id: str | None = None
    if window_id and window_dead:
        qualified_id = (
            window_id
            if is_foreign_window(window_id)
            else f"{config.tmux_session_name}:{window_id}"
        )

    # Enqueue status-message delete BEFORE registry clears the message ID
    if bot is not None:
        await enqueue_status_update(
            bot, user_id, window_id or "", None, thread_id=thread_id
        )
    else:
        clear_status_msg_info(user_id, thread_id)

    # Registry dispatch — all module-specific per-topic/window/chat state
    topic_state.clear_all(
        user_id,
        thread_id,
        window_id=window_id,
        qualified_id=qualified_id,
        chat_id=chat_id,
    )

    # Infrastructure cleanup (formatted keys, file I/O — not registerable)
    log_throttle_reset(f"status-update:{user_id}:{thread_id}")
    if window_id:
        log_throttle_reset(f"topic-probe:{window_id}")
        from ..mailbox import Mailbox

        mb = Mailbox(config.mailbox_dir)
        if qualified_id is not None:
            mb.clear_inbox(qualified_id)

    await clear_interactive_msg(user_id, bot, thread_id)

    # user_data cleanup
    if user_data is not None and user_data.get(PENDING_THREAD_ID) == thread_id:
        user_data.pop(PENDING_THREAD_ID, None)
        user_data.pop(PENDING_THREAD_TEXT, None)

    if user_data is not None:
        voice_store: dict[tuple[int, int], str] = user_data.get(VOICE_PENDING, {})
        stale = [k for k in voice_store if k[0] == chat_id]
        for k in stale:
            voice_store.pop(k, None)
