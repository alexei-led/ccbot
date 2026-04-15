"""Shell prompt marker setup orchestrator.

Centralizes the decision of when and how to set up the shell prompt marker.
Five trigger sites (directory browser, window bind, transcript discovery,
shell command send, provider switch) delegate to `ensure_setup` which applies
a policy based on trigger type:

- auto: always set up (explicit shell topic creation)
- lazy: set up only if marker missing and user hasn't skipped
- external_bind: show offer keyboard if marker missing
- provider_switch: show offer keyboard (skip flag cleared on provider switch)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from .callback_registry import register
from .message_sender import safe_send

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

logger = structlog.get_logger()

Trigger = Literal["auto", "external_bind", "provider_switch", "lazy"]

CB_SHELL_SETUP = "sh:setup:"
CB_SHELL_SKIP = "sh:skip:"


@dataclass
class _OrchestratorState:
    skip_flag: bool = False
    was_offered: bool = False


_state: dict[str, _OrchestratorState] = {}


def _get_state(window_id: str) -> _OrchestratorState:
    return _state.setdefault(window_id, _OrchestratorState())


async def ensure_setup(
    window_id: str,
    trigger: Trigger,
    *,
    bot: Bot | None = None,
    chat_id: int = 0,
    thread_id: int = 0,
) -> None:
    """Apply prompt-marker setup policy for the given trigger type."""
    from ..providers.shell_infra import has_prompt_marker, setup_shell_prompt

    st = _get_state(window_id)

    if trigger == "auto":
        await setup_shell_prompt(window_id, clear=True)
        return

    if trigger == "lazy":
        if st.skip_flag:
            return
        if not await has_prompt_marker(window_id):
            await setup_shell_prompt(window_id, clear=False)
        return

    if trigger in ("external_bind", "provider_switch"):
        if await has_prompt_marker(window_id):
            return
        suppress = st.was_offered if trigger == "external_bind" else st.skip_flag
        if not suppress:
            await _show_offer_keyboard(
                window_id, bot=bot, chat_id=chat_id, thread_id=thread_id
            )
        return


async def accept_offer(window_id: str) -> None:
    """User chose 'Set up' -- run setup and record the offer."""
    from ..providers.shell_infra import setup_shell_prompt

    st = _get_state(window_id)
    st.was_offered = True
    await setup_shell_prompt(window_id, clear=False)


def record_skip(window_id: str) -> None:
    """User chose 'Skip' -- suppress further offers this session."""
    st = _get_state(window_id)
    st.skip_flag = True


def clear_state(window_id: str) -> None:
    """Remove orchestrator state for a window (cleanup on true window death)."""
    _state.pop(window_id, None)


def _reset_all_state() -> None:
    """Reset all orchestrator state (for testing)."""
    _state.clear()


async def _show_offer_keyboard(
    window_id: str,
    *,
    bot: Bot | None = None,
    chat_id: int = 0,
    thread_id: int = 0,
) -> None:
    """Show inline keyboard with Set up / Skip buttons."""
    st = _get_state(window_id)

    if not bot or not chat_id:
        from ..providers.shell_infra import setup_shell_prompt

        st.was_offered = True
        await setup_shell_prompt(window_id, clear=False)
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚙️ Set up", callback_data=f"{CB_SHELL_SETUP}{window_id}"
                ),
                InlineKeyboardButton(
                    "⏭ Skip", callback_data=f"{CB_SHELL_SKIP}{window_id}"
                ),
            ]
        ]
    )
    sent = await safe_send(
        bot,
        chat_id,
        "Shell prompt marker helps ccgram detect command output. Set up now?",
        message_thread_id=thread_id,
        reply_markup=keyboard,
    )
    if sent is not None:
        st.was_offered = True


@register(CB_SHELL_SETUP, CB_SHELL_SKIP)
async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    """Handle Set up / Skip button presses."""
    from .callback_helpers import user_owns_window

    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    is_setup = data.startswith(CB_SHELL_SETUP)
    window_id = data[len(CB_SHELL_SETUP) :] if is_setup else data[len(CB_SHELL_SKIP) :]

    user = query.from_user
    if user is None or not user_owns_window(user.id, window_id):
        await query.answer("Not your session", show_alert=True)
        return

    await query.answer()

    if is_setup:
        try:
            await accept_offer(window_id)
            await query.edit_message_text("✅ Shell prompt marker configured")
        except TelegramError as exc:
            logger.debug("shell_setup_edit_failed", error=str(exc))
        except OSError as exc:
            logger.warning(
                "shell_setup_tmux_error", window_id=window_id, error=str(exc)
            )
            with contextlib.suppress(TelegramError):
                await query.edit_message_text(
                    "❌ Setup failed — window may have closed"
                )
    else:
        record_skip(window_id)
        with contextlib.suppress(TelegramError):
            await query.edit_message_text("⏭ Skipped — send ! prefix for raw commands")
