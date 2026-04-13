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

import asyncio
import contextlib
import structlog
import os
import signal

from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.error import BadRequest, Conflict, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .cc_commands import (
    discover_provider_commands,
    register_commands,
)
from .providers import (
    get_provider,
    get_provider_for_window,
)
from .config import config
from .handlers.topic_orchestration import (
    adopt_unbound_windows as _adopt_unbound_windows,
    handle_new_window as _handle_new_window,
)
from .handlers.command_orchestration import (
    forward_command_handler,
    sync_scoped_menu_for_text_context as _sync_scoped_menu_for_text_context,
    sync_scoped_provider_menu as _sync_scoped_provider_menu,
    setup_menu_refresh_job,
)
from .handlers.callback_helpers import get_thread_id as _get_thread_id
from .handlers.callback_registry import dispatch as _dispatch_callback
from .handlers.callback_registry import load_handlers as _load_callback_handlers
from .handlers.restore_command import restore_command
from .handlers.resume_command import resume_command
from .handlers.send_command import send_command
from .handlers.directory_browser import clear_browse_state
from .handlers.cleanup import unbind_command
from .handlers.command_history import recall_command
from .handlers.message_routing import handle_new_message
from .handlers.screenshot_callbacks import panes_command, screenshot_command
from .handlers.topic_lifecycle import topic_closed_handler, topic_edited_handler
from .handlers.history import send_history
from .handlers.sessions_dashboard import sessions_command
from .handlers.sync_command import sync_command
from .handlers.upgrade import upgrade_command
from .handlers.message_queue import (
    shutdown_workers,
)
from .handlers.message_sender import safe_reply
from .handlers.polling_coordinator import status_poll_loop
from .handlers.file_handler import handle_document_message, handle_photo_message
from .handlers.voice_handler import handle_voice_message
from .handlers.text_handler import handle_text_message
from .session import session_manager
from .session_monitor import NewMessage, NewWindowEvent, SessionMonitor
from .thread_router import thread_router
from .telegram_request import ResilientPollingHTTPXRequest
from .utils import handle_general_topic_message, is_general_topic, task_done_callback

logger = structlog.get_logger()

# Error keyword pattern for errors_only notification mode (word boundaries)

# Session monitor instance
session_monitor: SessionMonitor | None = None

# Status polling task
_status_poll_task: asyncio.Task | None = None


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

    provider = get_provider_for_window(window_id)
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

    provider = get_provider_for_window(window_id)
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

    from .handlers.toolbar_callbacks import (
        build_toolbar_keyboard,
        seed_button_states,
    )

    ws = session_manager.get_window_state(window_id)
    provider_name = ws.provider_name if ws and ws.provider_name else "claude"
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


def _global_exception_handler(
    _loop: asyncio.AbstractEventLoop, context: dict[str, object]
) -> None:
    """Last-resort handler for uncaught exceptions in asyncio tasks."""
    exc = context.get("exception")
    msg = context.get("message", "Unhandled exception in event loop")
    if isinstance(exc, BaseException):
        logger.error(
            "asyncio exception handler: %s",
            msg,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        logger.error("asyncio exception handler: %s", msg)


async def post_init(application: Application) -> None:
    global session_monitor, _status_poll_task

    # Install global asyncio exception handler as safety net
    asyncio.get_running_loop().set_exception_handler(_global_exception_handler)

    default_provider = get_provider()
    try:
        await register_commands(application.bot, provider=default_provider)
    except TelegramError:
        logger.warning("Failed to register bot commands at startup, will retry later")
    setup_menu_refresh_job(application)

    # Re-resolve stale window IDs from persisted state against live tmux windows
    await session_manager.resolve_stale_ids()

    await _adopt_unbound_windows(application.bot)

    # Warn if Claude Code hooks are not installed (provider-aware, non-blocking)
    provider = get_provider()
    if provider.capabilities.supports_hook:
        from .hook import _claude_settings_file, get_installed_events

        settings_file = _claude_settings_file()
        import json

        if settings_file.exists():
            try:
                settings = json.loads(settings_file.read_text())
                events = get_installed_events(settings)
                missing = [e for e, ok in events.items() if not ok]
                if missing:
                    logger.warning(
                        "Claude Code hooks incomplete — %d missing: %s. "
                        "Run: ccgram hook --install",
                        len(missing),
                        ", ".join(missing),
                    )
            except (json.JSONDecodeError, OSError):  # fmt: skip
                logger.warning(
                    "Claude Code hooks not installed. Run: ccgram hook --install"
                )
        else:
            logger.warning(
                "Claude Code hooks not installed (%s missing). "
                "Run: ccgram hook --install",
                settings_file,
            )

    monitor = SessionMonitor()
    # Expose to other modules (status_polling activity heuristic)
    from ccgram.session_monitor import set_active_monitor

    set_active_monitor(monitor)

    async def message_callback(msg: NewMessage) -> None:
        await handle_new_message(msg, application.bot)

    monitor.set_message_callback(message_callback)

    async def new_window_callback(event: NewWindowEvent) -> None:
        await _handle_new_window(event, application.bot)

    monitor.set_new_window_callback(new_window_callback)

    # Wire hook event dispatcher for structured Claude Code events
    from ccgram.providers.base import HookEvent
    from ccgram.handlers.hook_events import dispatch_hook_event

    async def hook_event_callback(event: HookEvent) -> None:
        await dispatch_hook_event(event, application.bot)

    monitor.set_hook_event_callback(hook_event_callback)
    monitor.start()
    session_monitor = monitor
    logger.info("Session monitor started")

    # Start status polling task (routed through PTB error handler)
    _status_poll_task = asyncio.create_task(status_poll_loop(application.bot))
    _status_poll_task.add_done_callback(task_done_callback)
    logger.info("Status polling task started")


async def _send_shutdown_notification(application: Application) -> None:
    """Send a shutdown notification to the General topic if a group is configured."""
    from .main import _shutdown_signal

    if not config.group_id:
        return

    sig = _shutdown_signal
    reason = f"Received {signal.Signals(sig).name}" if sig else "Clean exit"

    from . import __version__

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
    global _status_poll_task

    # Stop status polling
    if _status_poll_task:
        _status_poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _status_poll_task
        _status_poll_task = None
        logger.info("Status polling stopped")

    # Stop session monitor first (it may enqueue messages to workers)
    if session_monitor:
        session_monitor.stop()
        logger.info("Session monitor stopped")

    # Stop all queue workers after monitor is stopped
    await shutdown_workers()

    # Sweep expired mailbox messages before final state flush
    from .mailbox import Mailbox

    Mailbox(config.mailbox_dir).sweep()

    # Flush debounced state to disk AFTER workers/monitor stop (captures final mutations)
    session_manager.flush_state()


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
        logger.warning("Transient network error (PTB will retry): %s", context.error)
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
    application.add_handler(CommandHandler("new", new_command, filters=_group_filter))
    application.add_handler(
        CommandHandler("start", new_command, filters=_group_filter)  # compat alias
    )
    application.add_handler(
        CommandHandler("history", history_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("commands", commands_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("sessions", sessions_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("resume", resume_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("unbind", unbind_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("upgrade", upgrade_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("recall", recall_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("screenshot", screenshot_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("panes", panes_command, filters=_group_filter)
    )
    application.add_handler(CommandHandler("sync", sync_command, filters=_group_filter))
    application.add_handler(
        CommandHandler("toolbar", toolbar_command, filters=_group_filter)
    )
    application.add_handler(CommandHandler("send", send_command, filters=_group_filter))
    application.add_handler(
        CommandHandler("verbose", verbose_command, filters=_group_filter)
    )
    application.add_handler(
        CommandHandler("restore", restore_command, filters=_group_filter)
    )
    _load_callback_handlers()
    application.add_handler(CallbackQueryHandler(_dispatch_callback))
    # Topic closed event — unbind window (kept alive for rebinding)
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_CLOSED & _group_filter,
            topic_closed_handler,
        )
    )
    # Topic renamed event — sync name to tmux window
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_EDITED & _group_filter,
            topic_edited_handler,
        )
    )
    # Forward any other /command to the topic's provider CLI
    application.add_handler(
        MessageHandler(filters.COMMAND & _group_filter, forward_command_handler)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & _group_filter, text_handler)
    )
    # Photos
    application.add_handler(
        MessageHandler(filters.PHOTO & _group_filter, handle_photo_message)
    )
    # Documents
    application.add_handler(
        MessageHandler(filters.Document.ALL & _group_filter, handle_document_message)
    )
    # Voice messages (transcription when configured)
    application.add_handler(
        MessageHandler(filters.VOICE & _group_filter, handle_voice_message)
    )
    # Catch-all: unsupported content (stickers, voice, video, etc.)
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND
            & ~filters.TEXT
            & ~filters.PHOTO
            & ~filters.Document.ALL
            & ~filters.VOICE
            & ~filters.StatusUpdate.ALL
            & _group_filter,
            unsupported_content_handler,
        )
    )
    # Inline query handler (serves switch_inline_query_current_chat from history buttons)
    application.add_handler(InlineQueryHandler(inline_query_handler))

    return application
