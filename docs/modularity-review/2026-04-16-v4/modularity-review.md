# Modularity Review

**Scope**: Entire ccgram codebase — fourth pass, 2026-04-16  
**Date**: 2026-04-16 (v4 — follows `2026-04-16/`, `-v2/`, and `-v3/`)

## Executive Summary

ccgram is a single-process Python bot (~47k lines) that routes Telegram messages to AI coding agent CLIs running in tmux panes. Three refactoring passes have moved the overall modularity score from **4.8 to 5.6/10** (+0.8). The third pass was incremental cleanup: four redundant read patterns were replaced with `WindowView` fields, and two new accessor methods (`window_count`, `iter_window_ids`) eliminated direct `window_states` dict access from handler modules.

The score holds at **5.6/10** — this pass addressed low-hanging fruit within the existing architecture rather than making structural changes. The `SessionManager` dependency hub (85 call sites across 30 handler files) remains the dominant [coupling](https://coupling.dev/posts/core-concepts/coupling/) issue. Every other dimension is either at its natural floor (acceptable given low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/)) or blocked by this single bottleneck. The codebase is now at the point of diminishing returns for targeted fixes: the next meaningful improvement requires a dedicated pass to migrate the 10 highest-call-count handlers to read through `WindowView` exclusively.

## Four-Version Progression

| Dimension                                                                             | v1 (baseline) | v2 (+0.6)  | v3 (+0.2)  | v4 (this)  | Net Δ    |
| ------------------------------------------------------------------------------------- | ------------- | ---------- | ---------- | ---------- | -------- |
| Encapsulation / Information Hiding                                                    | 4/10          | 5/10       | 6/10       | 6/10       | +2       |
| Cohesion                                                                              | 5/10          | 5/10       | 5/10       | 5/10       | —        |
| [Coupling](https://coupling.dev/posts/core-concepts/coupling/) Discipline             | 4/10          | 5/10       | 5/10       | 5/10       | +1       |
| Contract Stability                                                                    | 6/10          | 6/10       | 6/10       | 6/10       | —        |
| Testability                                                                           | 5/10          | 6/10       | 7/10       | 7/10       | +2       |
| [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) Alignment | 4/10          | 5/10       | 5/10       | 5/10       | +1       |
| Module Size Distribution                                                              | 6/10          | 6/10       | 6/10       | 6/10       | —        |
| Dependency Direction                                                                  | 4/10          | 5/10       | 5/10       | 5/10       | +1       |
| **Overall**                                                                           | **4.8/10**    | **5.4/10** | **5.6/10** | **5.6/10** | **+0.8** |

## What Was Resolved This Pass

| Change                                                                      | Files | Effect                                                                                                            |
| --------------------------------------------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------- |
| `restore_command.py` — `get_approval_mode()` → `view.approval_mode`         | 1     | Eliminated redundant read where `view_window()` was already in scope                                              |
| `recovery_callbacks.py` — `get_window_provider()` → `view.provider_name`    | 1     | Same pattern; view guaranteed non-None by cwd guard                                                               |
| `recovery_callbacks.py` — two getters consolidated into one `view_window()` | 1     | Two `session_manager` calls → one, yielding both `provider_name` and `approval_mode`                              |
| `resume_command.py` — same two-getter consolidation                         | 1     | Identical pattern                                                                                                 |
| `session.py` — added `window_count` property + `iter_window_ids()`          | 1     | New [contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) accessors for handler use |
| `msg_spawn.py` — `window_states` dict → `window_count` property             | 1     | Eliminated direct dict access + `check_max_windows` indirection                                                   |
| `sync_command.py` — `window_states.keys()` → `iter_window_ids()`            | 1     | Eliminated direct dict key access                                                                                 |

**Net `session_manager` call site reduction**: 89 → 85 (–4 in handlers)

## What Remains — Diminishing Returns

The refactoring across all four passes has resolved every issue that could be addressed with targeted, localized edits:

| Category                             | v1 status                                                 | v4 status                                              |
| ------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------ |
| Import cycles                        | 4 cycles                                                  | 3 cycles (one broken by `monitor_events.py`)           |
| `claude_task_state` write authority  | 6 uncoordinated sites                                     | 3 trigger-type authorities (by design)                 |
| Polling state encapsulation          | Direct access from 4 handler files                        | Facade (`reset_window_polling_state`) fully adopted    |
| Infrastructure → domain dependencies | `tmux_manager` → `providers` at module level              | Local import only                                      |
| Provider testability                 | All 4 shell_infra functions + claude.py hardwired to tmux | Injectable `capture_fn`/`send_keys_fn` on entry points |
| `SessionManager` read coupling       | 89 call sites, 30 files                                   | 85 call sites, 30 files (–4.5%)                        |

The remaining 85 call sites across 30 files are the **natural floor for targeted fixes**. Reducing this number further requires a different approach: systematically migrating handler files to receive `WindowView` through their call chains rather than importing `session_manager` directly. This is a bulk migration (touching 10+ files) rather than a pattern fix.

## Coupling Overview

| Integration                                                             | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 30 handler modules → `SessionManager` (85 call sites)                   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — dominant remaining issue; ceiling for score improvement   |
| `window_tick` → `polling_strategies` internals (30 calls)               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service, low distance                                              | High                                                                        | Tolerable — poll executor legitimately owns these transitions  |
| 3 remaining deferred-import cycles                                      | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bidirectional) | Same service                                                            | High                                                                        | No — masks dependency graph; low priority                      |
| `window_tick` → `claude_task_state` (3 poll-cycle mutations)            | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional poll-cycle authority                         |
| `transcript_reader` → `claude_task_state` (2 parse mutations)           | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | Yes — intentional transcript-parse authority                   |
| `hook_events` → `session_lifecycle` (5 facade calls)                    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — named methods are the contract                           |
| `reset_window_polling_state()` — fully adopted                          | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | High                                                                        | Yes — no bypasses                                              |
| `window_count` + `iter_window_ids()` — new this pass                    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Moderate                                                                    | Yes — replaces raw dict access                                 |
| `has_prompt_marker` + `setup_shell_prompt` (injectable)                 | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Moderate                                                                    | Yes — injectable callables                                     |
| `monitor_events.py`, `IdleTracker`, `event_reader`, `providers/base.py` | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Low/Moderate                                                                | Yes — design exemplars                                         |

---

## Issue 1: SessionManager Dependency Hub — Natural Floor Reached

<div class="issue">

**Integration**: 30 handler modules → `session.py:SessionManager` (85 call sites)  
**Severity**: Significant — reduced from 89 to 85 call sites across four passes

### Knowledge Leakage

`SessionManager` is still directly imported by every handler module. The `WindowView` [contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) now covers 10 fields and is used correctly by handlers that call `view_window()`, but the remaining call sites use getter methods (`get_window_provider`, `get_approval_mode`, `get_notification_mode`, `get_session_id_for_window`) and write methods (`set_window_provider`, `set_window_approval_mode`, `set_window_cwd`) that expose the internal state model directly.

The four-pass series has eliminated every redundant read (cases where a `view_window()` call already existed and a separate getter was called on the same window). What remains are:

- **13 standalone `get_window_provider` calls** — each in a context where no prior `view_window()` exists, so switching requires adding a new view call + None guard
- **11 `set_window_provider` calls** — legitimate writes that belong on `SessionManager`
- **18 `view_window` calls** — correct pattern usage
- **~43 infrastructure/lifecycle calls** — the permanent floor

### Complexity Impact

The 85-call breadth means any session state model change still requires auditing across all 30 handler files. However, the [accidental volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) from this coupling is now lower than at baseline: `WindowView` covers the most commonly read fields, `session_lifecycle` owns all mutation-authority methods for hook events, and `reset_window_polling_state` hides polling internals. A developer adding a new per-window field now has a clear contract path: add it to `WindowView`, use it through `view_window()`, mutate through a named `session_lifecycle` method.

### Recommended Next Step

The targeted-fix approach has reached diminishing returns. The next meaningful improvement is a **bulk migration pass**: for each of the 10 highest-call-count handler files, replace all standalone `get_window_provider(wid)` / `get_approval_mode(wid)` calls with `view = session_manager.view_window(wid); view.field if view else default`. This is mechanical work (one pattern applied repeatedly) that would convert ~13 [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) reads to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) reads through `WindowView`.

The trade-off: each converted call site gains a None guard (the getter methods hide this with defaults). The benefit: those handler files can eventually stop importing `session_manager` entirely, reading everything through `WindowView` passed as a parameter.

</div>

---

## Issue 2: Three Deferred-Import Cycles Remain

<div class="issue">

**Integration**: `session.py` ↔ `session_resolver.py`, `session_map.py` ↔ `window_state_store.py` / `thread_router.py`  
**Severity**: Minor — unchanged, low priority

### Knowledge Leakage

Three bidirectional dependency cycles survive, each suppressed by function-level deferred imports. The `monitor_events.py` extraction in v2 demonstrated the fix pattern and broke the `transcript_reader ↔ session_monitor` cycle. The same technique applies to the remaining three but they are not blocking any feature work or causing test isolation problems.

### Recommended Improvement

Address opportunistically when touching the affected modules for other reasons. The recipe is proven: identify shared types, extract to a dependency-free module, both sides import from it.

</div>

---

## What Worked: Retrospective on the Four-Pass Series

The [Balanced Coupling](https://coupling.dev/posts/core-concepts/balance/) model guided the prioritization across all four passes. Here is what was accomplished and what each dimension shows:

| Dimension                     | What moved it                                                                                                              | What blocks further improvement                                                                          |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Encapsulation** (+2)        | `session_lifecycle` write authority, `reset_window_polling_state` facade, `WindowView.batch_mode`, injectable `capture_fn` | `SessionManager` getter proliferation across 30 files                                                    |
| **Testability** (+2)          | Injectable `capture_fn`/`send_keys_fn` in `claude.py` + `shell_infra.py`, `monitor_events.py` extraction                   | `shell_infra` internal functions still hardwire tmux for `detect_pane_shell` and `_is_interactive_shell` |
| **Coupling Discipline** (+1)  | `tmux_manager` module-level `providers` import removed, `transcript_reader ↔ session_monitor` cycle broken                 | 3 remaining deferred-import cycles                                                                       |
| **Dependency Direction** (+1) | `tmux_manager` → `providers` inverted dependency resolved                                                                  | `providers/claude.py` still lazily imports `tmux_manager` (tolerable)                                    |
| **Volatility Alignment** (+1) | Mutations consolidated per trigger type; facade seals polling internals                                                    | `SessionManager` read coupling in volatile handler layer                                                 |
| **Cohesion** (=)              | —                                                                                                                          | No module splits needed; large files are legitimate (parser, tmux manager)                               |
| **Contract Stability** (=)    | `WindowView`, `reset_window_polling_state`, `window_count`, `iter_window_ids` all stable                                   | Already at 6/10; further gains require protocol-level contracts                                          |
| **Module Size** (=)           | —                                                                                                                          | `tmux_manager.py` (1175 lines) is infrastructure; splitting adds complexity without reducing coupling    |

The overall trajectory — **4.8 → 5.4 → 5.6 → 5.6** — shows the characteristic diminishing-returns curve of incremental refactoring. The jump from 4.8 to 5.4 (v1→v2) came from addressing four distinct coupling patterns in parallel. Each subsequent pass had fewer high-impact targets. The codebase is now at a stable plateau where the remaining issues are either Minor (tolerable) or require a different class of effort (bulk handler migration).

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
