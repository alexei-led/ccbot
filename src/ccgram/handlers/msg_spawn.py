"""Agent spawn request handling with Telegram approval.

Manages the Telegram approval/denial flow, window creation, and topic
auto-creation for spawn requests. Pure spawn request functions (data types,
rate limiting, file CRUD) live in ``spawn_request.py`` to avoid pulling in
config/handler dependencies from CLI context.

Uses callback_registry self-registration for inline keyboard dispatch.

Key components:
  - handle_spawn_approval: create window + topic on approval
  - handle_spawn_denial: reject and clean up
  - Telegram callback handlers for [Approve] / [Deny] buttons
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..providers import resolve_launch_command
from .. import window_query
from ..session import session_manager
from ..spawn_request import (
    SpawnRequest,
    SpawnResult,
    pop_pending,
    spawns_dir,
)
from ..tmux_manager import tmux_manager
from .callback_registry import register
from .message_sender import rate_limit_send_message

if TYPE_CHECKING:
    from telegram import Bot

logger = structlog.get_logger()

CB_SPAWN_APPROVE = "sp:ok:"
CB_SPAWN_DENY = "sp:no:"


async def handle_spawn_approval(
    request_id: str,
    bot: Bot,
    spawn_timeout: int = 300,
) -> SpawnResult | None:
    req = pop_pending(request_id)
    if req is None:
        logger.warning(
            "Spawn request %s not found (expired or already handled)", request_id
        )
        return None

    if req.is_expired(timeout=spawn_timeout):
        spawn_file = spawns_dir() / f"{request_id}.json"
        spawn_file.unlink(missing_ok=True)
        logger.info("Spawn request %s expired before approval", request_id)
        return None

    from ..config import config

    if window_query.window_count() >= config.msg_max_windows:
        spawn_file = spawns_dir() / f"{request_id}.json"
        spawn_file.unlink(missing_ok=True)
        logger.warning("Spawn request %s denied: max windows reached", request_id)
        return None

    launch_command = resolve_launch_command(req.provider)

    success, message, window_name, window_id = await tmux_manager.create_window(
        req.cwd,
        launch_command=launch_command,
    )
    if not success:
        logger.error("Spawn window creation failed: %s", message)
        # Leave file on disk; next scan_spawn_requests() cycle will
        # re-discover it and post a fresh approval keyboard.
        return None

    # Window created — remove the request file (point of no return)
    spawn_file = spawns_dir() / f"{request_id}.json"
    spawn_file.unlink(missing_ok=True)

    session_manager.set_window_provider(window_id, req.provider, cwd=req.cwd)

    try:
        await _create_topic_for_spawn(bot, window_id, window_name, req)
    except TelegramError:
        logger.warning(
            "Topic creation failed for spawned window %s, window still active",
            window_id,
            exc_info=True,
        )

    if req.provider == "claude":
        from ..msg_skill import ensure_skill_installed

        ensure_skill_installed(req.cwd)

    if req.prompt:
        prompt_text = req.prompt
        if req.context_file:
            prompt_text = f"{req.prompt} (context: {req.context_file})"
        await tmux_manager.send_keys(window_id, prompt_text)

    logger.info(
        "Spawned window %s (%s) for %s (provider=%s)",
        window_id,
        window_name,
        req.requester_window,
        req.provider,
    )

    return SpawnResult(window_id=window_id, window_name=window_name)


def handle_spawn_denial(request_id: str) -> None:
    req = pop_pending(request_id)
    if req is not None:
        logger.info("Spawn request %s denied", request_id)
    # Remove the file from disk
    spawn_file = spawns_dir() / f"{request_id}.json"
    spawn_file.unlink(missing_ok=True)


async def post_spawn_approval_keyboard(
    bot: Bot,
    requester_window: str,
    request: SpawnRequest,
) -> bool:
    """Post a Telegram approval keyboard for a spawn request.

    Returns True if the keyboard was successfully posted, False otherwise.
    """
    from .msg_telegram import resolve_topic

    topic = resolve_topic(requester_window)
    if topic is None:
        return False

    _, thread_id, chat_id, _ = topic

    text = (
        f"\U0001f680 Spawn request: {request.provider} at {request.cwd}\n"
        f"Prompt: {request.prompt}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve",
                    callback_data=f"{CB_SPAWN_APPROVE}{request.id}",
                ),
                InlineKeyboardButton(
                    "Deny",
                    callback_data=f"{CB_SPAWN_DENY}{request.id}",
                ),
            ]
        ]
    )

    result = await rate_limit_send_message(
        bot,
        chat_id,
        text,
        message_thread_id=thread_id,
        reply_markup=keyboard,
    )
    return result is not None


async def _create_topic_for_spawn(
    bot: Bot,
    window_id: str,
    window_name: str,
    req: SpawnRequest,
) -> None:
    from .msg_telegram import resolve_topic
    from .topic_orchestration import collect_target_chats, create_topic_in_chat

    target_chats = collect_target_chats(window_id)
    for chat_id in target_chats:
        await create_topic_in_chat(bot, chat_id, window_id, window_name)

    topic_info = resolve_topic(req.requester_window)
    if topic_info:
        _, thread_id, chat_id, _ = topic_info
        text = f"\u2705 Spawned {window_name} ({window_id}) for: {req.prompt}"
        await rate_limit_send_message(
            bot,
            chat_id,
            text,
            message_thread_id=thread_id,
            disable_notification=True,
        )


# ── Callback handlers for spawn approval buttons ───────��─────────────────


@register(CB_SPAWN_APPROVE, CB_SPAWN_DENY)
async def _handle_spawn_callback(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
) -> None:
    import contextlib as _contextlib

    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    data = query.data

    if data.startswith(CB_SPAWN_APPROVE):
        request_id = data[len(CB_SPAWN_APPROVE) :]
        bot = update.get_bot()
        try:
            from ..config import config as _cfg

            result = await handle_spawn_approval(
                request_id, bot, spawn_timeout=_cfg.msg_spawn_timeout
            )
        except TelegramError:
            logger.warning("Spawn approval failed for %s", request_id, exc_info=True)
            result = None
        if result:
            text = f"\u2705 Spawned: {result.window_name} ({result.window_id})"
        else:
            text = "\u274c Spawn failed (request expired or window creation error)"
        with _contextlib.suppress(TelegramError):
            await query.edit_message_text(text)

    elif data.startswith(CB_SPAWN_DENY):
        request_id = data[len(CB_SPAWN_DENY) :]
        handle_spawn_denial(request_id)
        with _contextlib.suppress(TelegramError):
            await query.edit_message_text("\u274c Spawn request denied")
