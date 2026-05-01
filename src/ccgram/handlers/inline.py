"""Top-level inline-query and unsupported-content handlers.

These two callbacks live at the root of ``handlers/`` because they have
no natural feature subpackage:

- ``inline_query_handler`` echoes the user's typed text as a sendable
  inline result so any client can dispatch a queued message even when
  not yet inside a topic.
- ``unsupported_content_handler`` replies to media types the bot does
  not consume (stickers, video, etc.) with an actionable hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import structlog
from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from ..config import config
from .messaging_pipeline.message_sender import safe_reply

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = structlog.get_logger()


async def inline_query_handler(
    update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Echo query text as a sendable inline result."""
    if not update.inline_query:
        return
    user = update.effective_user
    if not user or not config.is_user_allowed(user.id):
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
    if not user or not config.is_user_allowed(user.id):
        return
    logger.debug("Unsupported content from user %d", user.id)
    # Omit "voice" from the list when whisper is configured (has its own handler)
    media_list = (
        "Stickers, voice, video" if not config.whisper_provider else "Stickers, video"
    )
    await safe_reply(
        update.message,
        f"⚠ {media_list}, and similar media are not supported. Use text, photos, or documents.",
    )
