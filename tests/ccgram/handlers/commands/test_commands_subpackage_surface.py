"""Structural test pinning the commands subpackage public surface.

Codifies the Round-5 invariant: the four submodules exist as importable
names and the package ``__all__`` matches the pre-refactor public
surface that ``handlers/command_orchestration.py`` exposed.
"""

import importlib

import pytest


_SUBMODULES = [
    "ccgram.handlers.commands.forward",
    "ccgram.handlers.commands.menu_sync",
    "ccgram.handlers.commands.failure_probe",
    "ccgram.handlers.commands.status_snapshot",
]


@pytest.mark.parametrize("module", _SUBMODULES)
def test_submodule_exists(module: str) -> None:
    importlib.import_module(module)


def test_public_surface_unchanged() -> None:
    """``handlers.commands.__all__`` must match the pre-refactor surface.

    Pre-refactor surface (sites that imported from
    ``handlers.command_orchestration``):
      - bot.py: ``commands_command``, ``toolbar_command``
      - bootstrap.py: ``setup_menu_refresh_job``
      - handlers/registry.py: ``commands_command``, ``forward_command_handler``,
        ``toolbar_command``
      - handlers/text/text_handler.py: ``sync_scoped_menu_for_text_context``

    The plan also re-exports ``get_global_provider_menu`` and
    ``set_global_provider_menu`` for tests that mutate the cache.
    """
    from ccgram.handlers import commands

    expected = {
        "commands_command",
        "forward_command_handler",
        "get_global_provider_menu",
        "set_global_provider_menu",
        "setup_menu_refresh_job",
        "sync_scoped_menu_for_text_context",
        "sync_scoped_provider_menu",
        "toolbar_command",
    }
    assert set(commands.__all__) == expected
    for name in expected:
        assert hasattr(commands, name), f"{name} missing from handlers.commands"
