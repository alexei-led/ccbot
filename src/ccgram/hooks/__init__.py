"""Provider-aware hook support for agent lifecycle events.

Defines normalized hook contracts and provider adapters used by the
``ccgram.hook`` CLI wrapper. Runtime code must stay import-light because hook
commands execute inside agent panes without bot configuration.
"""

from .adapters import (
    detect_provider_from_payload,
    get_hook_adapter,
)
from .model import NormalizedHookEvent, ProviderName

__all__ = [
    "NormalizedHookEvent",
    "ProviderName",
    "detect_provider_from_payload",
    "get_hook_adapter",
]
