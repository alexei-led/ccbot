# Modularity Review — ccgram

**Date:** 2026-04-15 (updated post-evening refactoring — all 5 open issues addressed)
**Scope:** Entire codebase (`src/ccgram/` — ~90 Python files, ~18,000 lines)
**Model:** Balanced Coupling (Strength × Distance × Volatility)

---

## Executive Summary

| Dimension                 | Score      | Notes                                                                                                                                |
| ------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Cohesion**              | 6.5/10     | Most modules focused. `window_tick.py` (610 lines) and `hook_events.py` are outliers. Session_monitor refactoring improved this.     |
| **Coupling Strength**     | 5/10       | `session.py` imported by 32 handler modules (functional coupling on volatile schema); `claude_task_state` accessed from 8 modules.   |
| **Layer Discipline**      | 5/10       | `hook_events` reaches into polling infra; `status_bubble` queries polling state; shell logic split across provider + handler layers. |
| **Encapsulation**         | 6.5/10     | `has_insert_indicator` promoted to public; store API bypasses resolved. `claude_task_state` ownership still undisciplined.           |
| **Volatility Management** | 5.5/10     | Provider protocol cleanly isolated. Core volatile areas (session state, task tracking) have cascading coupling.                      |
| **Testability**           | 5/10       | Global singletons (`session_manager`, `thread_router`, `claude_task_state`, `tmux_manager`) require complex test wiring.             |
| **AI Context Efficiency** | 5.5/10     | `session.py` imports (32 modules) mean any session change requires wide context. Core state changes still cascade.                   |
| **Overall**               | **5.5/10** | Active refactoring trajectory is clearly positive — three issues resolved today. Four issues remain.                                 |

---

## System Overview

ccgram is a Python Telegram bot that multiplexes AI coding agent CLIs (Claude, Codex, Gemini, Shell) over tmux sessions. It is a **single-service, single-process** system — all components share one Python process and a common set of global singletons.

**Subsystems identified:**

| Subsystem             | Key Files                                                                                                          | Domain Classification                  |
| --------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------- |
| Provider abstraction  | `providers/` (12 files)                                                                                            | Core — competitive advantage, evolving |
| Session monitoring    | `session_monitor.py`, `event_reader.py`, `session_lifecycle.py`, `transcript_reader.py`, `idle_tracker.py`         | Core — actively evolving               |
| Polling loop          | `handlers/polling_coordinator.py`, `window_tick.py`, `polling_strategies.py`                                       | Supporting — stable design             |
| Message delivery      | `handlers/message_queue.py`, `status_bubble.py`, `tool_batch.py`, `message_sender.py`                              | Supporting — stable                    |
| Handler layer         | ~50 handler modules                                                                                                | Supporting — frequently extended       |
| Core state            | `session.py`, `thread_router.py`, `window_state_store.py`, `session_map.py`, `claude_task_state.py`                | Supporting — frequently accessed       |
| Shell provider        | `providers/shell_infra.py`, `handlers/shell_commands.py`, `handlers/shell_capture.py`, `handlers/shell_context.py` | Supporting — actively developed        |
| Inter-agent messaging | `mailbox.py`, `msg_cmd.py`, `handlers/msg_broker.py`, `handlers/msg_spawn.py`, `handlers/msg_telegram.py`          | Core — new feature under development   |

**All issues resolved today (12 fixes across 2 refactoring sessions):**

- `parse_session_map` duplicate removed from `session.py` ✅
- `window_store.window_states` direct dict access replaced with store API ✅
- `_has_insert_indicator` promoted to public `has_insert_indicator` in `tmux_manager` ✅
- `_get_provider(window_id)` helper extracted in `window_tick.py` (6 duplicates → 1) ✅
- `session_monitor.py` refactored: 4 sub-modules extracted — monitor reduced 42% ✅
- `claude_task_state` cleanup consolidated in `session_lifecycle.handle_session_end()` ✅
- `hook_events` → `periodic_tasks` direct call replaced with registered `_stop_callback` ✅
- Deferred imports in `hook_events.py` promoted to module-level (dependency graph now visible) ✅
- `status_bubble` → `polling_strategies` severed via `register_rc_active_provider()` ✅
- `shell_capture ↔ shell_commands` cycle broken via `CommandApprovalCallback` Protocol ✅
- `_capture_with_scrollback` subprocess bypass replaced with `tmux_manager.capture_pane_scrollback()` ✅
- `session_manager.get_window_state()` removed from all handler call sites; `set_window_cwd()` added ✅

**Structural strengths:**

- `message_task.py` — pure frozen dataclass sum type, zero project imports
- `polling_coordinator.py` — 87 lines, thin orchestration shell
- `spawn_request.py` — pure functions and dataclasses, no handler dependencies
- `providers/base.py` — zero ccgram imports; clean protocol boundary
- `topic_state_registry.py` — self-registration pattern replaces 14+ lazy cleanup imports
- `hook.py` — correctly isolated from `config.py` (deployed in agent panes, no bot credentials)

---

## Open Issues

### Issue 1 — `session.py` Is a De-Facto Hub with 32 Handler Dependents (Critical)

**Files:** `session.py` (783 lines)
**What knowledge is shared:** Every Telegram handler that needs window state, mode settings, session resolution, display names, or state persistence imports `session_manager` directly. Currently 32 handler modules import from `session.py`, plus `bot.py`, `transcript_reader.py`, and `session_map.py`.

**API surface (indicative):**

```
Window state:     get_window_state(), view_window(), window_states
Mode settings:    get_approval_mode(), set_window_approval_mode()
                  get_notification_mode(), cycle_notification_mode()
                  get_batch_mode(), set_batch_mode()
Session map:      load_session_map(), register_hookless_session(), wait_for_session_map_entry()
Session resolve:  resolve_session_for_window(), get_recent_messages()
Lifecycle:        prune_stale_state(), audit_state(), resolve_stale_ids()
Provider:         get_window_provider(), set_window_provider()
```

**Coupling analysis:**

- **Strength:** HIGH — every handler makes direct functional calls to `session_manager`; mutation methods are called from 32 independent sites with no access discipline
- **Distance:** LOW (all in same process)
- **Volatility:** HIGH — WindowState schema has been extended repeatedly (approval modes, batch modes, notification modes, provider_name); each addition creates a wave of import-and-use sites

**Balance:** HIGH strength + HIGH volatility → UNBALANCED. The key risk is that `session.py` changes (any new field, any renamed method) must be audited across 32 + N handler files.

**AI context efficiency impact:** Any task touching session state requires loading `session.py` (783 lines) plus every handler that mutates the relevant field. An AI asked to "add a new per-window flag" must understand the full handler fan-out to not miss a usage site.

**Root cause:** `session_manager` is both a _data store_ (window states, display names) and a _service_ (session resolution, session map sync, state audit). These concerns grew together without a clean boundary being established.

**Recommendation:** `session.py` has already extracted `ThreadRouter`, `UserPreferences`, `WindowStateStore`, and `WindowView`. The next step is establishing that **handlers should prefer `window_view` (read) or specific setter methods (write)** and never access `window_states` directly. A `WindowService` or clearer division into `WindowStateService` (modes/provider) vs. `SessionResolver` (history, message lookup) would reduce each handler's dependency to a narrow slice.

---

### Issue 2 — `claude_task_state.py` Is Shared Mutable State with No Ownership Discipline (High)

**Files:** `claude_task_state.py` (562 lines), imported by 8 modules across core and handler layers.

**Import sites:**

```
session_lifecycle.py      — clear_window() (designated single authority)
transcript_reader.py      — set_window_tasks(), mark_task_completed()
handlers/hook_events.py   — add_subagent(), remove_subagent(), clear_subagents()
handlers/window_tick.py   — claude_task_state (object), build_subagent_label()
handlers/tool_batch.py    — build_subagent_label(), get_subagent_names()
handlers/status_bubble.py — get_claude_task_snapshot(), get_claude_wait_header()
```

**The coordination failure:** `session_lifecycle.py` is designated the single authority for session-end state cleanup. The `hook_events.py` SessionEnd handler correctly calls `session_lifecycle.handle_session_end(window_id)` — but then immediately performs _additional_ cleanup directly alongside it:

```python
session_lifecycle.handle_session_end(window_id)   # designated authority
session_manager.clear_window_session(window_id)   # also done directly
clear_subagents(window_id)                        # also done directly
```

Cleanup is split between the authority module and the caller. Anyone adding new per-session state that must be cleared on SessionEnd has two sites to update — miss either and state leaks.

More broadly, `claude_task_state` has 6 independent write paths with no coordination protocol:

| Caller                 | Operations                                                 |
| ---------------------- | ---------------------------------------------------------- |
| `session_lifecycle.py` | `clear_window()`                                           |
| `transcript_reader.py` | `set_window_tasks()`, `mark_task_completed()`              |
| `hook_events.py`       | `add_subagent()`, `remove_subagent()`, `clear_subagents()` |
| `window_tick.py`       | subagent label reads, indirect triggers                    |
| `tool_batch.py`        | `build_subagent_label()`, `get_subagent_names()`           |
| `status_bubble.py`     | `get_claude_task_snapshot()`, `get_claude_wait_header()`   |

**Coupling analysis:**

- **Strength:** HIGH — 6 callers mutate or read shared module-level dicts with no ownership discipline
- **Distance:** HIGH — `claude_task_state` bridges the monitoring layer (transcript_reader, session_lifecycle) and the display/handler layer (hook_events, status_bubble, tool_batch)
- **Volatility:** HIGH — Claude Code adds new task types and subagent patterns regularly; any schema change requires auditing all write callers

**Balance:** HIGH strength + HIGH distance + HIGH volatility → UNBALANCED. Any new per-session state field or lifecycle event requires auditing 6 callers across 2 layers, with no enforced coordination path.

**AI context efficiency impact:** Adding a new task field requires: reading `claude_task_state.py` (562 lines) + auditing all 6 callers + verifying the SessionEnd cleanup is consistent in both `session_lifecycle` and `hook_events`. Multi-file context load for what should be a contained change.

**Recommendation:** Consolidate all write access in `session_lifecycle.py`. Move subagent mutation functions there and have `hook_events.py` delegate fully — remove the parallel cleanup block alongside the `handle_session_end()` call. Give display modules a read-only interface via the existing `get_claude_task_snapshot()`.

---

### Issue 3 — `hook_events.py` Crosses the Hook→Polling Boundary (High)

**Files:** `handlers/hook_events.py`, `handlers/periodic_tasks.py`, `handlers/polling_strategies.py`

**What knowledge is shared:** `hook_events.py` dispatches structured Claude Code hook events. Its Stop handler directly invokes `run_broker_cycle()` from `periodic_tasks.py` (polling infrastructure) via a deferred import.

**Evidence (hook_events.py:180–182):**

```python
from .periodic_tasks import run_broker_cycle
await run_broker_cycle(bot, idle_windows=frozenset({event.window_key}))
```

**Coupling analysis:**

- **Strength:** HIGH — direct functional call into polling infrastructure from event dispatch layer
- **Distance:** LOW (same handlers package)
- **Volatility:** HIGH — hook events are the primary real-time signaling mechanism; new event types are added as Claude Code evolves

**Balance:** HIGH strength × HIGH volatility × LOW distance → UNBALANCED. The Stop event handler should signal intent (e.g., "broker delivery needed for this window") rather than invoking polling infrastructure directly. This creates a hidden dependency that only appears at runtime.

**The deferred import hides the real dependency graph:** 9 of `hook_events.py`'s imports are inside function bodies. Static analysis tools and AI context scanners won't see these imports unless they inspect every function body. Adding a new hook type requires understanding a hidden dependency graph.

**Recommendation:** Replace the direct `run_broker_cycle` call with a registered callback or a simple event queue. The existing callback registration pattern (used by `session_monitor`) provides a clean model. Consolidate deferred `message_queue` imports (appears 4× in different function bodies) to top-level.

---

### Issue 4 — `status_bubble.py` Queries Polling State Directly (Medium)

**Files:** `handlers/status_bubble.py`, `handlers/polling_strategies.py`

**Evidence (status_bubble.py:31, 195):**

```python
from .polling_strategies import terminal_screen_buffer
...
rc_active=terminal_screen_buffer.is_rc_active(window_id),
```

**Coupling analysis:**

- **Strength:** LOW-MEDIUM — single boolean lookup
- **Distance:** MEDIUM — different subsystems: display/delivery vs. polling state
- **Volatility:** LOW (RC badge is a stable feature)

**Balance:** Low volatility makes this tolerable in isolation. The architectural concern is that `status_bubble` (message delivery subsystem) now depends on `polling_strategies` (polling subsystem). If RC detection moves to a different module, `status_bubble` must change too.

**A secondary issue:** `status_bubble.py:138–162` accesses 4 internal fields of `ClaudeTaskSnapshot` directly. Any change to the snapshot schema breaks status display.

**Recommendation:** Pass `rc_active: bool` as a parameter to `build_status_keyboard()`. The caller already has the polling context. For the snapshot coupling: a `format_task_summary() -> str` method on `ClaudeTaskSnapshot` would encapsulate the display rendering.

---

### Issue 5 — Shell Feature Has Runtime Circular Dependency (Medium)

**Files:** `handlers/shell_capture.py`, `handlers/shell_commands.py`, `handlers/shell_context.py`

**What knowledge is shared:** `shell_capture._maybe_suggest_fix()` calls `shell_commands.show_command_approval()` via a deferred runtime import. `shell_context.py` was extracted to break an earlier static cycle, but the runtime mutual dependency between `shell_capture` and `shell_commands` persists.

**Coupling analysis:**

- **Strength:** HIGH — mutual functional dependency; each module calls the other's logic
- **Distance:** LOW (same package)
- **Volatility:** MEDIUM — shell NL-command flow evolves; error suggestion UX changes

**The tmux bypass in shell_capture:**

```python
# shell_capture.py calls tmux directly, bypassing tmux_manager:
proc = await asyncio.create_subprocess_exec("tmux", "capture-pane", ...)
```

This creates a second independent tmux access path outside `tmux_manager`, which now manages all other tmux I/O, vim state serialization, and external window routing.

**Recommendation:** Introduce a `CommandApprovalCallback` protocol or callable type. `shell_capture` accepts it as a parameter rather than importing `shell_commands` at runtime. This eliminates the circular dependency architecturally. Route the `capture-pane` call through `tmux_manager`.

---

## Summary Matrix

| Issue                                            | Files Affected                                                     | Strength | Volatility | Priority | Status                                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------ | -------- | ---------- | -------- | ------------------------------------------------------------------------------------------ |
| `session.py` hub — `get_window_state()` bypasses | `bot.py`, `directory_callbacks.py` (was 32 callers)                | HIGH     | HIGH       | Critical | **Fixed** (partial: `get_window_state()` eliminated; 32-module fan-out remains structural) |
| `claude_task_state` shared mutable, no authority | `claude_task_state.py`, `session_lifecycle`, `hook_events`, 5 more | HIGH     | HIGH       | High     | **Fixed**                                                                                  |
| `hook_events.py` reaches into polling infra      | `hook_events.py`, `periodic_tasks.py`                              | HIGH     | HIGH       | High     | **Fixed**                                                                                  |
| `status_bubble` queries polling state            | `status_bubble.py`, `polling_strategies.py`                        | LOW      | LOW        | Medium   | **Fixed**                                                                                  |
| `shell_capture` ↔ `shell_commands` runtime cycle | `shell_capture.py`, `shell_commands.py`                            | HIGH     | MEDIUM     | Medium   | **Fixed**                                                                                  |
| `_has_insert_indicator` private API access       | `window_tick.py`, `tmux_manager.py`                                | HIGH     | HIGH       | Critical | **Fixed**                                                                                  |
| `_get_provider()` duplicated 6× in window_tick   | `window_tick.py`                                                   | MED      | HIGH       | High     | **Fixed**                                                                                  |
| `session_map` bypasses `WindowStateStore` API    | `session_map.py`, `window_state_store.py`                          | HIGH     | MEDIUM     | High     | **Fixed**                                                                                  |
| `parse_session_map` duplicated in two files      | `session.py`, `session_map.py`                                     | HIGH     | MEDIUM     | Medium   | **Fixed**                                                                                  |
| `session_monitor.py` monolith                    | `session_monitor.py` (was 750+ lines)                              | HIGH     | HIGH       | Critical | **Fixed**                                                                                  |

---

## Recommended Priorities

1. **`claude_task_state` write discipline** — designate `session_lifecycle.py` as the single write authority and remove the `hook_events` → `claude_task_state` direct mutation path. This is the highest-risk shared-state pattern: volatile schema + 8 callers + no ownership discipline.

2. **`hook_events.py` boundary crossing** — replace the direct `run_broker_cycle` call with a callback or event notification. Consolidate the 4× deferred `message_queue` imports to top-level. Hidden dependencies are the most expensive pattern for AI context loading.

3. **`session.py` interface boundary** — formalize the read/write interface by enforcing `view_window()` for readers and explicit setter methods for writers. This doesn't require a big refactor — start by ensuring no handler bypasses the existing accessors. The 32-file fan-out is a symptom; narrowing each handler's dependency to the methods it actually uses is the fix.

4. **`status_bubble` → `polling_strategies` severance** — pass `rc_active: bool` as a parameter to `build_status_keyboard()`. One-line fix, zero risk, severs a cross-subsystem dependency.

5. **Shell circular dependency** — introduce a `CommandApprovalCallback` type to break the `shell_capture ↔ shell_commands` runtime cycle. Route the `capture-pane` subprocess call through `tmux_manager`.
