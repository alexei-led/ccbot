"""Root conftest — sets env vars BEFORE any ccgram module is imported.

The config.py module-level singleton requires TELEGRAM_BOT_TOKEN and
ALLOWED_USERS at import time, so these must be set before pytest
discovers any test that transitively imports ccgram.
"""

import contextlib
import os
import tempfile

import pytest

# Force-set (not setdefault) to prevent real env vars from leaking into tests
os.environ["TELEGRAM_BOT_TOKEN"] = "test:0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
os.environ["ALLOWED_USERS"] = "12345"
os.environ["CCGRAM_DIR"] = tempfile.mkdtemp(prefix="ccgram-test-")


@pytest.fixture(autouse=True)
def _clear_window_store():
    from ccgram.claude_task_state import claude_task_state
    from ccgram.window_state_store import get_window_store

    def _clear() -> None:
        # SessionManager hasn't been built in this test — nothing to clear.
        with contextlib.suppress(RuntimeError):
            get_window_store().window_states.clear()

    claude_task_state.reset()
    _clear()
    yield
    claude_task_state.reset()
    _clear()
