"""Shared test helpers for ccgram unit tests."""

from unittest.mock import MagicMock

from ccgram.providers.base import AgentProvider, StatusUpdate


def make_mock_provider(
    *, has_status: bool = False, interactive: bool = False
) -> MagicMock:
    """Build a mock provider with parse_terminal_status configured."""
    provider = MagicMock(spec=AgentProvider)
    if has_status:
        status = StatusUpdate(
            raw_text="Working...",
            display_label="…working",
            is_interactive=interactive,
            ui_type="AskUserQuestion" if interactive else None,
        )
        provider.parse_terminal_status.return_value = status
    else:
        provider.parse_terminal_status.return_value = None
    return provider
