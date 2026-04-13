# Polling and Events

## Functional Responsibilities

Two related subsystems live in the same module because they share a cadence and a state model:

1. **Status polling loop** — a 1-second async loop in `polling_coordinator.py` that iterates every thread binding and updates terminal status, interactive UI, topic lifecycle (autoclose / TTL), shell relay, and dead-window detection. Also runs bot-wide periodic tasks (broker delivery, mailbox sweep, live view tick, spawn processing, transcript discovery sweep) once per cycle.
2. **Hook event processing** — Claude Code's hooks (`SessionStart`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `TeammateIdle`, `TaskCompleted`) write append-only lines to `events.jsonl`; the session monitor reads them incrementally and dispatches to handler callbacks.

Files:

- **`handlers/polling_coordinator.py`** (~600 lines) — `status_poll_loop`, orchestration helpers (`update_status_message`, `_scan_window_panes`, `_maybe_check_passive_shell`, `_check_interactive_only`, `_handle_dead_window_notification`, `_handle_no_status`, `_transition_to_idle`). Imports from 9 handler modules; ordering of the inline sections matters.
- **`handlers/polling_strategies.py`** (~550 lines after refactor) — per-window polling state, split into two classes: `TerminalScreenBuffer` (pyte parsing, screen buffer pool, pane count cache, rendered text cache) and `TerminalPollState` (RC debounce, probe failures, startup grace, unbound timers, seen-status tracking, recent-activity). Plus `InteractiveUIStrategy` (pane alerts) and `TopicLifecycleStrategy` (autoclose, dead notification, typing throttle). Module-level wrapper functions **deleted** after the topic_state_registry change.
- **`handlers/periodic_tasks.py`** (unchanged) — bot-wide periodic task orchestration (broker, sweep, spawn, lifecycle, live view).
- **`hook.py`** — CLI entry point for Claude Code hooks. Reads stdin, writes `session_map.json` and `events.jsonl`.
- **`handlers/hook_events.py`** — dispatches parsed `HookEvent` objects from the session monitor to handler logic. Owns Stop/StopFailure/Notification/Subagent*/Team* handlers.
- **`claude_task_state.py`** — per-window task tracking state and `build_subagent_label` / `get_subagent_names`. Moved from `hook_events` in the Apr 12 refactor; stays here.

## Encapsulated Knowledge

- **Loop ordering** — only `polling_coordinator` knows the strict order: transcript discovery → status scan → pane scan → passive shell check → RC debounce → dead detection. Reordering is a semantic change.
- **Per-window state split** — after refactor, each polling state machine is a single-responsibility class:
  - `TerminalScreenBuffer` owns "what does this window's terminal look like" (pyte, pane count, rendered text).
  - `TerminalPollState` owns "how should we treat this window next tick" (probe failures, startup grace, activity timestamps, unbound timers).
  - `InteractiveUIStrategy` owns "which panes have pending interactive prompts".
  - `TopicLifecycleStrategy` owns "when should this topic auto-close / be marked dead / throttle typing".
- **Hook event wire format** — only `hook.py` knows the JSON schema Claude Code sends on stdin. Only `hook_events.py` knows how to parse the `events.jsonl` line format.
- **Cleanup registration** — after refactor, `@topic_state.register("window")` decorators live on the instance methods that implement cleanup. No more module-level wrappers. `topic_state_registry` accepts `Callable | MethodType`; the registry binds on registration.

## Subdomain Classification

**Core.** Polling is the backbone of the UX — users see idle/active/done state transitions on every interaction. Hook events drive instant notifications and are tied to Claude Code's event surface. Both evolve each release.

## Integration Contracts

### Inbound

| From                                                         | Kind                      | Contract                                                                      |
| ------------------------------------------------------------ | ------------------------- | ----------------------------------------------------------------------------- |
| Bot `post_init` → `status_poll_loop(bot)` as background task | Contract                  | Async function, cancellable                                                   |
| `session_monitor` → `hook_events.handle_event(event, bot)`   | Contract                  | `HookEvent` dataclass                                                         |
| `topic_state_registry` → instance methods via decorator      | Contract (after refactor) | Bound method with `(window_id, ...)` or `(user_id, thread_id, ...)` signature |

### Outbound

| To                                                  | Kind       | Contract                                                                            |
| --------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------- |
| 9 handler modules in `polling_coordinator`          | Functional | Direct imports; ordering matters. Trade-off: tight in-module coupling vs simplicity |
| `session_manager.view_window(window_id)`            | Contract   | Read-only projection                                                                |
| `status_bubble.enqueue_status_update(...)`          | Contract   | Message delivery                                                                    |
| `interactive_ui.show_interactive_alert(...)`        | Contract   | Alert keyboard                                                                      |
| `topic_lifecycle.schedule_autoclose_timer(...)`     | Contract   | Lifecycle hook                                                                      |
| `topic_emoji.set_topic_state(...)`                  | Contract   | Emoji badge update                                                                  |
| `tmux_manager.list_panes`, `capture_pane`           | Contract   | Standard ops                                                                        |
| `claude_task_state.build_subagent_label(window_id)` | Contract   | Pure lookup                                                                         |

### topic_state_registry change

```python
# topic_state_registry.py — updated signature
from types import MethodType
from typing import Callable, Literal

Scope = Literal["window", "topic", "qualified", "chat"]

def register(scope: Scope) -> Callable:
    def decorator(fn: Callable | MethodType) -> Callable:
        # Support both free functions AND bound methods.
        # For unbound methods (decorated at class body), defer binding
        # until the instance is available — use a `_pending_registrations`
        # list keyed by class, then wire in `__post_init__` of the owner.
        _pending_registrations.setdefault(_owner_of(fn), []).append((scope, fn))
        return fn
    return decorator
```

Alternative (simpler): keep module-level decorator semantics but add a `register_bound(scope, method)` helper that the strategy constructor calls explicitly:

```python
# In TerminalScreenBuffer.__init__
topic_state.register_bound("window", self.clear_screen_buffer)
topic_state.register_bound("window", self.reset_pane_count_cache)
```

This is more explicit (no class-body decorator magic) and removes the 20+ compat wrappers without introducing metaclass complexity.

## Change Vectors

- **New polling concern** — add a method to the right strategy class; register it via `register_bound` in the constructor. No wrapper functions, no module-level glue.
- **New hook event type** — add parser in `hook_events`, dispatcher branch, optional handler. The `events.jsonl` schema is append-only so old parsers keep working.
- **Change the loop cadence** — single constant in `polling_coordinator`.
- **Re-order the loop sections** — deliberate; all in one function.
- **Split `TerminalPollState` further** — if one of its concerns (e.g., probe failures) becomes complex enough, it can be extracted to its own class. The register_bound pattern makes this incremental.

## Refactor Plan

1. **Add `topic_state.register_bound(scope, method)`** to `topic_state_registry.py` (~10 lines). Accepts a bound method and a scope label. Internally the registry stores a callable that already has `self` baked in.
2. **Delete the 20+ module-level wrappers** at the bottom of `polling_strategies.py` (L566-652). They become dead code once instance methods are registered.
3. **Convert `@topic_state.register` decorations on free functions in `polling_strategies.py`** to `topic_state.register_bound(...)` calls inside the strategy constructors. For `TerminalStatusStrategy.__init__`, `InteractiveUIStrategy.__init__`, `TopicLifecycleStrategy.__init__`, add the registrations explicitly.
4. **Split `TerminalStatusStrategy`** into `TerminalScreenBuffer` and `TerminalPollState`. `TerminalScreenBuffer` owns: `clear_screen_buffer`, `reset_screen_buffer_state`, `get_screen_buffer`, `parse_with_pyte`, `update_pane_count_cache`, `is_single_pane_cached`, `get_rendered_text`. `TerminalPollState` owns: everything else currently in the class (~23 methods). They communicate via read-only method calls — e.g., `TerminalPollState.is_rc_active(window_id)` doesn't need the screen buffer.
5. **Update `polling_coordinator.py` imports** — uses `terminal_screen_buffer` and `terminal_poll_state` instances instead of `terminal_strategy`.
6. **Leave `status_poll_loop` alone.** The inline section ordering stays; the helpers stay; the loop itself is left unchanged. The pain was in the strategy layer, not the orchestration.
7. **Document the loop ordering** — a comment block at the top of `status_poll_loop` explaining why transcript discovery comes before status scanning, why dead detection comes after everything else. This is the only documentation of ordering-as-contract.

## Testability Goals

- **Unit-test each strategy class in isolation.** `TerminalScreenBuffer` can be tested with a fake pane text — no tmux. `TerminalPollState` can be tested with a fake clock — no real time.
- **Integration-test `update_status_message`** with a mocked `bot`, mocked `view_window`, mocked `tmux_manager`. The function is 100 lines but pure orchestration — every path is testable with fakes.
- **Integration-test the cleanup registry** — instantiate `TerminalScreenBuffer`, call `topic_state.fire("window", @5)`, verify `clear_screen_buffer(@5)` was called.
- **Unit-test `hook_events.handle_stop`** with a synthetic `HookEvent` and a fake session monitor — verify the status bubble update enqueues correctly.
- **Unit-test `claude_task_state.build_subagent_label`** — pure dict lookup.
- **E2E smoke test** — run `status_poll_loop` for a single tick against a fake tmux and a fake session manager; verify no exceptions on a minimal bound thread.
