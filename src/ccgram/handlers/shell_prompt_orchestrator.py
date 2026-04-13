"""Shell prompt marker setup orchestrator.

Centralizes the decision of when and how to set up the shell prompt marker.
Five trigger sites (directory browser, window bind, transcript discovery,
shell command send, provider switch) delegate to `ensure_setup` which applies
a policy based on trigger type:

- auto: always set up (explicit shell topic creation)
- lazy: set up only if marker missing and user hasn't skipped
- external_bind: show offer keyboard if marker missing
- provider_switch: show offer keyboard, re-offer after skip cleared
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..topic_state_registry import topic_state

Trigger = Literal["auto", "external_bind", "provider_switch", "lazy"]


@dataclass
class _OrchestratorState:
    skip_flag: bool = False
    was_offered: bool = False


_state: dict[str, _OrchestratorState] = {}


def _get_state(window_id: str) -> _OrchestratorState:
    if window_id not in _state:
        _state[window_id] = _OrchestratorState()
    return _state[window_id]


async def ensure_setup(window_id: str, trigger: Trigger) -> None:
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

    if trigger == "external_bind":
        if await has_prompt_marker(window_id):
            return
        if not st.was_offered:
            await _show_offer_keyboard(window_id)
        return

    if trigger == "provider_switch":
        if not st.skip_flag:
            await _show_offer_keyboard(window_id)
        return


async def accept_offer(window_id: str) -> None:
    """User chose 'Set up' — run setup and record the offer."""
    from ..providers.shell_infra import setup_shell_prompt

    st = _get_state(window_id)
    st.was_offered = True
    await setup_shell_prompt(window_id, clear=False)


def record_skip(window_id: str) -> None:
    """User chose 'Skip' — suppress further offers this session."""
    st = _get_state(window_id)
    st.skip_flag = True


def clear_state(window_id: str) -> None:
    """Remove orchestrator state for a window (cleanup on topic close)."""
    _state.pop(window_id, None)


topic_state.register_bound("window", clear_state)


async def _show_offer_keyboard(window_id: str) -> None:
    """Show inline keyboard with Set up / Skip buttons.

    This is a placeholder that will be wired to Telegram in Task 7
    when the trigger sites are migrated to use this orchestrator.
    """
    from ..providers.shell_infra import setup_shell_prompt

    st = _get_state(window_id)
    st.was_offered = True
    await setup_shell_prompt(window_id, clear=False)
