"""Live subpackage — live terminal view, screenshot, and pane controls.

Bundles the modules that own terminal-image surfaces in Telegram:
``live_view`` (auto-refreshing screenshot loop with content-hash gating
and timeout-based auto-stop), ``screenshot_callbacks`` (one-shot
screenshot command, inline-key remote control, refresh, live start/stop
callbacks plus the ``/live`` and ``/panes`` commands), and
``pane_callbacks`` (per-pane subscribe/unsubscribe, rename, and
lifecycle-notification toggles for multi-pane windows).

Public surface re-exported here is the entry point for ``bot.py`` and
the rest of ``handlers/``; internals stay in the per-module files.
"""

from .live_view import (
    LiveViewState,
    build_live_keyboard,
    content_hash,
    get_live_view,
    is_live,
    start_live_view,
    stop_live_view,
    tick_live_views,
)
from .pane_callbacks import (
    apply_pane_rename,
    build_pane_buttons,
    build_pane_lifecycle_button,
)
from .screenshot_callbacks import (
    KEY_LABELS,
    KEYS_SEND_MAP,
    build_screenshot_keyboard,
    handle_screenshot_callback,
    live_command,
    panes_command,
    screenshot_command,
)

__all__ = [
    "KEYS_SEND_MAP",
    "KEY_LABELS",
    "LiveViewState",
    "apply_pane_rename",
    "build_live_keyboard",
    "build_pane_buttons",
    "build_pane_lifecycle_button",
    "build_screenshot_keyboard",
    "content_hash",
    "get_live_view",
    "handle_screenshot_callback",
    "is_live",
    "live_command",
    "panes_command",
    "screenshot_command",
    "start_live_view",
    "stop_live_view",
    "tick_live_views",
]
