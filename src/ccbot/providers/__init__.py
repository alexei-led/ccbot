"""Provider abstractions for multi-agent CLI backends.

Re-exports the protocol, event types, capability dataclass, and registry
so consumers can do ``from ccbot.providers import registry, ...``.
Also provides ``get_provider()`` for accessing the active provider singleton,
and ``resolve_capabilities()`` for lightweight CLI commands that don't
require Config (doctor, status).
"""

import logging
import os

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


_registered = False


def _ensure_registered() -> None:
    """Register all known providers into the global registry (once)."""
    global _registered
    if _registered:
        return
    from ccbot.providers.claude import ClaudeProvider
    from ccbot.providers.codex import CodexProvider
    from ccbot.providers.gemini import GeminiProvider

    registry.register("claude", ClaudeProvider)
    registry.register("codex", CodexProvider)
    registry.register("gemini", GeminiProvider)
    _registered = True


def get_provider() -> AgentProvider:
    """Return the active provider instance (lazy singleton).

    On first call, registers all providers into the global registry and
    resolves the provider name from config. Falls back to ``"claude"`` if
    the configured provider is unknown.
    """
    global _active
    if _active is None:
        _ensure_registered()

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


def _reset_provider() -> None:
    """Reset the cached provider singleton (for tests only)."""
    global _active, _registered
    _active = None
    _registered = False


def get_provider_for_window(window_id: str) -> AgentProvider:
    """Return the provider for a specific window, falling back to config default.

    Looks up provider_name from the window's WindowState. If empty or invalid,
    falls back to the global config provider (get_provider()).
    """
    _ensure_registered()

    from ccbot.session import session_manager

    state = session_manager.window_states.get(window_id)
    if state and state.provider_name and registry.is_valid(state.provider_name):
        return registry.get(state.provider_name)
    return get_provider()


def detect_provider_from_command(pane_current_command: str) -> str:
    """Detect provider name from a tmux pane's running process.

    Matches the basename of the command against known provider names
    to avoid false positives from paths containing provider names.
    Returns empty string for unrecognized or empty commands so callers
    can distinguish "no match" from a confident detection.
    """
    cmd = pane_current_command.strip().lower()
    if not cmd:
        return ""

    # Match basename only (first token) to avoid false positives
    # from paths like /home/claude/bin/vim
    basename = os.path.basename(cmd.split()[0])
    for name in ("claude", "codex", "gemini"):
        if basename == name or basename.startswith(name + "-"):
            return name

    return ""


def resolve_launch_command(provider_name: str) -> str:
    """Resolve the launch command for a provider, applying env var overrides.

    Resolution: ``CCBOT_<NAME>_COMMAND`` (e.g. ``CCBOT_CLAUDE_COMMAND``) if set,
    otherwise the provider's hardcoded default (``capabilities.launch_command``).
    """
    _ensure_registered()
    override = os.environ.get(f"CCBOT_{provider_name.upper()}_COMMAND")
    if override:
        return override
    try:
        return registry.get(provider_name).capabilities.launch_command
    except UnknownProviderError:
        return registry.get("claude").capabilities.launch_command


def resolve_capabilities(provider_name: str | None = None) -> ProviderCapabilities:
    """Resolve provider capabilities without requiring full Config.

    Reads ``CCBOT_PROVIDER`` from env when *provider_name* is not given.
    Falls back to ``"claude"`` for unknown providers.
    Suitable for lightweight CLI commands (doctor, status) that must not
    import Config (which requires TELEGRAM_BOT_TOKEN).
    """
    _ensure_registered()
    name = (
        provider_name
        if provider_name is not None
        else os.environ.get("CCBOT_PROVIDER", "claude")
    )
    try:
        return registry.get(name).capabilities
    except UnknownProviderError:
        return registry.get("claude").capabilities


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
    "detect_provider_from_command",
    "get_provider",
    "get_provider_for_window",
    "registry",
    "resolve_capabilities",
    "resolve_launch_command",
]
