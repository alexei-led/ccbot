"""Toolbar subpackage — /toolbar inline keyboard and its callbacks.

Bundles ``toolbar_keyboard`` (TOML-backed config singleton, per-window
label overrides, ``InlineKeyboardMarkup`` builder, toggle-button state
seeding) and ``toolbar_callbacks`` (callback-data dispatch for ``CB_TOOLBAR``
clicks: ``key`` / ``text`` / ``builtin`` action types).

Public surface re-exported here is what ``bot.py`` and other handlers
import; module internals stay private.
"""

from .toolbar_callbacks import handle_toolbar_callback
from .toolbar_keyboard import (
    build_toolbar_keyboard,
    get_toolbar_config,
    refresh_button_label,
    reload_toolbar_config,
    seed_button_states,
)

__all__ = [
    "build_toolbar_keyboard",
    "get_toolbar_config",
    "handle_toolbar_callback",
    "refresh_button_label",
    "reload_toolbar_config",
    "seed_button_states",
]
