"""Structural tests for the recovery subpackage post-Round-5 split.

After Round 5 Task 3, ``recovery_callbacks.py`` shrank to a dispatcher
and the banner / picker UX flows moved to siblings. These tests pin the
new shape so regressions surface in CI rather than in production:

  - both new modules exist as importable names
  - ``handlers.recovery.__all__`` matches the pre-refactor public
    surface — external callers (``bot.py``, ``handlers/registry.py``,
    ``handlers/text/text_handler.py``) keep working unchanged
  - the dispatcher no longer re-imports the moved symbols at module
    scope (regression guard against the old ``__getattr__`` shim)
"""

from __future__ import annotations

import importlib

EXPECTED_PUBLIC_SURFACE = {
    "RecoveryBanner",
    "ResumeEntry",
    "build_recovery_keyboard",
    "discover_and_register_transcript",
    "format_session_entry",
    "handle_history_callback",
    "handle_recovery_callback",
    "handle_resume_command_callback",
    "render_banner",
    "restore_command",
    "resume_command",
    "scan_all_sessions",
    "scan_sessions_for_cwd",
    "send_history",
}


def test_recovery_banner_module_importable() -> None:
    mod = importlib.import_module("ccgram.handlers.recovery.recovery_banner")
    assert mod.RecoveryBanner.__module__ == mod.__name__
    assert callable(mod.render_banner)
    assert callable(mod.build_recovery_keyboard)


def test_resume_picker_module_importable() -> None:
    mod = importlib.import_module("ccgram.handlers.recovery.resume_picker")
    assert callable(mod.scan_sessions_for_cwd)
    assert callable(mod._handle_resume_pick)
    assert mod._SessionEntry.__module__ == mod.__name__


def test_recovery_callbacks_dispatcher_only() -> None:
    """Dispatcher is a thin module — banner/picker symbols moved away.

    ``_validate_recovery_state`` lives in :mod:`recovery_banner` (its
    only caller); only ``_clear_recovery_state`` is shared between the
    siblings and stays on the dispatcher.
    """
    mod = importlib.import_module("ccgram.handlers.recovery.recovery_callbacks")
    assert callable(mod.handle_recovery_callback)
    assert callable(mod._clear_recovery_state)
    assert not hasattr(mod, "_validate_recovery_state")
    banner = importlib.import_module("ccgram.handlers.recovery.recovery_banner")
    assert callable(banner._validate_recovery_state)


def test_subpackage_public_surface_unchanged() -> None:
    pkg = importlib.import_module("ccgram.handlers.recovery")
    assert set(pkg.__all__) == EXPECTED_PUBLIC_SURFACE
    for name in EXPECTED_PUBLIC_SURFACE:
        assert hasattr(pkg, name), f"recovery.{name} missing after split"


def test_render_banner_lives_in_banner_module() -> None:
    pkg = importlib.import_module("ccgram.handlers.recovery")
    assert pkg.render_banner.__module__ == "ccgram.handlers.recovery.recovery_banner"


def test_scan_sessions_for_cwd_lives_in_picker_module() -> None:
    pkg = importlib.import_module("ccgram.handlers.recovery")
    assert (
        pkg.scan_sessions_for_cwd.__module__ == "ccgram.handlers.recovery.resume_picker"
    )
