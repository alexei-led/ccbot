# `handlers/polling_coordinator` — Outer Poll Loop

## Functional Responsibilities

Owns **only** the outer polling loop. Post-refactor it is a ~80-line
module that handles:

- Startup: read `STATUS_POLL_INTERVAL` from config, initialize timers.
- Per-cycle: enumerate tmux windows (live + emdash external), build the
  window lookup map.
- Delegate all periodic side tasks to `periodic_tasks` (broker delivery,
  mailbox sweep, spawn processing, live view, topic probing).
- Iterate `thread_router.iter_thread_bindings()` and hand each binding
  to `window_tick.tick_window(...)`.
- Delegate lifecycle work (autoclose sweeps) to
  `periodic_tasks.run_lifecycle_tasks`.
- Top-level error handling with exponential backoff.
- `structlog.contextvars` binding per window.

That is the entire contract. No status formatting, no interactive UI
decisions, no emoji logic, no autoclose policy, no pane scanning.

## Encapsulated Knowledge

- **Loop cadence** (`STATUS_POLL_INTERVAL`).
- **Error recovery policy**: which exceptions bubble, which trigger
  backoff, backoff curve bounds.
- **Per-cycle side-task scheduling** (but the actual work lives in
  `periodic_tasks`).

## Subdomain Classification

**Supporting** — the _loop shell_ itself is low-volatility now that all
behaviour has been delegated. Backoff policy, cadence, and iteration
don't change often.

## Integration Contracts

| Integration      | Direction                     | Strength   | What is shared                                                                                   |
| ---------------- | ----------------------------- | ---------- | ------------------------------------------------------------------------------------------------ |
| `window_tick`    | `polling_coordinator` → calls | Functional | `tick_window(bot, user_id, thread_id, wid, window)` — the _only_ entry point for per-window work |
| `periodic_tasks` | `polling_coordinator` → calls | Functional | `run_periodic_tasks`, `run_lifecycle_tasks`                                                      |
| `tmux_manager`   | `polling_coordinator` → calls | Functional | `list_windows`, `discover_external_sessions`                                                     |
| `thread_router`  | `polling_coordinator` → calls | Functional | `iter_thread_bindings`                                                                           |
| `config`         | `polling_coordinator` → reads | Contract   | `status_poll_interval`                                                                           |
| `utils`          | `polling_coordinator` → calls | Functional | `log_throttled`                                                                                  |

**Imports deleted vs. pre-refactor**: `claude_task_state`, `providers`,
`providers.base`, `session`, `session_monitor`, `cleanup`,
`interactive_ui`, `message_queue`, `message_sender`, `polling_strategies`,
`recovery_callbacks`, `topic_emoji`, `transcript_discovery`. All of these
are now `window_tick`'s concerns.

### Public API

```python
async def status_poll_loop(bot: Bot) -> None:
    """Background task: poll all thread-bound windows at the configured
    interval. Delegates per-window work to window_tick.tick_window()
    and periodic side tasks to periodic_tasks."""
```

Single entry point, same as today. `bot.py` does not need to change.

## Change Vectors

1. **New cadence** — config change only.
2. **Different backoff policy** — isolated to the `except` clauses.
3. **Loop-level telemetry** (e.g., per-cycle duration metrics) — add once
   around the inner `for` loop.

Changes that do **not** belong here:

- Anything per-window → goes to `window_tick`.
- Anything per-topic cleanup → goes to `topic_state_registry`
  subscribers.
- Anything that iterates all windows for a cross-cutting reason → goes
  to `periodic_tasks`.
