"""Capability policy — unified feature-gating for provider capabilities.

Handlers call ``policy.can_hook``, ``policy.has_command("clear")``, etc.
instead of inspecting ``ProviderCapabilities`` fields directly.  This keeps
all feature-gating logic in one place so adding a new provider never requires
touching handler code.
"""

from typing import Literal

from ccbot.providers.base import AgentProvider, ProviderCapabilities


class CapabilityPolicy:
    """Answers "can this provider do X?" queries."""

    def __init__(self, capabilities: ProviderCapabilities) -> None:
        self._caps = capabilities

    @classmethod
    def from_provider(cls, provider: AgentProvider) -> CapabilityPolicy:
        """Build a policy from a live provider instance."""
        return cls(provider.capabilities)

    @property
    def can_hook(self) -> bool:
        return self._caps.supports_hook

    @property
    def can_resume(self) -> bool:
        return self._caps.supports_resume

    @property
    def can_continue(self) -> bool:
        return self._caps.supports_continue

    @property
    def has_structured_transcript(self) -> bool:
        return self._caps.supports_structured_transcript

    @property
    def transcript_format(self) -> Literal["jsonl", "plain"]:
        return self._caps.transcript_format

    def has_interactive_ui(self, ui_type: str) -> bool:
        """Check if provider's terminal output includes *ui_type* patterns."""
        return ui_type in self._caps.terminal_ui_patterns

    def has_command(self, command: str) -> bool:
        """Check if *command* is among the provider's built-in commands."""
        return command in self._caps.builtin_commands
