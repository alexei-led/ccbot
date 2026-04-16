# Modularity Review

**Scope**: Entire ccgram codebase — third pass, 2026-04-16  
**Date**: 2026-04-16 (v3 — follows `2026-04-16/` and `2026-04-16-v2/`)

## Executive Summary

ccgram is a single-process Python bot (~47k lines) that routes Telegram messages to AI coding agent CLIs running in tmux panes. Two consecutive refactoring passes have moved the overall modularity score from **4.8 to 5.6/10** (+0.8 over the baseline). The second pass completed the `claude_task_state` write-authority work: `hook_events.py` now has zero direct mutations — all hook-triggered task state changes route through `session_lifecycle` via three new named methods. Mutation authority is now cleanly partitioned by trigger type across three modules. The polling reset facade bypass was also closed, and `shell_infra.py` gained the same injectable-parameters pattern already present in `claude.py`.

The dominant remaining issue — `SessionManager` accessed directly from 30 handler files at 89 call sites — was not addressed in either pass and remains the single largest driver of [coupling](https://coupling.dev/posts/core-concepts/coupling/) density in the codebase. Addressing it is the highest-impact next step. Three deferred-import cycles and `window_tick.py`'s direct polling calls are minor issues that are tolerable at their current [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/).

## Three-Version Progression

| Dimension                                                                             | v1 (Apr 15) | v2 (Apr 16) | v3 (Apr 16) | Net Δ    |
| ------------------------------------------------------------------------------------- | ----------- | ----------- | ----------- | -------- |
| Encapsulation / Information Hiding                                                    | 4/10        | 5/10        | 6/10        | +2       |
| Cohesion                                                                              | 5/10        | 5/10        | 5/10        | —        |
| [Coupling](https://coupling.dev/posts/core-concepts/coupling/) Discipline             | 4/10        | 5/10        | 5/10        | +1       |
| Contract Stability                                                                    | 6/10        | 6/10        | 6/10        | —        |
| Testability                                                                           | 5/10        | 6/10        | 7/10        | +2       |
| [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) Alignment | 4/10        | 5/10        | 5/10        | +1       |
| Module Size Distribution                                                              | 6/10        | 6/10        | 6/10        | —        |
| Dependency Direction                                                                  | 4/10        | 5/10        | 5/10        | +1       |
| **Overall**                                                                           | **4.8/10**  | **5.4/10**  | **5.6/10**  | **+0.8** |

## What Was Resolved This Pass

| Issue                                                              | Change                                                                                                             | Status      |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ----------- |
| `hook_events` directly mutating `claude_task_state` (5 call sites) | 3 new methods on `SessionLifecycle`: `handle_notification_wait`, `handle_stop_task_state`, `handle_task_completed` | ✅ Resolved |
| Polling reset facade bypass in `_handle_session_end`               | Replaced `terminal_poll_state.clear_seen_status` with `reset_window_polling_state`                                 | ✅ Resolved |
| `has_prompt_marker` hardwires `tmux_manager`                       | Injectable `capture_fn` parameter                                                                                  | ✅ Resolved |
| `setup_shell_prompt` hardwires `tmux_manager`                      | Injectable `capture_fn` + `send_keys_fn` parameters                                                                | ✅ Resolved |
| Dead `_SessionMapError` constant in `session_lifecycle.py`         | Removed along with unused `json` import                                                                            | ✅ Resolved |

## Mutation Authority — Current State

`claude_task_state` is now written from three modules, each owning a distinct trigger type:

| Module              | Trigger type                    | Methods called                                                                                   |
| ------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------ |
| `session_lifecycle` | Hook events + lifecycle cleanup | `set_wait_header`, `clear_wait_header`, `mark_task_completed`, `clear_window`, `clear_subagents` |
| `window_tick`       | Poll-cycle transitions          | `clear_wait_header` (×2), `set_last_status`                                                      |
| `transcript_reader` | Transcript parsing              | `rebuild_from_entries`, `apply_entries`                                                          |

This is the intended end state per the "one authority per trigger type" recommendation from the v2 review. `hook_events.py` is now a read-only consumer of `claude_task_state` (two reads: `format_completion_text`, `has_snapshot`).

## Coupling Overview

| Integration                                                             | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 30 handler modules → `SessionManager` (89 call sites)                   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — dominant remaining issue                                  |
| `window_tick` → `polling_strategies` internals (30 calls)               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service, low distance                                              | High                                                                        | Tolerable — low distance balances high strength                |
| 3 remaining deferred-import cycles                                      | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bidirectional) | Same service                                                            | High                                                                        | No — masks true dependency graph                               |
| `window_tick` → `claude_task_state` (3 mutations)                       | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional poll-cycle authority                         |
| `transcript_reader` → `claude_task_state` (2 mutations)                 | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional transcript-parse authority                   |
| `hook_events` → `session_lifecycle` (5 method calls)                    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — named facade methods are the contract                    |
| `session_lifecycle` authority methods (8 methods total)                 | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — single authority per trigger type                        |
| `reset_window_polling_state()` facade                                   | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — fully adopted by all callers                             |
| `has_prompt_marker` + `setup_shell_prompt` (injectable)                 | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Moderate                                                                    | Yes — injectable callables make the boundary explicit          |
| `monitor_events.py`, `IdleTracker`, `event_reader`, `providers/base.py` | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Low/Moderate                                                                | Yes — correctly isolated                                       |

---

## Issue 1: SessionManager Remains a Dependency Hub

<div class="issue">

**Integration**: 30 handler modules → `session.py:SessionManager` (89 call sites)  
**Severity**: Significant — unchanged across all three passes

### Knowledge Leakage

`SessionManager` is directly imported by every handler module. Despite the `WindowView` read-only projection (which covers `window_id`, `cwd`, `provider_name`, `approval_mode`, `notification_mode`, `batch_mode`, `transcript_path`, `window_name`, `session_id`, `external`), the 89 call sites still acquire [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to specific `SessionManager` methods: `get_window_provider`, `get_session_id_for_window`, `clear_window_session`, `prune_stale_state`, `resolve_stale_ids`, `set_window_provider`, `set_window_cwd`, and others.

The `_wire_singletons()` initialization pattern — which injects a `_schedule_save` callback into five sub-singletons at startup — still creates a hidden ordering constraint. Any new sub-singleton must be wired into this chain or will silently break persistence.

### Complexity Impact

With 89 call sites across 30 files, any change to the session state model requires an audit of the entire handler layer. The `WindowView` contract covers the read path for the fields it includes, but modules that call methods not yet on `WindowView` (`get_session_id_for_window`, `get_window_provider`) still depend on the `SessionManager` API directly. The breadth of this coupling is the primary reason the Encapsulation and Volatility Alignment scores have not moved above 6 despite two refactoring passes.

### Cascading Changes

- Adding a new per-window mode or setting requires: field in `WindowState`, getter/setter in `SessionManager`, serialization changes, and additions across the handler modules that consume the setting.
- Renaming an existing mode (e.g., `notification_mode` → `notify_mode`) requires updating all 30 handler files, not just `session.py`.
- The 10 highest-call-count handlers (`sync_command.py`, `recovery_callbacks.py`, `transcript_discovery.py`, `resume_command.py`, `restore_command.py`, `directory_callbacks.py`, `message_routing.py`, `window_tick.py`, `topic_orchestration.py`, `topic_lifecycle.py`) account for 61 of the 89 call sites.

### Recommended Improvement

Extend `WindowView` to cover the remaining commonly-read fields (`session_id`, `approval_mode` is already there). Then migrate the 10 highest-call-count handlers to use `view_window()` for reads instead of importing `session_manager`. The goal is to reduce the number of files that import `session_manager` at all — not to eliminate all calls, but to limit direct `session_manager` imports to modules that genuinely need to write state. Reads should go through `WindowView`; writes should go through narrow command methods. This converts [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) at the read boundary.

The trade-off: migrating 10 files is a day's work with mechanical changes. The benefit compounds with every subsequent feature addition — a new field added to `WindowState` only needs to appear in `WindowView`, not be tracked across 30 handler call sites.

</div>

---

## Issue 2: Three Deferred-Import Cycles Remain

<div class="issue">

**Integration**: `session.py` ↔ `session_resolver.py`, `session_map.py` ↔ `window_state_store.py` / `thread_router.py`  
**Severity**: Minor — one cycle was broken in v1 (`transcript_reader ↔ session_monitor`), three remain

### Knowledge Leakage

Three bidirectional dependency cycles survive, each suppressed by function-level deferred imports. The suppression works at runtime but makes the true dependency graph invisible to static analysis tools. `session_map.py` is the most entangled: it defers imports of both `window_store` and `thread_router` inside nearly every method, meaning its full dependency set cannot be determined from the file's import block alone.

The `monitor_events.py` extraction in v1 demonstrated the fix: extract shared types into a dependency-free module and both sides of the cycle can import from it without circular dependency. The same recipe applies here.

### Recommended Improvement

For the `session.py ↔ session_resolver` cycle: the `ClaudeSession` dataclass (4 fields, zero internal dependencies) is the shared type. Extract it to `session_types.py`. `session.py` imports `ClaudeSession` from `session_types`; `session_resolver.py` defines and exports `session_resolver` while importing `ClaudeSession` from `session_types`. The cycle dissolves because neither module needs to import the other's singleton.

For `session_map.py` ↔ `window_state_store` / `thread_router`: identify the shared data types used in `session_map.py`'s method signatures and extract them to a dependency-free module. This is more involved but follows the same pattern.

</div>

---

## Issue 3: window_tick Has 30 Direct Polling Strategy Calls

<div class="issue">

**Integration**: `window_tick.py` → `terminal_poll_state`, `lifecycle_strategy`, `terminal_screen_buffer` (30 call sites)  
**Severity**: Minor — tolerable given low distance, flagged for awareness

### Knowledge Leakage

`window_tick.py` is the per-window poll cycle executor and its relationship to `polling_strategies.py` is architecturally close. The [balance rule](https://coupling.dev/posts/core-concepts/balance/) tolerates high [integration strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/). However, 30 separate call sites to three different singletons means each polling strategy refactoring touches `window_tick` in multiple places.

`hook_events.py` no longer bypasses the `reset_window_polling_state` facade, so the "one call site for external resets" contract is now clean. The 30 calls in `window_tick` are legitimately internal — `window_tick` IS the poll executor and owns these transitions.

### Recommended Improvement

Low priority. If `window_tick.py` grows further, group related state transitions into compound methods on the strategy objects (e.g., `lifecycle_strategy.complete_dead_window_transition(user_id, thread_id, window_id)` instead of 3–4 separate calls). This reduces call-site count without adding a new architectural layer. Address opportunistically during feature work on the polling subsystem.

</div>

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
