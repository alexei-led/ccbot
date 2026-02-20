"""Provider abstractions for multi-agent CLI backends.

Re-exports the protocol, event types, capability dataclass, and registry
so consumers can do ``from ccbot.providers import registry, ...``.
Also provides ``get_provider()`` for accessing the active provider singleton.
"""

import logging

from ccbot.providers.base import (
    EXPANDABLE_QUOTE_END,
    EXPANDABLE_QUOTE_START,
    AgentMessage,
    AgentProvider,
    DiscoveredCommand,
    ProviderCapabilities,
    SessionStartEvent,
    StatusUpdate,
)
from ccbot.providers.registry import ProviderRegistry, UnknownProviderError, registry

logger = logging.getLogger(__name__)

# Singleton cache
_active: AgentProvider | None = None


def get_provider() -> AgentProvider:
    """Return the active provider instance (lazy singleton).

    On first call, registers ClaudeProvider into the global registry and
    resolves the provider name from config. Falls back to ``"claude"`` if
    the configured provider is unknown.
    """
    global _active
    if _active is None:
        from ccbot.providers.claude import ClaudeProvider

        registry.register("claude", ClaudeProvider)

        from ccbot.config import config

        try:
            _active = registry.get(config.provider_name)
        except UnknownProviderError:
            logger.warning(
                "Unknown provider %r, falling back to 'claude'",
                config.provider_name,
            )
            _active = registry.get("claude")
    return _active


__all__ = [
    "EXPANDABLE_QUOTE_END",
    "EXPANDABLE_QUOTE_START",
    "AgentMessage",
    "AgentProvider",
    "DiscoveredCommand",
    "ProviderCapabilities",
    "ProviderRegistry",
    "SessionStartEvent",
    "StatusUpdate",
    "UnknownProviderError",
    "get_provider",
    "registry",
]
