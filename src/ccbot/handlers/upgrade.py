"""Upgrade handler — /upgrade command for self-updating ccbot via uv.

Runs `uv tool upgrade ccbot`, reports the result, and restarts the bot
process via os.execv() if an upgrade was installed. Existing tmux windows
are untouched since only the bot process restarts.

Key function: upgrade_command().
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from .message_sender import safe_edit, safe_reply

logger = logging.getLogger(__name__)

_UPGRADE_TIMEOUT = 60


async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /upgrade — upgrade ccbot via uv and restart if needed."""
    user = update.effective_user
    if not user or not update.message:
        return
    if not config.is_user_allowed(user.id):
        await safe_reply(update.message, "You are not authorized to use this bot.")
        return

    from .. import __version__

    msg = await update.message.reply_text("\u23f3 Checking for updates...")

    try:
        proc = await asyncio.create_subprocess_exec(
            "uv",
            "tool",
            "upgrade",
            "ccbot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_UPGRADE_TIMEOUT
        )
    except FileNotFoundError:
        await safe_edit(
            msg, "\u274c `uv` not found. Is ccbot installed via `uv tool install`?"
        )
        return
    except TimeoutError:
        await safe_edit(msg, "\u274c Upgrade timed out after 60s.")
        return
    except OSError as exc:
        await safe_edit(msg, f"\u274c Upgrade failed: {exc}")
        return

    output = (stdout or b"").decode() + (stderr or b"").decode()

    if proc.returncode != 0:
        detail = output.strip()[:200] if output.strip() else "unknown error"
        await safe_edit(
            msg, f"\u274c Upgrade failed (exit {proc.returncode}):\n`{detail}`"
        )
        return

    # Detect whether an upgrade actually happened
    # uv tool upgrade output: "Nothing to upgrade" when up-to-date,
    # or "Upgraded ccbot ..." when upgraded
    if "nothing to upgrade" in output.lower():
        await safe_edit(msg, f"\u2705 Already up to date (v{__version__}).")
        return

    # Try to extract new version from uv tool list
    new_version = await _get_installed_version()
    version_text = f"v{new_version}" if new_version else "new version"

    await safe_edit(msg, f"\u2705 Upgraded to {version_text}. Restarting...")
    logger.info(
        "Upgrade complete (%s -> %s), scheduling restart", __version__, version_text
    )

    # Set restart flag and stop the application
    from .. import main as main_module

    main_module._restart_requested = True

    # Brief delay so the edit message reaches Telegram
    await asyncio.sleep(0.5)
    context.application.stop_running()


async def _get_installed_version() -> str | None:
    """Query uv tool list to get the currently installed ccbot version."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "uv",
            "tool",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except OSError:
        return None

    for line in (stdout or b"").decode().splitlines():
        if line.startswith("ccbot "):
            # Format: "ccbot v0.2.1" or "ccbot 0.2.1"
            version = line.split(None, 1)[1].lstrip("v")
            return version
    return None
