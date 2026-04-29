"""Polling subpackage — terminal status polling orchestration.

Bundles the modules that drive the per-window polling cycle:
``polling_coordinator`` (the outer loop), ``window_tick`` (per-window
work), ``polling_strategies`` (screen buffer, lifecycle, interactive,
pane strategies), and ``periodic_tasks`` (broker delivery, mailbox
sweep, lifecycle ticking).

Public surface re-exported here is the entry point for ``bot.py`` and
the rest of ``handlers/``; internals stay in the per-module files.
"""

from .periodic_tasks import (
    TOPIC_CHECK_INTERVAL,
    run_broker_cycle,
    run_lifecycle_tasks,
    run_periodic_tasks,
)
from .polling_coordinator import status_poll_loop
from .polling_strategies import (
    ACTIVITY_THRESHOLD,
    MAX_PROBE_FAILURES,
    PANE_COUNT_TTL,
    RC_DEBOUNCE_SECONDS,
    SHELL_COMMANDS,
    STARTUP_TIMEOUT,
    TYPING_INTERVAL,
    InteractiveUIStrategy,
    PaneStatusStrategy,
    PaneTransition,
    TerminalPollState,
    TerminalScreenBuffer,
    TickContext,
    TickDecision,
    TopicLifecycleStrategy,
    TopicPollState,
    WindowPollState,
    interactive_strategy,
    is_shell_prompt,
    lifecycle_strategy,
    pane_status_strategy,
    reset_window_polling_state,
    terminal_poll_state,
    terminal_screen_buffer,
)
from .window_tick import decide_tick, tick_window

__all__ = [
    "ACTIVITY_THRESHOLD",
    "MAX_PROBE_FAILURES",
    "PANE_COUNT_TTL",
    "RC_DEBOUNCE_SECONDS",
    "SHELL_COMMANDS",
    "STARTUP_TIMEOUT",
    "TOPIC_CHECK_INTERVAL",
    "TYPING_INTERVAL",
    "InteractiveUIStrategy",
    "PaneStatusStrategy",
    "PaneTransition",
    "TerminalPollState",
    "TerminalScreenBuffer",
    "TickContext",
    "TickDecision",
    "TopicLifecycleStrategy",
    "TopicPollState",
    "WindowPollState",
    "decide_tick",
    "interactive_strategy",
    "is_shell_prompt",
    "lifecycle_strategy",
    "pane_status_strategy",
    "reset_window_polling_state",
    "run_broker_cycle",
    "run_lifecycle_tasks",
    "run_periodic_tasks",
    "status_poll_loop",
    "terminal_poll_state",
    "terminal_screen_buffer",
    "tick_window",
]
