"""Shell subpackage — NL→command flow, output relay, prompt-marker setup.

Bundles the modules that implement the shell provider's Telegram surface:
``shell_commands`` (NL→LLM→approval keyboard, raw ``!`` execution,
``handle_shell_message`` / ``handle_shell_callback``), ``shell_capture``
(passive output relay, exit-code reactions, ``register_approval_callback``
indirection that breaks the runtime ``shell_capture ↔ shell_commands``
cycle), ``shell_context`` (LLM context gathering and secret redaction),
and ``shell_prompt_orchestrator`` (centralised prompt-marker setup
policy across the five trigger sites).

Public surface re-exported here is the entry point for ``bot.py`` and
the rest of ``handlers/``; internals stay in the per-module files.
"""

from .shell_capture import (
    check_passive_shell_output,
    clear_shell_monitor_state,
    mark_telegram_command,
    register_approval_callback,
    reset_shell_monitor_state,
    strip_terminal_glyphs,
)
from .shell_commands import (
    clear_shell_pending,
    handle_shell_callback,
    handle_shell_message,
    has_shell_pending,
    show_command_approval,
)
from .shell_context import (
    gather_llm_context,
    redact_for_llm,
)
from .shell_prompt_orchestrator import (
    CB_SHELL_SETUP,
    CB_SHELL_SKIP,
    accept_offer,
    clear_state,
    ensure_setup,
    record_skip,
)

__all__ = [
    "CB_SHELL_SETUP",
    "CB_SHELL_SKIP",
    "accept_offer",
    "check_passive_shell_output",
    "clear_shell_monitor_state",
    "clear_shell_pending",
    "clear_state",
    "ensure_setup",
    "gather_llm_context",
    "handle_shell_callback",
    "handle_shell_message",
    "has_shell_pending",
    "mark_telegram_command",
    "record_skip",
    "redact_for_llm",
    "register_approval_callback",
    "reset_shell_monitor_state",
    "show_command_approval",
    "strip_terminal_glyphs",
]
