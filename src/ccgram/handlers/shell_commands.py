"""Shell command generation and approval flow.

Handles the NL description -> LLM -> suggested command -> approval keyboard
flow for the shell provider. Also handles raw command execution via ``!`` prefix.

Key components:
  - handle_shell_message: Route shell text (NL or raw ``!`` command)
  - handle_shell_callback: Dispatch approval keyboard callbacks
  - clear_shell_pending: Cleanup for topic deletion
"""

import structlog

from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..llm import get_completer
from ..llm.base import CommandResult
from ..session import session_manager
from ..tmux_manager import tmux_manager
from .callback_data import (
    CB_SHELL_CANCEL,
    CB_SHELL_CONFIRM_DANGER,
    CB_SHELL_EDIT,
    CB_SHELL_RUN,
)
from .message_sender import safe_edit, safe_reply, safe_send
from .message_queue import enqueue_status_update
from .shell_capture import start_shell_capture
from .status_polling import clear_probe_failures

logger = structlog.get_logger()

# Module-level pending command state: (chat_id, thread_id) -> (command, user_id)
_shell_pending: dict[tuple[int, int], tuple[str, int]] = {}


def clear_shell_pending(chat_id: int, thread_id: int) -> None:
    """Clear any pending shell command for this topic (used by cleanup)."""
    _shell_pending.pop((chat_id, thread_id), None)


async def handle_shell_message(
    bot: Bot,
    user_id: int,
    thread_id: int,
    window_id: str,
    text: str,
    message: Message | None = None,
) -> None:
    """Route shell provider messages: ``!`` prefix = raw, else = NL via LLM."""
    await enqueue_status_update(bot, user_id, window_id, None, thread_id)
    clear_probe_failures(window_id)

    # Clear any stale pending command for this topic
    chat_id = session_manager.resolve_chat_id(user_id, thread_id)
    clear_shell_pending(chat_id, thread_id)

    if text.startswith("!"):
        raw = text[1:].lstrip()
        if not raw:
            return
        await _execute_raw_command(bot, user_id, thread_id, window_id, raw)
        return

    try:
        completer = get_completer()
    except ValueError:
        logger.exception("LLM misconfigured, falling back to raw")
        completer = None

    if not completer:
        await _execute_raw_command(bot, user_id, thread_id, window_id, text)
        return

    # Gather context from tmux
    cwd = ""
    recent_output = ""
    window_state = session_manager.get_window_state(window_id)
    if window_state.cwd:
        cwd = window_state.cwd

    raw_pane = await tmux_manager.capture_pane(window_id)
    if raw_pane:
        lines = raw_pane.strip().splitlines()
        recent_output = "\n".join(lines[-10:])

    try:
        result = await completer.generate_command(
            text,
            cwd=cwd,
            recent_output=recent_output,
        )
    except RuntimeError:
        logger.exception("LLM command generation failed, falling back to raw")
        await _execute_raw_command(bot, user_id, thread_id, window_id, text)
        return

    await _show_command_approval(
        bot, chat_id, thread_id, window_id, result, user_id, message
    )


async def _execute_raw_command(
    bot: Bot,
    user_id: int,
    thread_id: int,
    window_id: str,
    command: str,
) -> None:
    """Send a raw command to the shell and start output capture."""
    success, err_message = await session_manager.send_to_window(window_id, command)
    if not success:
        chat_id = session_manager.resolve_chat_id(user_id, thread_id)
        await safe_send(
            bot, chat_id, f"\u274c {err_message}", message_thread_id=thread_id
        )
        return

    start_shell_capture(bot, user_id, thread_id, window_id)


async def _show_command_approval(
    bot: Bot,
    chat_id: int,
    thread_id: int,
    window_id: str,
    result: CommandResult,
    user_id: int,
    message: Message | None = None,
) -> None:
    """Show a suggested command with approval keyboard."""
    text = f"`{result.command}`"
    if result.explanation:
        text += f"\n{result.explanation}"
    if result.is_dangerous:
        text = f"\u26a0\ufe0f *Potentially dangerous*\n{text}"

    keyboard = _build_approval_keyboard(window_id, result.is_dangerous)
    if message:
        await safe_reply(message, text, reply_markup=keyboard)
    else:
        await safe_send(
            bot, chat_id, text, message_thread_id=thread_id, reply_markup=keyboard
        )
    _shell_pending[(chat_id, thread_id)] = (result.command, user_id)


def _build_approval_keyboard(
    window_id: str, is_dangerous: bool
) -> InlineKeyboardMarkup:
    """Build the command approval inline keyboard."""
    if is_dangerous:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "\u26a0 Confirm Run",
                        callback_data=f"{CB_SHELL_CONFIRM_DANGER}{window_id}",
                    ),
                    InlineKeyboardButton(
                        "\u2715 Cancel",
                        callback_data=f"{CB_SHELL_CANCEL}{window_id}",
                    ),
                ],
            ]
        )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "\u25b6 Run",
                    callback_data=f"{CB_SHELL_RUN}{window_id}",
                ),
                InlineKeyboardButton(
                    "\u270f Edit",
                    callback_data=f"{CB_SHELL_EDIT}{window_id}",
                ),
                InlineKeyboardButton(
                    "\u2715 Cancel",
                    callback_data=f"{CB_SHELL_CANCEL}{window_id}",
                ),
            ],
        ]
    )


async def handle_shell_callback(
    query: CallbackQuery,
    user_id: int,
    data: str,
    bot: Bot,
    thread_id: int | None,
) -> None:
    """Handle shell command approval callbacks."""
    if thread_id is None:
        await query.answer("No topic context")
        return

    chat_id = session_manager.resolve_chat_id(user_id, thread_id)
    pending = _shell_pending.get((chat_id, thread_id))

    if data.startswith(CB_SHELL_RUN) or data.startswith(CB_SHELL_CONFIRM_DANGER):
        await _cb_run(query, bot, user_id, thread_id, chat_id, pending)
    elif data.startswith(CB_SHELL_EDIT):
        await _cb_edit(query, chat_id, thread_id, pending)
    elif data.startswith(CB_SHELL_CANCEL):
        await _cb_cancel(query, chat_id, thread_id)


async def _cb_run(
    query: CallbackQuery,
    bot: Bot,
    user_id: int,
    thread_id: int,
    chat_id: int,
    pending: tuple[str, int] | None,
) -> None:
    """Handle Run / Confirm Danger callbacks."""
    await query.answer()
    if not pending:
        await safe_edit(query, "\u274c Command expired")
        return

    command, pending_user_id = pending
    if pending_user_id != user_id:
        await safe_edit(query, "\u274c Not your command")
        return

    # Use window from thread binding (authoritative), not callback data
    window_id = session_manager.get_window_for_thread(user_id, thread_id)
    if not window_id:
        clear_shell_pending(chat_id, thread_id)
        await safe_edit(query, "\u274c No session bound")
        return

    clear_shell_pending(chat_id, thread_id)
    await safe_edit(query, f"\u25b6 `{command}`")
    await _execute_raw_command(bot, user_id, thread_id, window_id, command)


async def _cb_edit(
    query: CallbackQuery,
    chat_id: int,
    thread_id: int,
    pending: tuple[str, int] | None,
) -> None:
    """Handle Edit callback."""
    await query.answer()
    clear_shell_pending(chat_id, thread_id)
    if pending:
        await safe_edit(
            query,
            f"\U0001f4cb Copy, edit, and send back:\n`{pending[0]}`",
        )
    else:
        await safe_edit(query, "\u274c Command expired")


async def _cb_cancel(
    query: CallbackQuery,
    chat_id: int,
    thread_id: int,
) -> None:
    """Handle Cancel callback."""
    await query.answer("Cancelled")
    clear_shell_pending(chat_id, thread_id)
    await safe_edit(query, "Cancelled")
