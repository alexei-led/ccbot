# Modularity Review — ccgram (Evening)

**Date:** 2026-04-15 (post-round-2 refactoring — all 12 fixes applied and verified)
**Scope:** Entire codebase (`src/ccgram/` — ~92 Python files, ~18,000 lines)
**Model:** Balanced Coupling (Strength × Distance × Volatility)
**Context:** Solo project, preventative architecture work, no current runtime pain

---

## Executive Summary

| Dimension                 | Score        | Delta      | Notes                                                                                                                                                                                            |
| ------------------------- | ------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Cohesion**              | 7.0 / 10     | ▲ +0.5     | Extracted modules are exemplary (idle_tracker 29L, event_reader 70L). window_tick (610L) and session.py (789L) remain broad.                                                                     |
| **Coupling Strength**     | 6.5 / 10     | ▲ +1.5     | Callback injection pattern reduces hidden couplings. session.py 32-handler fan-out and claude_task_state 4-write-path remain.                                                                    |
| **Layer Discipline**      | 7.5 / 10     | ▲ +2.5     | Major wins: run_broker_cycle → callback; status_bubble severed from polling_strategies; shell subprocess routed through tmux_manager.                                                            |
| **Encapsulation**         | 6.5 / 10     | = 0.0      | WindowStateStore API enforced; view_window() established. claude_task_state write discipline soft — 4 independent write paths persist despite declared "single authority."                       |
| **Volatility Management** | 6.5 / 10     | ▲ +1.0     | Provider abstraction is excellent. Session state changes cascade through 32 handlers (most volatile coupling).                                                                                   |
| **Testability**           | 5.5 / 10     | ▲ +0.5     | New small modules are highly testable. 6 global singletons (session_manager, thread_router, claude_task_state, tmux_manager, terminal_poll_state, terminal_screen_buffer) remain test obstacles. |
| **AI Context Efficiency** | 6.5 / 10     | ▲ +1.0     | Callback injection makes hidden deps visible. Deferred imports mostly eliminated. session.py 32-handler fan-out is the largest remaining context burden.                                         |
| **Architectural Clarity** | 7.5 / 10     | (new)      | Excellent documentation, consistent patterns (callback injection, self-registration). All patterns are named and declared.                                                                       |
| **Overall**               | **6.8 / 10** | **▲ +1.3** | Meaningful improvement. Trajectory is positive and concrete. Remaining issues are manageable for a solo project.                                                                                 |

---

## What Changed Since This Morning

12 concrete fixes were applied across two refactoring sessions:

| Fix                                                                              | Effect                       |
| -------------------------------------------------------------------------------- | ---------------------------- |
| `parse_session_map` duplicate removed                                            | Single source of truth       |
| `window_store.window_states` dict access replaced with store API                 | Encapsulation enforced       |
| `_has_insert_indicator` → `has_insert_indicator`                                 | No private API crossing      |
| `_get_provider()` 6 duplicates → 1 extracted function                            | DRY                          |
| `session_monitor.py` monolith → 4 sub-modules                                    | Cohesion, testability        |
| `claude_task_state` cleanup consolidated in `session_lifecycle`                  | Single authority declared    |
| `hook_events → periodic_tasks` → `_stop_callback` registration                   | Layer discipline             |
| Deferred `message_queue` imports → module-level                                  | Dependency graph now visible |
| `status_bubble → polling_strategies` → `register_rc_active_provider`             | Subsystem boundary clean     |
| `shell_capture ↔ shell_commands` → `CommandApprovalCallback` Protocol            | Main cycle broken            |
| `_capture_with_scrollback` subprocess → `tmux_manager.capture_pane_scrollback()` | Single tmux I/O path         |
| `session_manager.get_window_state()` bypasses → `view_window()`                  | Access discipline            |

**New structural strengths from this round:**

- `idle_tracker.py` — 29 lines, zero project imports, pure Python dict wrapper
- `event_reader.py` — 70 lines, only `aiofiles` + `structlog` + `providers.base.HookEvent`
- `session_lifecycle.py` — 115 lines, declared single authority for session-end state cleanup
- Callback injection pattern used consistently: `_stop_callback` (hook→polling), `register_rc_active_provider` (polling→status_bubble)
- `CommandApprovalCallback` Protocol defined in `shell_capture.py` — breaks main circular dependency

---

## System Overview

ccgram is a single-process Python Telegram bot managing AI coding agent CLIs over tmux. It is an **integration hub by nature** — Telegram API, tmux subprocess, 4 agent CLIs, Claude Code hooks, LLM API, and filesystem state all converge in one process. Some coupling is architecturally essential.

**Subsystems:**

| Subsystem             | Key Files                                                                                                          | Domain                           | Volatility |
| --------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------- | ---------- |
| Provider abstraction  | `providers/` (12 files)                                                                                            | Core — competitive advantage     | High       |
| Session monitoring    | `session_monitor.py`, `event_reader.py`, `session_lifecycle.py`, `transcript_reader.py`, `idle_tracker.py`         | Core — active evolution          | High       |
| Polling loop          | `handlers/polling_coordinator.py`, `window_tick.py`, `polling_strategies.py`                                       | Supporting — stable design       | Medium     |
| Message delivery      | `handlers/message_queue.py`, `status_bubble.py`, `tool_batch.py`, `message_sender.py`                              | Supporting — stable              | Low        |
| Handler layer         | ~50 handler modules                                                                                                | Supporting — extended frequently | Medium     |
| Core state            | `session.py`, `thread_router.py`, `window_state_store.py`, `claude_task_state.py`                                  | Supporting — frequently accessed | High       |
| Shell provider        | `providers/shell_infra.py`, `handlers/shell_commands.py`, `handlers/shell_capture.py`, `handlers/shell_context.py` | Supporting — active development  | Medium     |
| Inter-agent messaging | `mailbox.py`, `handlers/msg_broker.py`, `handlers/msg_spawn.py`, `handlers/msg_telegram.py`                        | Core — new feature               | High       |

---

## Remaining Open Issues

### Issue 1 — `session.py` Structural Hub: 32 Handler Dependents (High)

**Files:** `session.py` (789 lines, 47 methods)
**Verified:** 32 handler modules import `session_manager` directly, plus `bot.py` and `session_monitor.py`.

`session.py` has already extracted `ThreadRouter`, `UserPreferences`, `WindowStateStore`, and `WindowView`. What remains is still a broad surface:

```
Display names:    get_display_name(), set_display_name(), sync_display_names()
Session map:      load_session_map(), register_hookless_session(), wait_for_session_map_entry()
Session resolve:  resolve_session_for_window(), get_recent_messages(), get_session_id_for_window()
Lifecycle:        prune_stale_state(), audit_state(), resolve_stale_ids()
Provider:         get_window_provider(), set_window_provider()
Modes:            get_approval_mode(), set_window_approval_mode()
                  get_notification_mode(), set_notification_mode(), cycle_notification_mode()
                  get_batch_mode(), set_batch_mode(), cycle_batch_mode()
State:            view_window(), clear_window_session(), set_window_cwd()
```

**Coupling analysis:**

- **Strength:** HIGH — 32 callers make direct functional calls to mutable state
- **Distance:** LOW (solo project, same process)
- **Volatility:** HIGH — WindowState schema extended repeatedly; each new per-window flag reaches all 32 callers

**Balance:** HIGH strength + HIGH volatility → UNBALANCED. For a solo project, the practical cost is AI context burden: adding any new per-window flag requires auditing 32 handler files to find all usage sites. The review can't confirm safety without loading them all.

**Root cause:** Two distinct responsibilities are fused in one object:

1. **Window state store** — per-window modes, CWD, provider, display names (mutable, per-window state)
2. **Session resolver** — session history, message lookup, session map sync (read-heavy, session-scoped)

**Recommendation:** This doesn't require a large refactor — the extracted `WindowStateStore` already exists. The cleaner split would have handlers import the store directly for mode/state operations, and a `SessionResolver` for history/message operations. Each handler's actual dependency would shrink to 1–2 specific method groups rather than the entire SessionManager surface.

---

### Issue 2 — `claude_task_state` Has 4 Independent Write Paths (High)

**Files:** `claude_task_state.py` (491-line class), 4 writer modules

**Write operations, by caller:**

| Caller                    | Operations                                                                                                         | Layer   |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------- |
| `session_lifecycle.py`    | `clear_window()`, `clear_subagents()`                                                                              | Core    |
| `transcript_reader.py`    | `apply_entries()`, `rebuild_from_entries()`                                                                        | Core    |
| `handlers/hook_events.py` | `set_wait_header()`, `clear_wait_header()`, `mark_task_completed()`, `add_subagent()`, `remove_subagent()` (5 ops) | Handler |
| `handlers/window_tick.py` | `clear_wait_header()`, `set_last_status()`                                                                         | Handler |

**The authority violation:** `session_lifecycle.py` declares in its module-level docstring: _"callers must NOT touch claude_task_state or subagent state directly."_ Yet `hook_events.py` writes `add_subagent` / `remove_subagent` (subagent mutations) and `window_tick.py` writes `clear_wait_header` directly.

**Coordination conflict:** Both `hook_events.py` (Stop event) and `window_tick.py` (idle detection) independently call `clear_wait_header`. The comment in `hook_events.py` line 217 acknowledges the coordination concern: _"No immediate status update — the polling loop already appends subagent count."_ This means the two callers are aware of each other, but the coordination is implicit.

**Coupling analysis:**

- **Strength:** HIGH — 4 callers write to shared module-level dict, no ownership enforcement
- **Distance:** HIGH (crosses monitoring layer ↔ handler layer)
- **Volatility:** HIGH — Claude Code adds new task types, subagent patterns

**Balance:** HIGH strength + HIGH distance + HIGH volatility → UNBALANCED AND CRITICAL.

**Recommendation:** Enforce the declared authority. Move subagent mutation (`add_subagent`, `remove_subagent`) from `hook_events.py` into `session_lifecycle.py`. Have `hook_events` call `session_lifecycle.handle_subagent_start(window_id, ...)` and `handle_subagent_stop(window_id, ...)` — mirroring the existing `handle_session_end` pattern. For `clear_wait_header`: if the poller clears it on idle, that is `window_tick`'s right; if hooks clear it on Stop, that is `hook_events`'s right — pick one and document which owns the wait-header lifecycle.

---

### Issue 3 — `hook_events.py` SessionEnd Orchestrates 5 Subsystems (Medium)

**File:** `handlers/hook_events.py`, `_handle_session_end()` lines 287–312

Every SessionEnd event triggers operations across 5 distinct subsystems:

```python
session_lifecycle.handle_session_end(window_id)       # Core lifecycle
session_manager.clear_window_session(window_id)       # Core state
terminal_poll_state.clear_seen_status(window_id)      # Polling infra
thread_router.resolve_chat_id(user_id, thread_id)     # Routing
update_topic_emoji(bot, ...)                          # UI
enqueue_status_update(bot, ...)                       # Message delivery
```

**Coupling analysis:**

- **Strength:** HIGH — direct orchestration of 5 modules
- **Distance:** LOW (solo project, same process, all in handlers/)
- **Volatility:** HIGH — new hook event types added as Claude Code evolves

**Balance:** HIGH strength + LOW distance → BALANCED by distance, but the fan-out is a maintenance concern. Adding state to a new subsystem (e.g., a new per-session LLM cache) requires modifying `_handle_session_end`. The `session_lifecycle` was designed to absorb this, but doesn't own the full cleanup chain.

**Recommendation:** `session_lifecycle.handle_session_end()` could absorb the `session_manager.clear_window_session()` call — it has the window_id and is already coordinating task/subagent cleanup. `terminal_poll_state.clear_seen_status()` is polling infra and could be registered as a cleanup callback. This would reduce `hook_events._handle_session_end` to: call session_lifecycle, then deliver UI updates — a cleaner boundary.

---

### Issue 4 — `window_tick.py`: Wide Orchestration Hub (Low–Medium)

**File:** `handlers/window_tick.py` (610 lines, 19 functions, 23 import sources)

`window_tick` is the per-window polling heartbeat — it runs every second per active window. Its 19 functions span: dead window detection, interactive UI checking, transcript discovery, passive shell monitoring, status line computation, state transitions, status bubble updates, and multi-pane scanning. One public entry point: `tick_window()` at line 576.

**Coupling analysis:**

- **Strength:** HIGH — imports from 23 sources, mutates claude_task_state, calls into 8 subsystems
- **Distance:** LOW (same handlers package)
- **Volatility:** MEDIUM — polling behavior evolves with new features but core loop is stable

**Balance:** HIGH strength + LOW distance + MEDIUM volatility → BORDERLINE. This is an orchestrator pattern — inherently wide. The existing `polling_strategies.py` extracted the strategy objects, but the orchestration logic remains in `window_tick`.

**Structural note:** `window_tick` has no clear sub-component boundaries. The 19 functions could be grouped into 3 logical units:

- **Status resolution** (`_resolve_status`, `_build_status_line`, `decide_tick`, `_check_vim_insert`)
- **UI events** (`_check_interactive_only`, `_maybe_check_passive_shell`, `_scan_window_panes`)
- **State transitions** (`_apply_active_transition`, `_apply_done_transition`, `_apply_starting_transition`, `_transition_to_idle`, `_apply_tick_decision`, `_update_status`)

Extracting these groups would bring each logical unit to ~150–200 lines and reduce `tick_window` to pure coordination.

**Recommendation:** Low priority — this is a complexity issue, not a coupling problem. Address after Issue 2.

---

### Issue 5 — Residual Deferred Import: `shell_commands` → `shell_capture` (Low)

**File:** `handlers/shell_commands.py`, line 229

```python
from .shell_capture import mark_telegram_command
mark_telegram_command(window_id, command, user_id, thread_id)
```

The main `shell_capture ↔ shell_commands` cycle was broken by `CommandApprovalCallback`. One one-direction deferred import remains: `shell_commands` lazy-imports `mark_telegram_command` from `shell_capture`. The import is inside an async function body, not top-level.

**Coupling analysis:**

- **Strength:** LOW (one function, one direction, read-only call)
- **Distance:** LOW (same package)
- **Volatility:** LOW (mark_telegram_command is a stable tracking function)

**Balance:** LOW strength + LOW volatility → BALANCED AND TOLERABLE.

**Recommendation:** Lift the import to module-level in `shell_commands.py`. There is no longer a static cycle — the Protocol broke the reverse direction. The deferred import is now purely historical artifact.

---

## Summary Matrix

| Issue                                           | Files Affected                                                                                                  | Strength | Vol. | Priority    | Status                                  |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------- | ---- | ----------- | --------------------------------------- |
| `session.py` hub — 32 handler dependents        | `session.py` + 32 handler files                                                                                 | HIGH     | HIGH | **High**    | Open                                    |
| `claude_task_state` — 4 independent write paths | `claude_task_state.py`, `hook_events`, `window_tick`, `transcript_reader`, `session_lifecycle`                  | HIGH     | HIGH | **High**    | Open (authority declared, not enforced) |
| `hook_events` SessionEnd — 5 subsystems         | `hook_events.py`, `session_lifecycle`, `session_manager`, `terminal_poll_state`, `topic_emoji`, `message_queue` | HIGH     | HIGH | **Medium**  | Open (LOW distance softens)             |
| `window_tick.py` — 610L orchestration hub       | `window_tick.py`                                                                                                | HIGH     | MED  | **Low–Med** | Open (complexity, not coupling)         |
| `shell_commands:229` deferred import            | `shell_commands.py`, `shell_capture.py`                                                                         | LOW      | LOW  | **Low**     | Open (one-line fix)                     |

---

## Verified Fixes (All 12 from Morning Sessions)

| Fix                                                                   | Verified State                                                                                        |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `parse_session_map` duplicate removed                                 | ✅ Single parse in `session_map.py`                                                                   |
| `window_store.window_states` dict access → store API                  | ✅ `view_window()` pattern established                                                                |
| `_has_insert_indicator` promoted to public                            | ✅ `has_insert_indicator` in `tmux_manager.py`                                                        |
| `_get_provider()` 6 duplicates → 1 at `window_tick.py:64`             | ✅ Confirmed single definition                                                                        |
| `session_monitor.py` → 4 sub-modules                                  | ✅ `event_reader` (70L), `idle_tracker` (29L), `session_lifecycle` (115L), `transcript_reader` (416L) |
| `claude_task_state` cleanup → `session_lifecycle`                     | ✅ `handle_session_end` owns clear_window + clear_subagents                                           |
| `hook_events → periodic_tasks` → `_stop_callback`                     | ✅ No `run_broker_cycle` call in `hook_events.py`                                                     |
| Deferred `message_queue` imports → module-level                       | ✅ `enqueue_status_update` imported at line 33                                                        |
| `status_bubble → polling_strategies` → `register_rc_active_provider`  | ✅ Zero coupling to `polling_strategies`                                                              |
| `shell_capture ↔ shell_commands` → `CommandApprovalCallback` Protocol | ✅ Cycle broken; `_approval_callback` slot at line 65                                                 |
| `_capture_with_scrollback` subprocess → `tmux_manager`                | ✅ No subprocess calls in `shell_capture.py`                                                          |
| `session_manager.get_window_state()` → `view_window()`                | ✅ Access pattern established                                                                         |

---

## Architectural Patterns Introduced (Positive)

These patterns emerged during refactoring and should be used consistently for future extensions:

| Pattern                         | Example                                                          | Use When                                                                                                   |
| ------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Callback injection**          | `register_rc_active_provider()`, `_stop_callback`                | Subsystem A needs to call into B at runtime, but static import would create a layer violation              |
| **Self-registration decorator** | `topic_state_registry`, `callback_registry`                      | Cleanup functions or callback handlers that need to be discovered without explicit registration at startup |
| **Protocol boundary**           | `AgentProvider`, `CommandApprovalCallback`, `WhisperTranscriber` | Replace concrete type deps when the dependency crosses a significant boundary                              |
| **Pure dataclass module**       | `message_task.py` (zero project imports), `expandable_quote.py`  | Sum types, constants, or shared data structures that would otherwise create circular deps                  |
| **Singleton extracted module**  | `idle_tracker` (29L), `event_reader` (70L)                       | Stateful singleton that has a clear, narrow responsibility — extract before the responsibility grows       |

---

## Recommended Next Steps

Priority order for a solo dev, accounting for AI context efficiency as the primary cost:

1. **Enforce `claude_task_state` write discipline** — move `add_subagent`/`remove_subagent` from `hook_events` into `session_lifecycle`, and pick a single owner for `clear_wait_header`. 2–3 file changes, high leverage. This makes schema changes safe to reason about from one location.

2. **Split `session.py` into two narrower interfaces** — extract `SessionResolver` (history, message lookup, session map) from `SessionManager` (mode settings, window state, CWD, provider). Handlers that only need mode operations stop importing the full 789-line, 47-method object.

3. **Absorb `session_manager.clear_window_session()` into `session_lifecycle`** — consolidate SessionEnd cleanup fully into one place. Reduces `hook_events._handle_session_end` to lifecycle call + UI updates.

4. **Lift `shell_commands:229` deferred import** — one-line fix. `from .shell_capture import mark_telegram_command` can now be top-level. No cycle remains.

5. **Consider splitting `window_tick.py`** into three modules (status resolution, UI event handling, state transitions). Only worthwhile after the above structural work, when `window_tick` is no longer importing from 23 sources.
