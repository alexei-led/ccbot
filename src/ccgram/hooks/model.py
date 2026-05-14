"""Normalized hook event types shared by provider adapters.

Adapters convert provider-specific stdin payloads into a small safe event model.
The model intentionally excludes raw prompts, tool inputs, tool outputs, and LLM
messages because hook payloads can contain secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ProviderName: TypeAlias = Literal["claude", "pi", "codex", "gemini"]


@dataclass(frozen=True, slots=True)
class NormalizedHookEvent:
    """Provider-neutral hook event safe for ccgram state files."""

    provider_name: ProviderName
    native_event_name: str
    canonical_event_name: str
    session_id: str
    cwd: Path | None
    transcript_path: Path | None
    data: dict[str, JsonValue]


class HookAdapter(Protocol):
    """Provider-specific hook payload normalizer.

    ``event_types`` covers what the adapter knows how to normalize (a superset).
    ``installable_events`` covers what ccgram actually installs in user config —
    a subset chosen for the lifecycle signals ccgram acts on. The two differ on
    purpose; conflating them would install hooks for events the bot ignores.
    """

    provider_name: ProviderName
    event_types: tuple[str, ...]
    installable_events: tuple[str, ...]
    install_managed_by_ccgram: bool

    def normalize(self, payload: dict[str, object]) -> NormalizedHookEvent | None:
        """Return a safe normalized event, or None for invalid/unhandled input."""
        ...
