# Modularity Review

**Scope**: Entire ccgram codebase — post-refactoring pass, 2026-04-16  
**Date**: 2026-04-16 (v2 — follows the morning review in `2026-04-16/`)  
**Previous review**: `docs/modularity-review/2026-04-16/modularity-review.md`

## Executive Summary

ccgram is a single-process Python bot (~47k lines) that routes Telegram messages to AI coding agent CLIs running in tmux panes. A targeted refactoring pass addressed all six issues from the morning review: `monitor_events.py` was extracted to break the `transcript_reader ↔ session_monitor` import cycle; subagent mutation authority was consolidated into `SessionLifecycle`; a `reset_window_polling_state()` facade now provides a single reset contract for the polling subsystem; `tmux_manager`'s module-level dependency on the provider domain layer was removed; `WindowView` gained a `batch_mode` field; and `ClaudeProvider.scrape_current_mode` became testable via an injectable `capture_fn`.

The overall modularity health has improved from **4.8/10 to 5.4/10**, moving from "needs attention" to "improving but significant work remains." The session-state [coupling](https://coupling.dev/posts/core-concepts/coupling/) problem was not targeted in this pass and remains the dominant drag: `SessionManager` is still directly accessed from all 30 handler files at 89 call sites. The `claude_task_state` write-authority problem was partially resolved — cleanup paths are now consolidated — but active state mutations from `hook_events.py` and `window_tick.py` still bypass the designated authority. Both issues affect the most [volatile](https://coupling.dev/posts/dimensions-of-coupling/volatility/) areas of the codebase and remain the highest-priority targets for the next pass.

## Dimension Scores

| Dimension                                                                             | Before     | After      | Delta    | Notes                                                                                        |
| ------------------------------------------------------------------------------------- | ---------- | ---------- | -------- | -------------------------------------------------------------------------------------------- |
| Encapsulation / Information Hiding                                                    | 4/10       | 5/10       | +1       | `batch_mode` on `WindowView`; subagent authority consolidated; polling reset facade added    |
| Cohesion                                                                              | 5/10       | 5/10       | —        | No module splits; large files unchanged                                                      |
| [Coupling](https://coupling.dev/posts/core-concepts/coupling/) Discipline             | 4/10       | 5/10       | +1       | `tmux_manager` module-level `providers` import removed; transcript/monitor cycle broken      |
| Contract Stability                                                                    | 6/10       | 6/10       | —        | `reset_window_polling_state` is a new named contract; `WindowView` gains `batch_mode`        |
| Testability                                                                           | 5/10       | 6/10       | +1       | Injectable `capture_fn`; `monitor_events.py` freely importable without triggering singletons |
| [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) Alignment | 4/10       | 5/10       | +1       | Coupling density in volatile areas slightly reduced                                          |
| Module Size Distribution                                                              | 6/10       | 6/10       | —        | No module splits                                                                             |
| Dependency Direction                                                                  | 4/10       | 5/10       | +1       | `tmux_manager` → `providers` module-level dependency removed                                 |
| **Overall**                                                                           | **4.8/10** | **5.4/10** | **+0.6** | Meaningful progress; session-state and active mutation authority remain open                 |

## What Was Resolved

| Issue                                                      | Change                                                                                    | Status                           |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------- |
| Circular dependency: `transcript_reader ↔ session_monitor` | Extracted `monitor_events.py` with zero internal dependencies                             | ✅ Resolved                      |
| Subagent mutation authority                                | `handle_subagent_start/stop` added to `SessionLifecycle`; `hook_events` routes through it | ✅ Resolved (cleanup paths)      |
| Polling state facade                                       | `reset_window_polling_state(window_id)` added; `command_orchestration` uses it            | ✅ Resolved (one bypass remains) |
| `tmux_manager` → `providers` layer violation               | Module-level import removed; local import inside `_scan_session_windows`                  | ✅ Resolved                      |
| `WindowView` coverage gap                                  | `batch_mode` field added; `_handle_stop` uses `view.notification_mode`                    | ✅ Partial                       |
| `ClaudeProvider.scrape_current_mode` hardwires tmux        | Injectable `capture_fn` parameter with default                                            | ✅ Resolved                      |

## Coupling Overview

| Integration                                               | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)    |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 30 handler modules → `SessionManager` (89 call sites)     | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — unchanged from prior review                                  |
| `hook_events` → `claude_task_state` (5 active mutations)  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — non-cleanup writes have no single authority                  |
| `window_tick` → `claude_task_state` (3 mutations)         | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — active state mutations outside designated authority          |
| `window_tick` → `polling_strategies` internals (30 calls) | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service (cross-layer)                                              | High                                                                        | No — core polling loop reaches into strategy internals directly   |
| `hook_events` → `terminal_poll_state.clear_seen_status`   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — bypasses `reset_window_polling_state` facade                 |
| 3 remaining deferred-import cycles                        | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bidirectional) | Same service                                                            | High                                                                        | No — masks true dependency graph                                  |
| `shell_infra` (4 functions) → `tmux_manager` (hardwired)  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | Moderate                                                                    | No — providers not unit-testable without tmux                     |
| `monitor_events.py` — new module                          | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Low                                                                         | Yes — no internal dependencies, pure data                         |
| `AgentProvider` Protocol (18 methods)                     | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Moderate                                                                    | Mostly — wide surface, but appropriate for this abstraction level |
| `reset_window_polling_state()` facade                     | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — single reset contract for external callers                  |
| `hook.py` ↔ `session_map.py` file-lock protocol           | Behavioral                                                                                            | Cross-process                                                           | Low                                                                         | Yes — low volatility makes unbalanced strength tolerable          |

---

## Issue 1: SessionManager Remains a Dependency Hub

<div class="issue">

**Integration**: 30 handler modules → `session.py:SessionManager` (89 call sites)  
**Severity**: Significant — unchanged from prior review

### Knowledge Leakage

`SessionManager` is directly imported and called across every handler in the codebase. The `WindowView` read-only projection introduced in previous work helps for single-field reads, but it only covers the read path and only for handlers that call `view_window()` first. The remaining 89 call sites acquire [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to the session state model: notification modes, approval modes, batch modes, session IDs, provider names, and cwds are all read through individual getter methods rather than through a stable contract.

The `_wire_singletons()` initialization pattern (injecting `_schedule_save` callbacks into five sub-singletons) still exists as a hidden ordering constraint. Any new sub-singleton added to the system inherits this constraint silently.

### Complexity Impact

With 89 call sites across 30 files, a change to the session state model (adding a field, renaming a mode, changing how session IDs are resolved) still requires auditing the entire handler layer. The `WindowView` projection reduces the impact for the fields it covers, but it needs to cover all commonly-read fields before it materially reduces the coupling breadth.

### Cascading Changes

Adding a new per-window setting (e.g., `verbosity_mode`) still requires: a field in `WindowState`, a getter/setter in `SessionManager`, serialization changes in `session.py`, and additions in each handler that needs the setting. The `WindowView` only helps if `batch_mode` (and future additions) are consistently read through it rather than via direct `session_manager.get_*()` calls.

### Recommended Improvement

Continue the `WindowView` expansion already begun in this pass. The next step is to add getters currently called directly on `session_manager` (`get_approval_mode`, `get_session_id_for_window`) to `WindowView`, and migrate handlers that call `view_window()` to use the view fields. The goal is to reduce the number of files that import `session_manager` at all. Target the 10 highest-call-count files first (`sync_command.py`, `recovery_callbacks.py`, `transcript_discovery.py`, `resume_command.py`).

</div>

---

## Issue 2: claude_task_state Active Mutations Have No Single Authority

<div class="issue">

**Integration**: `hook_events.py` (5 calls) + `window_tick.py` (3 calls) → `claude_task_state`  
**Severity**: Significant — partially addressed

### Knowledge Leakage

The prior pass successfully consolidated subagent lifecycle mutations (add/remove/clear) and session-end cleanup into `SessionLifecycle`. However, active state mutations triggered by hook events and poll-cycle transitions still reach `claude_task_state` directly:

- `hook_events._handle_notification`: `set_wait_header()`
- `hook_events._handle_stop`: `clear_wait_header()`, `format_completion_text()`
- `hook_events._handle_task_completed`: `mark_task_completed()`, `has_snapshot()`
- `window_tick._apply_active_transition`: `clear_wait_header()`
- `window_tick._update_status`: `set_last_status()`

These five distinct mutation entry points mean that [knowledge of the internal `ClaudeTaskStateStore` API](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) is diffused across two handler modules rather than concentrated in one authority. If `ClaudeTaskStateStore` gains new fields or changes its wait-header model, all five callers must be audited.

### Complexity Impact

The two remaining mutation sites (`hook_events` and `window_tick`) have different triggers: hook events are asynchronous external signals; poll-cycle transitions are synchronous internal state machine steps. This means the shared state is written from two different execution contexts, and the consistency model must be reasoned about across those boundaries. Adding a new hook event that modifies task state requires knowing which existing module to put the mutation in — a non-obvious choice that relies on convention rather than structure.

### Cascading Changes

- Adding a new hook event type that updates task state requires choosing between `hook_events`, `session_lifecycle`, or a new module — no structure guides the choice.
- Changing how `clear_wait_header` semantics work (e.g., adding a reason parameter) requires updates in both `hook_events` and `window_tick`.

### Recommended Improvement

Split the remaining mutations by trigger type. Hook-event-driven mutations (`set_wait_header`, `clear_wait_header` on Stop, `mark_task_completed`) belong in `session_lifecycle` or a thin new `task_state_events.py` coordinator that `hook_events` calls. Poll-cycle mutations (`clear_wait_header` on active transition, `set_last_status`) belong in `window_tick` — these are the monitoring loop's own state updates and are legitimately local. The key insight: not all writes need the same authority; the goal is one authority _per trigger type_, not a single global write lock.

</div>

---

## Issue 3: hook_events Bypasses the Polling Reset Facade

<div class="issue">

**Integration**: `hook_events._handle_session_end` → `terminal_poll_state.clear_seen_status` directly  
**Severity**: Minor

### Knowledge Leakage

`reset_window_polling_state(window_id)` was introduced in this pass precisely to encapsulate the two-step polling reset (`clear_seen_status` + `clear_screen_buffer`). `command_orchestration` correctly uses it. But `hook_events._handle_session_end` at line 302 still calls `terminal_poll_state.clear_seen_status(window_id)` directly, bypassing the facade. This is a single-line bypass, but it means the facade's contract is not enforced — if a third state cell is added to `reset_window_polling_state`, `hook_events` won't pick it up.

### Recommended Improvement

Replace the direct call in `_handle_session_end` with `reset_window_polling_state(window_id)`. One line change — already has the correct import path from the same file's other polling references.

</div>

---

## Issue 4: window_tick.py Has 30 Direct Polling Strategy Calls

<div class="issue">

**Integration**: `window_tick.py` → `terminal_poll_state`, `lifecycle_strategy`, `terminal_screen_buffer` (30 call sites)  
**Severity**: Minor

### Knowledge Leakage

`window_tick.py` is the per-window poll cycle executor — it is architecturally close to the polling strategy objects and legitimately owns most of the interaction with them. However, 30 direct calls to three different singleton objects means `window_tick` has deep [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to the internal structure of `polling_strategies.py`. When a strategy method is renamed or a new state cell is added, `window_tick` is always affected.

The `reset_window_polling_state` facade reduced the coupling from external command handlers. `window_tick` is a different category — it IS the tick executor and owns the polling state machine transitions. The coupling here is high-strength at very low distance (both files are in `handlers/`), which the [balance rule](https://coupling.dev/posts/core-concepts/balance/) tolerates. The issue is not the coupling itself but its dispersion across 30 separate call sites.

### Recommended Improvement

Low priority given the low distance. If `window_tick.py` grows further, consider grouping related state transitions into methods on the strategy objects themselves (e.g., `lifecycle_strategy.complete_dead_window_transition(user_id, thread_id, window_id)` instead of 3–4 separate calls). This reduces the number of external call sites without introducing a new layer.

</div>

---

## Issue 5: Three Deferred-Import Cycles Remain

<div class="issue">

**Integration**: `session.py` ↔ `session_resolver.py`, `session_map.py` ↔ `window_state_store.py` / `thread_router.py`, `session_lifecycle.py` → `session.py` (runtime-only)  
**Severity**: Minor

### Knowledge Leakage

Three bidirectional dependency cycles still exist, each suppressed with function-level deferred imports. The `transcript_reader ↔ session_monitor` cycle from the prior review was broken by `monitor_events.py` — the same technique applies to the remaining three. The pattern: modules that are both state owners and state consumers create the cycle; extracting shared types into dependency-free modules resolves it.

The new `session_lifecycle → session` dependency added in this pass is a unidirectional runtime import (not a cycle), but it's worth monitoring: if `session.py` ever imports `session_lifecycle` at module level, a new cycle forms.

### Recommended Improvement

The same recipe that resolved Issue 5 in the prior pass: identify shared types or interfaces that both sides of each remaining cycle depend on, extract them into a dependency-free module, and the cycle resolves. For the `session.py ↔ session_resolver` cycle: the `ClaudeSession` dataclass used by both is a candidate for extraction into `session_types.py`.

</div>

---

## Issue 6: shell_infra Hardwires tmux_manager in 4 Async Functions

<div class="issue">

**Integration**: `providers/shell_infra.py` → `tmux_manager` (lazy imports in `has_prompt_marker`, `detect_pane_shell`, `_is_interactive_shell`, `setup_shell_prompt`)  
**Severity**: Minor — unchanged from prior review

### Knowledge Leakage

`ClaudeProvider.scrape_current_mode` was fixed in this pass — it now accepts an injectable `capture_fn`. The four `shell_infra` async functions follow the identical pattern but were not updated. Any test that exercises `setup_shell_prompt()` must mock the entire `tmux_manager` module or use a real tmux session.

### Recommended Improvement

The same injectable parameter pattern applied to `claude.py` works here. `setup_shell_prompt(window_id, *, send_keys_fn=None, capture_fn=None)` with defaults pointing to `tmux_manager.send_keys` and `tmux_manager.capture_pane`. The pattern is now demonstrated in the codebase — apply it to `shell_infra` in the next pass.

</div>

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
