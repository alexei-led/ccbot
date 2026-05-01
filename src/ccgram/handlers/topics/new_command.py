"""``/new`` (and ``/start`` alias) handler — welcome message for the bot.

Authorization is checked first. On unauthorized access an explanatory
reply is sent. Any in-progress directory-browser state on the user is
cleared so a stale picker does not interfere with the next interaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from telegram import Update
from ...config import config
from ..messaging_pipeline.message_sender import safe_reply
from .directory_browser import clear_browse_state

if TYPE_CHECKING:
    from telegram.ext import ContextTypes


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not config.is_user_allowed(user.id):
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
