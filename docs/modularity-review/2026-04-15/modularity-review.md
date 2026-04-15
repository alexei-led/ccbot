# Modularity Review — ccgram

**Date:** 2026-04-15  
**Scope:** Entire codebase (`src/ccgram/` — 90 Python files, ~18,000 lines)  
**Model:** Balanced Coupling (Strength × Distance × Volatility)

---

## Executive Summary

| Dimension                 | Score    | Notes                                                                                                                  |
| ------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Cohesion**              | 6/10     | Most modules focused; `window_tick.py` (616 lines, 24 imports) and `hook_events.py` (15 modules) are outliers          |
| **Encapsulation**         | 4/10     | Private functions accessed cross-module; internal dicts bypassed in 5 places                                           |
| **Coupling Strength**     | 6/10     | Mostly functional coupling; `session_map` → `window_store` is intrusive; `status_bubble` knows task schema internals   |
| **Subsystem Boundaries**  | 5/10     | Three confirmed layer violations: display→polling, hook→polling, poll→session-monitor                                  |
| **Dependency Graph**      | 5/10     | Active circular dependency (shell_capture ↔ shell_commands); ~6 structural cycles suppressed via deferred imports      |
| **State Ownership**       | 6/10     | `parse_session_map` duplicated across two files; `window_store.window_states` public dict bypassed by external callers |
| **AI Context Efficiency** | 5/10     | `window_tick.py` requires loading 24 modules to safely edit; hook event changes cascade into 15 modules                |
| **Overall**               | **5/10** | Active refactoring trajectory is positive; five high-priority structural issues remain                                 |

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
| Core state            | `session.py`, `thread_router.py`, `window_state_store.py`, `session_map.py`                                        | Supporting — schema-stable             |
| Shell provider        | `providers/shell_infra.py`, `handlers/shell_commands.py`, `handlers/shell_capture.py`, `handlers/shell_context.py` | Supporting — actively developed        |
| Inter-agent messaging | `mailbox.py`, `msg_cmd.py`, `handlers/msg_broker.py`, `handlers/msg_spawn.py`, `handlers/msg_telegram.py`          | Core — new feature under development   |

**Strengths identified:**

- `message_task.py` — pure frozen dataclass sum type, zero project imports, textbook data contract
- `polling_coordinator.py` — 87 lines, thin orchestration shell, recent successful refactor
- `spawn_request.py` — pure functions and dataclasses, no handler dependencies
- `providers/__init__.py` — clean lazy-registration facade, no circular deps
- The recent session_monitor refactoring (extracting EventReader, IdleTracker, SessionLifecycle, TranscriptReader) reduced the monolith by 42% — demonstrates the team's ability to improve modularity

---

## Issues

### Issue 1 — `window_tick.py` is a God Module for Per-Window Polling (Critical)

**Files:** `handlers/window_tick.py` (616 lines)  
**What knowledge is shared:** window_tick imports from 24 distinct modules and makes 6 identical calls to `get_provider_for_window(window_id, provider_name=session_manager.get_window_provider(window_id))`.

**Coupling analysis:**

- **Strength:** HIGH — imports private functions (`_has_insert_indicator`, `notify_vim_insert_seen`) from `tmux_manager`; reads `get_active_monitor()` from `session_monitor`; orchestrates interactive UI, recovery, transcript discovery, status display, passive shell relay, and multi-pane scanning all in one file
- **Distance:** LOW (same service, adjacent modules)
- **Volatility:** HIGH — per-window behavior is the core of every new feature; every provider capability change, new UI element, and status update passes through here

**Balance:** HIGH strength × LOW distance = technically balanced by the rule. But the private API access (`_has_insert_indicator`) creates an intrusive coupling that violates encapsulation regardless of distance.

**The 6-call duplication (window_tick.py lines 152, 205, 226, 325, 448, 557):**

```python
# This pattern appears 6 times with no variation:
provider = get_provider_for_window(
    window_id, provider_name=session_manager.get_window_provider(window_id)
)
```

Each copy is a context-loading event for an AI making a change in this file. A helper `_get_provider(window_id)` would reduce blast radius.

**Private API access (window_tick.py:335):**

```python
from ..tmux_manager import _has_insert_indicator, notify_vim_insert_seen
```

`_has_insert_indicator` is a private function. This creates a hidden contract: refactoring vim-insert detection in `tmux_manager` will silently break `window_tick`. Either promote these to public API or move the vim detection logic into the polling layer.

**Why it matters for AI context efficiency:** Any change to per-window polling behavior requires loading window_tick.py's full context alongside 24 other modules. The 6 duplicated provider calls mean every reader must resolve the same pattern 6 times.

**Recommendation:** Extract a `VimInsertDetector` or make `_has_insert_indicator` and `notify_vim_insert_seen` public. Extract the repeated `_get_provider(window_id)` helper. Consider whether the passive shell relay logic (currently embedded) could move to `shell_capture.py`.

---

### Issue 2 — `hook_events.py` Has 15 Module Dependencies, Half Hidden (High)

**Files:** `handlers/hook_events.py` (385 lines)  
**What knowledge is shared:** This file dispatches Claude Code hook events (Stop, StopFailure, SessionEnd, Notification, SubagentStart/Stop, TeammateIdle, TaskCompleted) to the handler layer. To do so, it imports from 15 distinct modules — 9 of which are deferred (inside function bodies).

**Coupling analysis:**

- **Strength:** HIGH — directly calls `claude_task_state.set_wait_header()`, `format_completion_text()`, `mark_task_completed()`; calls `run_broker_cycle()` from `periodic_tasks` immediately after a Stop event; calls `terminal_poll_state.clear_seen_status()` from `polling_strategies`
- **Distance:** LOW (same service)
- **Volatility:** HIGH — hook events are the primary mechanism for real-time agent feedback; new hook types are added as Claude Code evolves; each new event requires changes here

**Balance:** HIGH strength × HIGH volatility × LOW distance → UNBALANCED. This is the highest-volatility module in the codebase and it has the broadest import surface.

**The deferred import pattern hides the real dependency graph:**

```python
# Inside _handle_stop():
from .periodic_tasks import run_broker_cycle
run_broker_cycle(bot, user_id, thread_id)
```

This crosses a subsystem boundary: hook_events (event dispatch) reaches into periodic_tasks (polling infrastructure). The Stop event handler should emit a signal (e.g., via the existing callback registry or a simple queue) rather than directly invoking polling infrastructure.

**The same module imported 4 times in different functions:**

```python
# hook_events.py:60, :129, :236, :315 — all deferred
from .message_queue import enqueue_status_update
```

This is hidden fan-out: static analysis tools and AI context scanners will only see this import if they inspect all function bodies.

**Why it matters for AI context efficiency:** Adding a new hook event type requires understanding hook_events.py + its 15 dependencies, half of which are only visible at runtime. A developer (human or AI) must scan every function body to build the full dependency picture.

**Recommendation:** Move `asyncio` to a top-level import (it's stdlib, no circular risk). Consolidate deferred `message_queue` imports to top-level. Replace the `run_broker_cycle` direct call with a registered callback or a simple event emission to break the hook→polling boundary crossing.

---

### Issue 3 — `session_map.py` Bypasses `WindowStateStore` and `ThreadRouter` APIs (High)

**Files:** `session_map.py`, `window_state_store.py`, `thread_router.py`  
**What knowledge is shared:** `session_map.py` accesses the internal `window_states` dict of `WindowStateStore` directly, bypassing the store's own rich API.

**Evidence (5 direct dict accesses):**

```python
session_map.py:194  for w in window_store.window_states          # iteration
session_map.py:199  window_store.window_states[w].session_id     # field read
session_map.py:204  del window_store.window_states[wid]          # deletion
session_map.py:294  if window_id in window_store.window_states:  # membership test
session_map.py:295  del window_store.window_states[window_id]    # deletion
```

And for `ThreadRouter`:

```python
session_map.py:188  for user_bindings in thread_router.thread_bindings.values()
```

**Coupling analysis:**

- **Strength:** HIGH (intrusive) — reads and modifies internal data structures directly, bypassing mutation methods
- **Distance:** LOW (same service)
- **Volatility:** MEDIUM — `WindowState` schema is relatively stable; `thread_bindings` dict structure is stable

**Balance:** The low volatility partially excuses this, but `window_store` has `clear_window_session()`, `prune_stale_window_states()`, and `get_window_state()` — all purpose-built for exactly these operations. The direct access creates an implicit contract on the dict's shape that the store's API would abstract away.

**Root cause:** `window_states` is declared as a public attribute (no underscore) on `WindowStateStore`, inviting direct access. This is a leaking abstraction by design.

**Why it matters:** If `WindowStateStore` ever needs to add side effects on window removal (e.g., invalidating a cache, notifying a listener), the 5 direct deletions in `session_map.py` will silently bypass that logic.

**Recommendation:** Make `window_states` private (`_window_states`). Add `remove_window(window_id)` and `iter_window_ids()` methods to `WindowStateStore`. Replace direct dict access in `session_map.py` with these methods. Similarly, expose `ThreadRouter.iter_bound_windows()` rather than allowing direct iteration of `thread_bindings`.

---

### Issue 4 — `parse_session_map` Logic Duplicated Across Two Files (Medium)

**Files:** `session.py` (lines 50–88), `session_map.py` (lines 34–72)  
**What knowledge is shared:** Both files define `parse_session_map()` and `parse_emdash_provider()` with identical implementations.

**Evidence:**

- `session.py:50` — `def parse_session_map(raw: dict[str, Any], prefix: str) -> dict[str, dict[str, str]]:`
- `session_map.py:34` — same function signature and body
- `session.py:80` — `def parse_emdash_provider(session_name: str) -> str:`
- `session_map.py:72` — same

**Coupling analysis:**

- **Strength:** HIGH (code duplication — identical logic in two places)
- **Distance:** LOW
- **Volatility:** MEDIUM — emdash session name parsing would need to change if emdash's naming convention changes; duplicate means two change sites

**Balance:** Duplication is a cohesion failure. `session_map.py` is the canonical home for session-map parsing. `session.py` imports from `session_map.py` but still defines its own copies.

**Why it matters:** A change to the emdash session name format (e.g., a new `-chat-` variant) must be applied to both copies or behavior diverges. For an AI making a targeted change, discovering the duplicate requires searching for both definition sites.

**Recommendation:** Delete `parse_session_map` and `parse_emdash_provider` from `session.py`. Update `session_monitor.py` (which imports `parse_session_map` from `session`) to import from `session_map.py` directly.

---

### Issue 5 — `status_bubble.py` Crosses Subsystem Boundary into Polling Layer (Medium)

**Files:** `handlers/status_bubble.py`, `handlers/polling_strategies.py`  
**What knowledge is shared:** `status_bubble.py` (message delivery subsystem) imports `terminal_screen_buffer` from `polling_strategies.py` (polling subsystem) to check `is_rc_active(window_id)` when building the status keyboard.

**Evidence (status_bubble.py:189–195):**

```python
from .polling_strategies import terminal_screen_buffer

keyboard = build_status_keyboard(
    window_id,
    history=history,
    rc_active=terminal_screen_buffer.is_rc_active(window_id),
)
```

**Coupling analysis:**

- **Strength:** LOW-MEDIUM (single function call for a boolean flag)
- **Distance:** MEDIUM (different subsystems: display/delivery vs. polling state)
- **Volatility:** LOW (RC badge is a stable feature)

**Balance:** Low volatility makes this tolerable, but the cross-subsystem dependency is architecturally surprising. `is_rc_active()` is polling state — `status_bubble` shouldn't know it exists.

**A second issue in the same file:** `status_bubble.py:138–162` accesses 4 internal fields of `ClaudeTaskSnapshot` (`total_count`, `done_count`, `open_count`, `items`). This model coupling means any change to the snapshot's field names or types will break status display.

**Why it matters for AI context efficiency:** Understanding status_bubble's keyboard layout now requires loading `polling_strategies.py`. A change to RC detection logic must check whether `status_bubble` is affected.

**Recommendation:** Pass `rc_active: bool` as a parameter to `build_status_keyboard()`. The caller (which already knows the polling state) supplies it — status_bubble remains blind to how it's determined. For the snapshot coupling: consider adding a `format_task_summary() -> str` method to `ClaudeTaskSnapshot` or `ClaudeTaskState` to encapsulate the display logic.

---

### Issue 6 — `shell_capture ↔ shell_commands` Mutual Circular Dependency (Medium)

**Files:** `handlers/shell_capture.py`, `handlers/shell_commands.py`, `handlers/shell_context.py`  
**What knowledge is shared:** `shell_capture._maybe_suggest_fix()` calls `shell_commands.show_command_approval()` via a deferred runtime import. `shell_commands` imports from `shell_context` (which was extracted to break an earlier cycle). The extraction broke the static cycle but the runtime mutual dependency persists.

**Coupling analysis:**

- **Strength:** HIGH — mutual functional dependency where each module calls the other's logic
- **Distance:** LOW (same package, adjacent files)
- **Volatility:** MEDIUM — shell NL-command flow evolves; error suggestion UX may change

**Balance:** HIGH strength × LOW distance = technically balanced. But the circular call creates a hidden runtime coupling that static analysis (including AI file readers) cannot see without executing the code.

**The `asyncio.create_subprocess_exec` duplication in shell_capture:**

```python
# shell_capture.py calls tmux directly, bypassing tmux_manager:
proc = await asyncio.create_subprocess_exec("tmux", "capture-pane", ...)
```

This duplicates tmux interaction logic that lives in `tmux_manager.py`, creating two independent tmux access paths.

**Recommendation:** Introduce a `CommandApprovalCallback` protocol or callable type. `shell_capture` accepts this as a constructor/call parameter rather than importing `shell_commands` at runtime. This eliminates the circular dependency architecturally. For the tmux bypass: route `capture-pane` calls through `tmux_manager`.

---

## Summary Matrix

| Issue                                         | Files Affected                                           | Strength | Volatility | Priority |
| --------------------------------------------- | -------------------------------------------------------- | -------- | ---------- | -------- |
| window_tick.py god module + private API       | window_tick.py, tmux_manager.py                          | HIGH     | HIGH       | Critical |
| hook_events.py broad imports + layer crossing | hook_events.py, periodic_tasks.py, polling_strategies.py | HIGH     | HIGH       | High     |
| session_map bypasses store APIs               | session_map.py, window_state_store.py, thread_router.py  | HIGH     | MEDIUM     | High     |
| parse_session_map duplicated                  | session.py, session_map.py                               | HIGH     | MEDIUM     | Medium   |
| status_bubble crosses into polling layer      | status_bubble.py, polling_strategies.py                  | LOW      | LOW        | Medium   |
| shell_capture ↔ shell_commands circular       | shell_capture.py, shell_commands.py                      | HIGH     | MEDIUM     | Medium   |

---

## What Is Working Well

| Pattern              | Where                               | Why It Works                                                                           |
| -------------------- | ----------------------------------- | -------------------------------------------------------------------------------------- |
| Data contract module | `message_task.py`                   | Pure frozen dataclasses, zero project imports — any module can import without risk     |
| Thin orchestrator    | `polling_coordinator.py` (87 lines) | Delegates all work, no logic leakage — result of recent successful refactoring         |
| Clean data ownership | `spawn_request.py`                  | Pure CRUD with no handler/Telegram/config dependencies                                 |
| Provider facade      | `providers/__init__.py`             | Lazy registration avoids circular imports; detection/factory/launch cleanly separated  |
| Registry pattern     | `topic_state_registry.py`           | Self-registration decorator replaces 14+ lazy imports in cleanup.py                    |
| Shell extraction     | `shell_context.py`                  | Correctly extracted to break static circular dependency (though runtime cycle remains) |

---

## Recommended Priorities

1. **Promote or relocate private tmux functions** in `window_tick.py` — this is the clearest encapsulation violation with the widest blast radius per change (window_tick touches 24 modules)
2. **Extract `_get_provider(window_id)` helper** in `window_tick.py` — eliminates 6 duplicate 3-line expressions, reduces reading burden for AI-assisted changes
3. **Delete `parse_session_map` duplicate** from `session.py` — one-line fix with zero risk; reduces emdash change-site count from 2 to 1
4. **Make `window_store.window_states` private** — forces session_map.py to use the store's existing `clear_window_session()` and `prune_stale_window_states()` methods
5. **Pass `rc_active` as a parameter to `build_status_keyboard()`** — cleanly severs the status_bubble → polling_strategies dependency
