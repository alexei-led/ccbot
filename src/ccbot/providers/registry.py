"""Provider registry — maps provider names to classes, instantiates on demand.

The module-level ``registry`` singleton starts empty; provider modules
call ``registry.register()`` at import time.  Handlers call
``registry.get(name)`` to obtain a provider instance and
``registry.available()`` to list registered names.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccbot.providers.base import AgentProvider

logger = logging.getLogger(__name__)


class UnknownProviderError(KeyError):
    """Raised when requesting a provider name that is not registered."""


class ProviderRegistry:
    """Maps provider name strings to AgentProvider classes."""

    def __init__(self) -> None:
        self._providers: dict[str, type[AgentProvider]] = {}

    def register(self, name: str, provider_cls: type[AgentProvider]) -> None:
        """Register a provider class under *name* (overwrites silently)."""
        self._providers[name] = provider_cls
        logger.debug("Registered provider %r", name)

    def get(self, name: str) -> AgentProvider:
        """Instantiate and return the provider registered under *name*.

        Raises ``UnknownProviderError`` if *name* is not registered.
        """
        cls = self._providers.get(name)
        if cls is None:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise UnknownProviderError(
                f"Unknown provider {name!r}. Available: {available}"
            )
        return cls()

    def available(self) -> list[str]:
        """Return sorted list of registered provider names."""
        return sorted(self._providers)


registry = ProviderRegistry()
