"""Telegram bot handlers — the main UI layer of CCGram.

Registers all command/callback/message handlers and manages the bot lifecycle.
Each Telegram topic maps 1:1 to a tmux window (Claude session).

Core responsibilities:
  - Command handlers: /new (+ /start alias), /history, /sessions, /resume,
    /screenshot, /panes, /toolbar, /restore, plus forwarding unknown /commands to Claude Code via tmux.
  - Callback query handler: thin dispatcher routing to dedicated handler modules.
  - Topic-based routing: each named topic binds to one tmux window.
    Unbound topics trigger the directory browser to create a new session.
  - Topic lifecycle: closing a topic unbinds the window (kept alive for
    rebinding). Unbound windows are auto-killed after TTL by status polling.
    Unsupported content (images, stickers, etc.) is rejected with a warning.
  - Bot lifecycle management: post_init, post_shutdown, create_bot.

Key functions: create_bot(), handle_new_message().
"""

import os
import signal

import structlog
from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.error import BadRequest, Conflict, NetworkError
from telegram.ext import (
    AIORateLimiter,
    Application,
    ContextTypes,
    filters,
)

from . import bootstrap, window_query
from .config import config
from .cc_commands import discover_provider_commands
from .handlers.callback_helpers import get_thread_id as _get_thread_id
from .handlers.command_orchestration import (
    sync_scoped_menu_for_text_context as _sync_scoped_menu_for_text_context,
)
from .handlers.command_orchestration import (
    sync_scoped_provider_menu as _sync_scoped_provider_menu,
)
from .handlers.messaging_pipeline.message_sender import safe_reply
from .handlers.recovery import send_history
from .handlers.registry import register_all
from .handlers.text import handle_text_message
from .handlers.topics.directory_browser import clear_browse_state
from .providers import (
    get_provider_for_window,
)
from .session import session_manager
from .telegram_request import ResilientPollingHTTPXRequest
from .thread_router import thread_router
from .utils import handle_general_topic_message, is_general_topic

logger = structlog.get_logger()


def is_user_allowed(user_id: int | None) -> bool:
    return user_id is not None and config.is_user_allowed(user_id)


# Group filter: when CCBOT_GROUP_ID is set, only process updates from that group.
# filters.ALL is a no-op — single-instance backward compat.
_group_filter: filters.BaseFilter = (
    filters.Chat(chat_id=config.group_id) if config.group_id else filters.ALL
)


# --- Command handlers ---


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        if update.message:
            await safe_reply(update.message, "You are not authorized to use this bot.")
        return

    clear_browse_state(context.user_data)

    if update.message:
        await safe_reply(
            update.message,
            "\U0001f916 *Claude Code Monitor*\n\n"
            "Each topic is a session. Create a new topic to start.",
        )


async def history_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show message history for the active session or bound thread."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = _get_thread_id(update)
    window_id = thread_router.resolve_window_for_thread(user.id, thread_id)
    if not window_id:
        await safe_reply(update.message, "\u274c No session bound to this topic.")
        return

    provider = get_provider_for_window(
        window_id, provider_name=window_query.get_window_provider(window_id)
    )
    if not provider.capabilities.supports_structured_transcript:
        await safe_reply(update.message, "No transcript available for this provider.")
        return

    await send_history(update.message, window_id)


async def commands_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show provider-specific slash commands for the current topic."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = _get_thread_id(update)
    window_id = thread_router.resolve_window_for_thread(user.id, thread_id)
    if not window_id:
        await safe_reply(update.message, "\u274c No session bound to this topic.")
        return

    provider = get_provider_for_window(
        window_id, provider_name=window_query.get_window_provider(window_id)
    )
    await _sync_scoped_provider_menu(update.message, user.id, provider)
    commands = discover_provider_commands(provider)
    if not commands:
        await safe_reply(
            update.message,
            f"Provider: `{provider.capabilities.name}`\nNo discoverable commands.",
        )
        return

    lines = [f"Provider: `{provider.capabilities.name}`", "Supported commands:"]
    for cmd in sorted(commands, key=lambda c: c.telegram_name):
        if not cmd.telegram_name:
            continue
        original = cmd.name if cmd.name.startswith("/") else f"/{cmd.name}"
        lines.append(f"- `/{cmd.telegram_name}` \u2192 `{original}`")
    await safe_reply(update.message, "\n".join(lines))


async def toolbar_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show persistent action toolbar with inline keyboard buttons."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = _get_thread_id(update)
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

    from .handlers.toolbar import (
        build_toolbar_keyboard,
        seed_button_states,
    )

    provider_name = window_query.get_window_provider(window_id) or "claude"
    # Seed toggle-button labels with the actual current state so the
    # initial render shows "Edit"/"Plan"/"YOLO"/"Def" instead of "Mode".
    await seed_button_states(window_id)
    keyboard = build_toolbar_keyboard(window_id, provider_name)
    display = thread_router.get_display_name(window_id)
    await safe_reply(
        update.message,
        f"\U0001f39b `{display}` toolbar",
        reply_markup=keyboard,
    )


async def verbose_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle tool call batching for this topic."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = _get_thread_id(update)
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

    new_mode = session_manager.cycle_batch_mode(window_id)
    if new_mode == "batched":
        await safe_reply(
            update.message,
            "\u26a1 Tool calls will be *batched* into a single message.",
        )
    else:
        await safe_reply(
            update.message,
            "\U0001f4ac Tool calls will be sent *individually* (verbose mode).",
        )


async def toolcalls_command(
    update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Cycle tool-call visibility for this topic: default \u2192 shown \u2192 hidden \u2192 default."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    if not update.message:
        return

    thread_id = _get_thread_id(update)
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

    new_mode = session_manager.cycle_tool_call_visibility(window_id)
    if new_mode == "shown":
        await safe_reply(
            update.message,
            "\u26a1 Tool calls *shown* for this topic (overrides global default).",
        )
    elif new_mode == "hidden":
        await safe_reply(
            update.message,
            "\U0001f507 Tool calls *hidden* for this topic (overrides global default).",
        )
    else:
        # new_mode == "default" \u2014 describe the resolved global behavior
        from .config import config

        resolved = "hidden" if config.hide_tool_calls else "shown"
        await safe_reply(
            update.message,
            f"\U0001f504 Tool calls follow the global default (currently *{resolved}*).",
        )


async def inline_query_handler(
    update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Echo query text as a sendable inline result."""
    if not update.inline_query:
        return
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    text = update.inline_query.query.strip()
    if not text:
        await update.inline_query.answer([])
        return

    result = InlineQueryResultArticle(
        id="cmd",
        title=text,
        description="Tap to send",
        input_message_content=InputTextMessageContent(message_text=text),
    )
    await update.inline_query.answer([result], cache_time=0, is_personal=True)


async def unsupported_content_handler(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Reply to non-text messages (images, stickers, voice, etc.)."""
    if not update.message:
        return
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        return
    logger.debug("Unsupported content from user %d", user.id)
    # Omit "voice" from the list when whisper is configured (has its own handler)
    media_list = (
        "Stickers, voice, video" if not config.whisper_provider else "Stickers, video"
    )
    await safe_reply(
        update.message,
        f"\u26a0 {media_list}, and similar media are not supported. Use text, photos, or documents.",
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        if update.message:
            await safe_reply(update.message, "You are not authorized to use this bot.")
        return

    if not update.message or not update.message.text:
        return

    await _sync_scoped_menu_for_text_context(update, user.id)
    await handle_text_message(update, context)


# --- App lifecycle ---


async def post_init(application: Application) -> None:
    """Run the post_init wiring sequence — see ``bootstrap.bootstrap_application``."""
    await bootstrap.bootstrap_application(application)


async def _send_shutdown_notification(application: Application) -> None:
    """Send a shutdown notification to the General topic if a group is configured."""
    from .main import _shutdown_signal

    if not config.group_id:
        return

    sig = _shutdown_signal
    reason = f"Received {signal.Signals(sig).name}" if sig else "Clean exit"

    from . import __version__
    from telegram.error import TelegramError

    text = f"🔌 ccgram stopped — {reason} (v{__version__})"
    try:
        await application.bot.send_message(
            chat_id=config.group_id,
            text=text,
            message_thread_id=1,  # General topic
        )
    except (TelegramError, RuntimeError) as exc:
        logger.debug("Shutdown notification skipped: %s", exc)


async def post_stop(application: Application) -> None:
    """Send shutdown notification while HTTP transport is still alive."""
    await _send_shutdown_notification(application)


async def post_shutdown(_application: Application) -> None:
    """Tear down runtime state — see ``bootstrap.shutdown_runtime``."""
    await bootstrap.shutdown_runtime()


async def _error_handler(_update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bot-level errors from updater and handlers."""
    if isinstance(context.error, Conflict):
        logger.critical(
            "Another bot instance is polling with the same token. "
            "Shutting down to avoid conflicts."
        )
        os.kill(os.getpid(), signal.SIGINT)
        return
    if isinstance(context.error, BadRequest) and "too old" in str(context.error):
        logger.debug("Callback query expired (query too old)")
        return
    if isinstance(context.error, NetworkError) and not isinstance(
        context.error, BadRequest
    ):
        # PTB will retry automatically — not actionable; demoted from warning.
        logger.info("Transient network error (PTB will retry): %s", context.error)
        return
    logger.error("Unhandled bot error", exc_info=context.error)


def create_bot() -> Application:
    # Suppress PTBUserWarning about JobQueue (we intentionally don't use it for core tasks)
    import warnings

    warnings.filterwarnings("ignore", message=".*JobQueue.*", category=UserWarning)
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .rate_limiter(AIORateLimiter(max_retries=5))
        .request(ResilientPollingHTTPXRequest())
        .get_updates_request(ResilientPollingHTTPXRequest(connection_pool_size=1))
        .post_init(post_init)
        .post_stop(post_stop)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_error_handler(_error_handler)
    register_all(
        application,
        _group_filter,
        new_command=new_command,
        history_command=history_command,
        commands_command=commands_command,
        toolbar_command=toolbar_command,
        verbose_command=verbose_command,
        toolcalls_command=toolcalls_command,
        text_handler=text_handler,
        inline_query_handler=inline_query_handler,
        unsupported_content_handler=unsupported_content_handler,
    )

    return application
