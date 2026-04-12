"""Unified cleanup API for topic state.

Orchestrates topic teardown: dispatches registered cleanups via
TopicStateRegistry, then handles infrastructure and bot-specific async
cleanup that cannot be registered (log throttle, mailbox I/O, status
messages, interactive UI, user_data).

Functions:
  - clear_topic_state: Clean up all memory state for a specific topic
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Bot

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

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
    from ..topic_state_registry import topic_state

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


async def unbind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disconnect a topic from its tmux window without killing the session."""
    from ..config import config
    from ..thread_router import thread_router
    from ..utils import handle_general_topic_message, is_general_topic
    from .callback_helpers import get_thread_id
    from .message_queue import enqueue_status_update
    from .message_sender import safe_reply

    user = update.effective_user
    if not user or not config.is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = get_thread_id(update)
    if thread_id is None:
        if (
            update.message
            and update.effective_chat
            and is_general_topic(update.message)
        ):
            await handle_general_topic_message(
                update.get_bot(), update.message, update.effective_chat.id
            )
        else:
            await safe_reply(update.message, "\u274c Use this command inside a topic.")
        return

    window_id = thread_router.get_window_for_thread(user.id, thread_id)
    if not window_id:
        await safe_reply(
            update.message, "\u274c This topic is not bound to any session."
        )
        return

    display = thread_router.get_display_name(window_id)
    await enqueue_status_update(context.bot, user.id, window_id, None, thread_id)
    await clear_topic_state(
        user.id,
        thread_id,
        context.bot,
        context.user_data,
        window_id=window_id,
        window_dead=False,
    )
    thread_router.unbind_thread(user.id, thread_id)
    await safe_reply(
        update.message,
        f"\u2702 Unbound from window `{display}`. The session is still running.\n"
        "Send a message in this topic to rebind or create a new session.",
    )
