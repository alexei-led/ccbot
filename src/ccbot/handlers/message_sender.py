"""Safe message sending helpers with MarkdownV2 fallback.

Provides utility functions for sending Telegram messages with automatic
conversion to MarkdownV2 format and fallback to plain text on failure.

Functions:
  - rate_limit_send: Rate limiter to avoid Telegram flood control
  - rate_limit_send_message: Combined rate limiting + send with fallback
  - safe_reply: Reply with MarkdownV2, fallback to plain text
  - safe_edit: Edit message with MarkdownV2, fallback to plain text
  - safe_send: Send message with MarkdownV2, fallback to plain text
"""

import asyncio
import re
import structlog
import time
from typing import Any

from telegram import Bot, LinkPreviewOptions, Message
from telegram.error import BadRequest, RetryAfter, TelegramError

from ..markdown_v2 import convert_markdown

logger = structlog.get_logger()

# Disable link previews in all messages to reduce visual noise
NO_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Regex to strip MarkdownV2 escape sequences from plain text fallback.
# Matches a backslash followed by any MarkdownV2 special character.
_MDV2_STRIP_RE = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!\\])")
# Strip expandable blockquote syntax: leading ">" prefix and trailing "||"
_BLOCKQUOTE_PREFIX_RE = re.compile(r"^>", re.MULTILINE)
_BLOCKQUOTE_CLOSE_RE = re.compile(r"\|\|$", re.MULTILINE)


def _retry_after_seconds(exc: RetryAfter) -> int:
    """Extract retry delay from RetryAfter, handling both int and timedelta."""
    ra = exc.retry_after
    return ra if isinstance(ra, int) else int(ra.total_seconds())


def strip_mdv2(text: str) -> str:
    """Strip MarkdownV2 formatting artifacts for clean plain text fallback.

    Removes backslash escapes before special chars and blockquote syntax
    so the fallback message is readable without formatting artifacts.
    """
    text = _MDV2_STRIP_RE.sub(r"\1", text)
    text = _BLOCKQUOTE_CLOSE_RE.sub("", text)
    return _BLOCKQUOTE_PREFIX_RE.sub("", text)


# Rate limiting: last send time per chat to avoid Telegram flood control
_last_send_time: dict[int, float] = {}
MESSAGE_SEND_INTERVAL = 1.1  # seconds between messages to same chat


async def rate_limit_send(chat_id: int) -> None:
    """Wait if necessary to avoid Telegram flood control (max 1 msg/sec per chat)."""
    now = time.monotonic()
    if chat_id in _last_send_time:
        elapsed = now - _last_send_time[chat_id]
        if elapsed < MESSAGE_SEND_INTERVAL:
            await asyncio.sleep(MESSAGE_SEND_INTERVAL - elapsed)
    _last_send_time[chat_id] = time.monotonic()


async def _send_with_fallback(
    bot: Bot,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Message | None:
    """Send message with MarkdownV2, falling back to plain text on failure.

    Internal helper that handles the MarkdownV2 → plain text fallback pattern.
    Handles RetryAfter with a single sleep+retry instead of propagating.
    Returns the sent Message on success, None on failure.
    """
    kwargs.setdefault("link_preview_options", NO_LINK_PREVIEW)
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=convert_markdown(text),
            parse_mode="MarkdownV2",
            **kwargs,
        )
    except RetryAfter as e:
        await asyncio.sleep(_retry_after_seconds(e) + 1)
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=convert_markdown(text),
                parse_mode="MarkdownV2",
                **kwargs,
            )
        except TelegramError as e2:
            logger.warning("Failed to send message to %s after retry: %s", chat_id, e2)
            return None
    except TelegramError:
        try:
            return await bot.send_message(
                chat_id=chat_id, text=strip_mdv2(text), **kwargs
            )
        except RetryAfter as e:
            await asyncio.sleep(_retry_after_seconds(e) + 1)
            try:
                return await bot.send_message(
                    chat_id=chat_id, text=strip_mdv2(text), **kwargs
                )
            except TelegramError as e2:
                logger.warning(
                    "Failed to send message to %s after retry: %s", chat_id, e2
                )
                return None
        except TelegramError as e:
            logger.warning("Failed to send message to %s: %s", chat_id, e)
            return None


async def rate_limit_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Message | None:
    """Rate-limited send with MarkdownV2 fallback.

    Combines rate_limit_send() + _send_with_fallback() for convenience.
    The chat_id should be the group chat ID for forum topics, or the user ID
    for direct messages.  Use session_manager.resolve_chat_id() to obtain it.
    Returns the sent Message on success, None on failure.
    """
    await rate_limit_send(chat_id)
    return await _send_with_fallback(bot, chat_id, text, **kwargs)


async def safe_reply(message: Message, text: str, **kwargs: Any) -> Message | None:
    """Reply with MarkdownV2, falling back to plain text on failure.

    Returns None if the original message no longer exists (e.g. deleted topic).
    Handles RetryAfter with a single sleep+retry instead of propagating.
    """
    kwargs.setdefault("link_preview_options", NO_LINK_PREVIEW)
    try:
        return await message.reply_text(
            convert_markdown(text),
            parse_mode="MarkdownV2",
            **kwargs,
        )
    except BadRequest as exc:
        if "not found" in str(exc).lower():
            logger.warning("Cannot reply: original message gone (%s)", exc)
            return None
        raise
    except RetryAfter as e:
        await asyncio.sleep(_retry_after_seconds(e) + 1)
        try:
            return await message.reply_text(
                convert_markdown(text),
                parse_mode="MarkdownV2",
                **kwargs,
            )
        except TelegramError as e2:
            logger.warning("Failed to reply after retry: %s", e2)
            return None
    except TelegramError:
        try:
            return await message.reply_text(strip_mdv2(text), **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(_retry_after_seconds(e) + 1)
            try:
                return await message.reply_text(strip_mdv2(text), **kwargs)
            except TelegramError as e2:
                logger.warning("Failed to reply after retry: %s", e2)
                return None
        except TelegramError as e2:
            logger.warning("Failed to reply: %s", e2)
            return None


async def safe_edit(target: Any, text: str, **kwargs: Any) -> None:
    """Edit message with MarkdownV2, falling back to plain text on failure.

    Accepts either a CallbackQuery (edit_message_text) or a Message (edit_text).
    Handles RetryAfter with a single sleep+retry instead of propagating.
    """
    kwargs.setdefault("link_preview_options", NO_LINK_PREVIEW)
    # Message.edit_text vs CallbackQuery.edit_message_text
    edit_fn = (
        target.edit_text if isinstance(target, Message) else target.edit_message_text
    )
    try:
        await edit_fn(
            convert_markdown(text),
            parse_mode="MarkdownV2",
            **kwargs,
        )
    except RetryAfter as e:
        await asyncio.sleep(_retry_after_seconds(e) + 1)
        try:
            await edit_fn(
                convert_markdown(text),
                parse_mode="MarkdownV2",
                **kwargs,
            )
        except TelegramError as e2:
            logger.warning("Failed to edit message after retry: %s", e2)
    except TelegramError:
        try:
            await edit_fn(strip_mdv2(text), **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(_retry_after_seconds(e) + 1)
            try:
                await edit_fn(strip_mdv2(text), **kwargs)
            except TelegramError as e2:
                logger.warning("Failed to edit message after retry: %s", e2)
        except TelegramError as e:
            logger.warning("Failed to edit message: %s", e)


async def safe_send(
    bot: Bot,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
    **kwargs: Any,
) -> None:
    """Send message with MarkdownV2, falling back to plain text on failure.

    Handles RetryAfter with a single sleep+retry instead of propagating.
    """
    kwargs.setdefault("link_preview_options", NO_LINK_PREVIEW)
    if message_thread_id is not None:
        kwargs.setdefault("message_thread_id", message_thread_id)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=convert_markdown(text),
            parse_mode="MarkdownV2",
            **kwargs,
        )
    except RetryAfter as e:
        await asyncio.sleep(_retry_after_seconds(e) + 1)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=convert_markdown(text),
                parse_mode="MarkdownV2",
                **kwargs,
            )
        except TelegramError as e2:
            logger.warning("Failed to send message to %s after retry: %s", chat_id, e2)
    except TelegramError:
        try:
            await bot.send_message(chat_id=chat_id, text=strip_mdv2(text), **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(_retry_after_seconds(e) + 1)
            try:
                await bot.send_message(chat_id=chat_id, text=strip_mdv2(text), **kwargs)
            except TelegramError as e2:
                logger.warning(
                    "Failed to send message to %s after retry: %s", chat_id, e2
                )
        except TelegramError as e:
            logger.warning("Failed to send message to %s: %s", chat_id, e)
