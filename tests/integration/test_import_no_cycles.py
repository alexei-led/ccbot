"""Verify ``import ccgram`` and submodules succeed in a clean interpreter.

Regression guard for round-4 modularity decouple (F6.2): hoisting in-function
imports to module level can introduce import cycles that don't surface in the
in-process test suite (other tests warm caches first). A fresh subprocess
catches a cycle that the in-process suite would miss.
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


_MODULES = [
    "ccgram",
    "ccgram.bot",
    "ccgram.bootstrap",
    "ccgram.telegram_client",
    "ccgram.session",
    "ccgram.session_map",
    "ccgram.session_monitor",
    "ccgram.tmux_manager",
    "ccgram.handlers",
    "ccgram.handlers.callback_registry",
    "ccgram.handlers.registry",
    "ccgram.handlers.cleanup",
    "ccgram.handlers.command_history",
    "ccgram.handlers.command_orchestration",
    "ccgram.handlers.hook_events",
    "ccgram.handlers.inline",
    "ccgram.handlers.interactive",
    "ccgram.handlers.live",
    "ccgram.handlers.messaging",
    "ccgram.handlers.messaging_pipeline",
    "ccgram.handlers.polling",
    "ccgram.handlers.polling.window_tick",
    "ccgram.handlers.polling.window_tick.decide",
    "ccgram.handlers.polling.window_tick.observe",
    "ccgram.handlers.polling.window_tick.apply",
    "ccgram.handlers.recovery",
    "ccgram.handlers.send",
    "ccgram.handlers.shell",
    "ccgram.handlers.status",
    "ccgram.handlers.text",
    "ccgram.handlers.toolbar",
    "ccgram.handlers.topics",
    "ccgram.handlers.voice",
    "ccgram.providers",
    "ccgram.miniapp",
]


@pytest.mark.parametrize("module", _MODULES)
def test_module_imports_in_clean_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Importing {module} failed in a clean interpreter.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
