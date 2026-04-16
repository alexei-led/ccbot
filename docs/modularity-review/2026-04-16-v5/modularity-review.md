# Modularity Review

**Scope**: Entire ccgram codebase — fifth pass, 2026-04-16  
**Date**: 2026-04-16 (v5 — final review of the refactoring series)

## Executive Summary

ccgram is a single-process Python bot (~47k lines) that routes Telegram messages to AI coding agent CLIs running in tmux panes. Four refactoring passes have moved the overall modularity score from **4.8 to 6.3/10** (+1.5). The final pass — extracting `window_query.py` — was the structural breakthrough that broke through the 5.6 plateau: handler files importing `SessionManager` dropped from 30 to 15 (–50%), and call sites from 85 to 57 (–33%). The god-object is now split along its natural read/write boundary: `window_query` owns reads, `session_lifecycle` owns mutations, and `SessionManager` is retained only as the coordinator for writes, lifecycle operations, and session resolution.

The codebase has moved from "needs attention" to **"healthy with known debt"**. No Significant or Critical issues remain. The three Minor issues — 15 handler files that still import `SessionManager`, 3 deferred-import cycles, and `window_tick`'s 30 polling strategy calls — are all either at their natural floor (legitimate consumers) or tolerable at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/). The refactoring series is complete.

## Five-Version Progression

| Dimension                                                                             | v1      | v2      | v3      | v4      | v5      | Net Δ    |
| ------------------------------------------------------------------------------------- | ------- | ------- | ------- | ------- | ------- | -------- |
| Encapsulation / Information Hiding                                                    | 4       | 5       | 6       | 6       | **7**   | +3       |
| Cohesion                                                                              | 5       | 5       | 5       | 5       | 5       | —        |
| [Coupling](https://coupling.dev/posts/core-concepts/coupling/) Discipline             | 4       | 5       | 5       | 5       | **6**   | +2       |
| Contract Stability                                                                    | 6       | 6       | 6       | 6       | **7**   | +1       |
| Testability                                                                           | 5       | 6       | 7       | 7       | 7       | +2       |
| [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) Alignment | 4       | 5       | 5       | 5       | **6**   | +2       |
| Module Size Distribution                                                              | 6       | 6       | 6       | 6       | 6       | —        |
| Dependency Direction                                                                  | 4       | 5       | 5       | 5       | **6**   | +2       |
| **Overall**                                                                           | **4.8** | **5.4** | **5.6** | **5.6** | **6.3** | **+1.5** |

## What This Pass Changed

The `window_query.py` extraction was the single largest architectural change in the series:

| Metric                                     | v1 (baseline) | v4 (pre-extraction) | v5 (post-extraction) | Total Δ |
| ------------------------------------------ | ------------- | ------------------- | -------------------- | ------- |
| Handler files importing `SessionManager`   | 30            | 30                  | **15**               | –50%    |
| `session_manager.*` call sites in handlers | 89            | 85                  | **57**               | –36%    |
| Fully decoupled handler files              | 0             | 0                   | **14**               | +14     |
| Partially migrated handler files           | 0             | 0                   | 3                    | +3      |

**14 handler files now have zero `SessionManager` dependency**:
`file_handler`, `send_command`, `sessions_dashboard`, `shell_context`, `toolbar_callbacks`, `hook_events`, `interactive_ui`, `msg_broker`, `status_bubble`, `tool_batch`, `topic_emoji`, `voice_callbacks`, `window_tick`, `text_handler`

**3 handler files partially migrated** (reads via `window_query`, writes via `session_manager`):
`command_orchestration`, `msg_spawn`, `sync_command`

## Architectural Pattern: Read/Write Boundary Split

The god-object problem was resolved by splitting `SessionManager` along its natural read/write boundary:

| Concern                        | Module                         | [Coupling](https://coupling.dev/posts/core-concepts/coupling/) level                                | Depends on                                |
| ------------------------------ | ------------------------------ | --------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| **Reads**                      | `window_query.py`              | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | `window_state_store` only                 |
| **Hook-event mutations**       | `session_lifecycle.py`         | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | `claude_task_state`, `session_manager`    |
| **Poll-cycle mutations**       | `window_tick.py`               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (intentional) | `claude_task_state`, `polling_strategies` |
| **Transcript-parse mutations** | `transcript_reader.py`         | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (intentional) | `claude_task_state`                       |
| **Writes + lifecycle**         | `session.py`                   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)               | Full state graph                          |
| **Polling state**              | `reset_window_polling_state()` | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | `polling_strategies` internals            |

Handlers that only read window state (`view_window`, `get_window_provider`, `get_approval_mode`, etc.) now import `window_query` — a dependency-free module with [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to `window_state_store`. They never touch `SessionManager`.

## Coupling Overview

| Integration                                                   | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 14 handler modules → `window_query` (read-only)               | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — narrow read contract, no shared mutable state            |
| 15 handler modules → `SessionManager` (writes + lifecycle)    | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Tolerable — legitimate consumers of write/lifecycle API        |
| 3 handler modules → both (partial migration)                  | Mixed                                                                                                 | Same service                                                            | High                                                                        | Tolerable — reads through contract, writes through functional  |
| `hook_events` → `session_lifecycle` (5 facade calls)          | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — named mutation methods                                   |
| `window_tick` → `polling_strategies` (30 calls)               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service, low distance                                              | High                                                                        | Tolerable — poll executor owns transitions                     |
| `window_tick` → `claude_task_state` (3 poll-cycle mutations)  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional trigger-type authority                       |
| `transcript_reader` → `claude_task_state` (2 parse mutations) | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional trigger-type authority                       |
| 3 deferred-import cycles                                      | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bidirectional) | Same service                                                            | High                                                                        | No — masks dependency graph; low priority                      |
| `reset_window_polling_state()` — fully adopted                | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — no bypasses                                              |
| `monitor_events.py`, `IdleTracker`, `event_reader`, `base.py` | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Low/Moderate                                                                | Yes — design exemplars                                         |

---

## Issue 1: 15 Handler Files Still Import SessionManager

<div class="issue">

**Integration**: 15 handler modules → `session.py:SessionManager` (57 call sites)  
**Severity**: Minor — natural floor reached

### Knowledge Leakage

The remaining 15 handler files import `SessionManager` because they genuinely need its write, lifecycle, or query capabilities:

- **7 files** call write methods (`set_window_provider`, `set_window_approval_mode`, `set_window_cwd`, `set_display_name`, `cycle_notification_mode`)
- **4 files** call lifecycle methods (`audit_state`, `prune_stale_state`, `sync_display_names`, `wait_for_session_map_entry`)
- **4 files** call session resolution (`resolve_session_for_window`, `find_users_for_session`, `get_recent_messages`)

These are [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) call sites that cannot be reduced to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) without introducing artificial abstractions. The [balance rule](https://coupling.dev/posts/core-concepts/balance/) tolerates high strength at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) — and all 15 files are same-service, same-team, same-deployment.

### Recommended Improvement

Accept this as the natural floor. The 57 remaining call sites are legitimate consumers of capabilities that only `SessionManager` can provide (state mutation, persistence, session resolution). No further extraction is warranted — it would add abstraction without reducing [shared knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/).

If a future refactoring pass targets this, the highest-leverage move is to extract `set_window_provider` (11 call sites across 7 files) into `session_lifecycle`, since it is semantically a lifecycle operation. But this is optimization, not a fix for a coupling imbalance.

</div>

---

## Issue 2: Three Deferred-Import Cycles Remain

<div class="issue">

**Integration**: `session.py` ↔ `session_resolver.py`, `session_map.py` ↔ `window_state_store.py` / `thread_router.py`  
**Severity**: Minor — unchanged, low priority

### Knowledge Leakage

Three bidirectional dependency cycles survive, each suppressed by function-level deferred imports. The `monitor_events.py` extraction in v2 proved the fix pattern. These cycles are not blocking feature work, test isolation, or IDE navigation in practice.

### Recommended Improvement

Address opportunistically when touching the affected modules. The recipe is proven and mechanical: extract shared types to a dependency-free module.

</div>

---

## Issue 3: window_tick Has 30 Direct Polling Strategy Calls

<div class="issue">

**Integration**: `window_tick.py` → `terminal_poll_state`, `lifecycle_strategy`, `terminal_screen_buffer`  
**Severity**: Minor — tolerable at low distance

### Knowledge Leakage

`window_tick.py` is the per-window poll cycle executor. Its 30 calls to three `polling_strategies` singletons are high-strength [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/), but at very low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) (both files are in `handlers/`, same team, same deployment). The [balance rule](https://coupling.dev/posts/core-concepts/balance/) explicitly tolerates this configuration.

### Recommended Improvement

Low priority. If `window_tick.py` grows further, group related transitions into compound methods on the strategy objects. Address opportunistically.

</div>

---

## Series Retrospective: What Moved Each Score

| Dimension                          | v1→v5                                                                                                                                                 | What moved it                                                    | Current ceiling |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | --------------- |
| **Encapsulation** (4→7, +3)        | `window_query` extraction, `session_lifecycle` write authority, `reset_window_polling_state` facade, `WindowView.batch_mode`, injectable `capture_fn` | 15 legitimate `SessionManager` consumers are the floor           |
| **Coupling Discipline** (4→6, +2)  | `tmux_manager` layer violation removed, `transcript_reader ↔ session_monitor` cycle broken, `window_query` splits read/write boundary                 | 3 remaining import cycles (low priority)                         |
| **Testability** (5→7, +2)          | Injectable `capture_fn`/`send_keys_fn`, `monitor_events.py` extraction, `window_query` simplifies test mocking                                        | `shell_infra` internal functions still hardwire tmux             |
| **Volatility Alignment** (4→6, +2) | Mutations consolidated per trigger type, read coupling in volatile handlers converted to contract coupling                                            | Natural floor — remaining functional coupling is in stable areas |
| **Dependency Direction** (4→6, +2) | `tmux_manager` → `providers` inversion resolved, `window_query` depends only on `window_state_store` (correct direction)                              | `providers/claude.py` still lazily imports `tmux_manager`        |
| **Contract Stability** (6→7, +1)   | `WindowView`, `window_query` functions, `reset_window_polling_state`, `session_lifecycle` facade methods                                              | Already at 7/10; further gains need protocol-level contracts     |
| **Cohesion** (5→5, =)              | —                                                                                                                                                     | Large files are legitimate (parser, tmux manager)                |
| **Module Size** (6→6, =)           | —                                                                                                                                                     | `tmux_manager.py` is infrastructure; splitting adds complexity   |

### The trajectory

```
v1 ──(+0.6)──▸ v2 ──(+0.2)──▸ v3 ──(+0.0)──▸ v4 ──(+0.7)──▸ v5
4.8            5.4            5.6            5.6            6.3
```

The pattern: v1→v2 was the broadest fix (four coupling patterns in parallel, +0.6). v2→v3 consolidated write authority (+0.2). v3→v4 hit diminishing returns with incremental cleanup (+0.0). v4→v5 broke through the plateau with a structural change — extracting the read/write boundary (+0.7). The lesson: incremental fixes converge to a local optimum; breaking through requires an architectural insight (in this case, "reads don't need the coordinator").

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
