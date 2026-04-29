"""Handler test fixtures — short-circuit slow real waits."""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _instant_session_map_wait(monkeypatch):
    from ccgram.session_map import session_map_sync

    monkeypatch.setattr(
        session_map_sync,
        "wait_for_session_map_entry",
        AsyncMock(return_value=True),
    )


@pytest.fixture(autouse=True)
def _disable_send_rate_limit(monkeypatch):
    """Zero out MESSAGE_SEND_INTERVAL so back-to-back sends don't sleep.

    Tests in TestRateLimitSend re-patch the interval inline when they
    need to assert on the wait calculation.
    """
    monkeypatch.setattr(
        "ccgram.handlers.messaging_pipeline.message_sender.MESSAGE_SEND_INTERVAL", 0
    )


@pytest.fixture(autouse=True)
def _zero_command_orchestration_delays(monkeypatch):
    """Collapse command-orchestration probe / fallback delays."""
    monkeypatch.setattr(
        "ccgram.handlers.command_orchestration._CODEX_STATUS_FALLBACK_DELAY_SECONDS",
        0,
    )
    monkeypatch.setattr(
        "ccgram.handlers.command_orchestration._COMMAND_ERROR_PROBE_DELAY_SECONDS",
        0,
    )
