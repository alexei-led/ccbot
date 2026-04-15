# Modularity Decouple

## Overview

Address the top 5 modularity issues identified in `docs/modularity-review/2026-04-15/modularity-review.md`.
Root causes: a provider→session layer violation, a god-object session manager, a monolithic session monitor,
an overloaded window tick, and a state-store that knows about provider business logic.

The goal is cleaner boundaries, no circular-import risk, and a reduced blast radius when changing
session state, providers, or polling logic. All changes keep `make check` green throughout.

**Amended after Codex review** (2026-04-15): reordered from `5→1→2→3→4` to `5→2→1→4→3`, added
`get_window_provider()` helper pre-step, fixed `get_provider()` API error in Issue 5, documented
3 behavioral guards for Issue 5, narrowed `decide_tick` to a richer `TickContext` approach,
and scoped Issue 3 as EventReader-first.

## Context (from discovery)

- **Files involved**: `providers/__init__.py` (318L), `window_state_store.py` (317L), `session.py` (803L),
  `session_monitor.py` (890L), `handlers/window_tick.py` (534L), `window_view.py` (29L)
- **Key numbers**: `get_provider_for_window` called at 56 sites; `get_window_state()` at 31 sites;
  `view_window()` at only 8 sites; 30 handler files touch `session_manager`
- **Already in place**: `get_provider_for_window` already accepts `provider_name: str | None = None`
  with a "skips session-manager lookup" comment — the fix is to make all callers supply it
- **Issue 5 nuance**: the `providers.registry` import in `window_state_store.set_window_provider` is for
  a `supports_hook` capability check, not just name validation — move that logic up to `session.py`
- **`get_window_provider()` does not exist** in `session.py` today — must be added as part of Task 1
- **3 behavioral guards** in `set_window_provider` must be preserved exactly (see Technical Details)
- **Test layout**: `tests/ccgram/` mirrors source; `tests/integration/` for real-tmux tests

## Development Approach

- **Testing approach**: Regular (code first, tests updated)
- Complete each task fully before moving to the next
- `make check` must pass at the end of every task (fmt + lint + typecheck + test)
- No backwards-compat shims — feature branch

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document blockers with ⚠️ prefix

## Solution Overview

**Task order (amended by Codex):** `5 → 2 → 1 → 4 → 3`

1. **Task 1 — Issue 5 + `get_window_provider()` helper**: Remove `providers.registry` from
   `window_state_store`, add `SessionManager.get_window_provider()` helper. Zero handler file changes.
2. **Task 2 — Issue 2**: Migrate read-only `get_window_state()` callers to `view_window()` first, so
   that callers already have a stable `provider_name` source before Issue 1 removes the fallback.
3. **Task 3 — Issue 1**: Eliminate lazy `session_manager` import from `providers/__init__`. Callers now
   use `view_window().provider_name` or the new `get_window_provider()` helper.
4. **Task 4 — Issue 4**: Decompose `window_tick.py` with a `TickContext` richer input object pattern.
   Removes `window_tick`'s `get_active_monitor()` coupling before the monitor is split.
5. **Task 5 — Issue 3**: Split `session_monitor.py` starting with `EventReader` (clean extraction),
   then `SessionLifecycle` with full session-map diffing + cache ownership. `IdleTracker` last.

**Why this order:** Issue 2 before Issue 1 gives callers a stable `provider_name` source via
`view_window()` — avoids adding fresh `get_window_state()` coupling just to satisfy Issue 1.
Issue 4 before Issue 3 removes `window_tick`'s direct `get_active_monitor()` dependency before
the monitor is split, making the split cleaner.

## Technical Details

### Issue 5 — move `supports_hook` check out of `window_state_store`

Current `set_window_provider` in `window_state_store.py` (lines 175–208) has **three behavioral guards
that must be preserved exactly**:

1. **Only on real provider change**: `old_provider != provider_name` — no cleanup if same provider
2. **Only when provider_name is truthy**: `provider_name == ""` is a reset-to-default and must NOT
   trigger hookless cleanup
3. **Always invoke `_on_hookless_provider_switch`** for hookless targets, even when `state.session_id`
   is already empty (only `session_id` and `transcript_path` are cleared conditionally)

Fix: accept `new_provider_supports_hook: bool` as a parameter; `session.py` resolves it via
`registry.get(provider_name)` (not `get_provider()` — that takes no argument):

```python
# window_state_store.py — no providers import needed
def set_window_provider(
    self,
    window_id: str,
    provider_name: str,
    *,
    new_provider_supports_hook: bool = True,
    cwd: str | None = None,
) -> None:
    state = self.get_window_state(window_id)
    old_provider = state.provider_name
    state.provider_name = provider_name
    if cwd is not None:
        state.cwd = cwd
    # Guard 1 & 2: only on real change, only when non-empty
    if old_provider != provider_name and provider_name:
        if not new_provider_supports_hook:
            # Guard 3: always call, even if session_id already empty
            self._on_hookless_provider_switch(window_id)
    self._save()

# session.py — already imports providers, resolves supports_hook before calling store
def set_window_provider(self, window_id: str, provider_name: str, *, cwd: str | None = None) -> None:
    from .providers.registry import registry
    supports_hook = registry.get(provider_name).capabilities.supports_hook if provider_name else True
    self._store.set_window_provider(window_id, provider_name, new_provider_supports_hook=supports_hook, cwd=cwd)
```

Also add `SessionManager.get_window_provider()` helper:

```python
def get_window_provider(self, window_id: str) -> str | None:
    """Return the provider name for a window, or None if not set."""
    state = self._store.window_states.get(window_id)
    return state.provider_name if state else None
```

### Issue 2 — `WindowView` adoption

`view_window()` returns `WindowView | None`. Current `get_window_state()` returns `WindowState`
and raises if window missing. Migration pattern for read-only sites:

```python
# before
state = session_manager.get_window_state(window_id)
if state.provider_name == "claude": ...

# after — also yields provider_name for Issue 1 callers
view = session_manager.view_window(window_id)
if view and view.provider_name == "claude": ...
```

Sites that write state still use `get_window_state()` — no change needed there.

### Issue 1 — eliminate lazy import in `providers/__init__`

Current fallback path in `get_provider_for_window` (line ~108):

```python
if provider_name is None:
    from ccgram.session import session_manager   # layer violation
    state = session_manager.window_states.get(window_id)
    provider_name = state.provider_name if state else None
```

Fix: remove the `None` fallback branch entirely. All callers must pass `provider_name` explicitly.
After Issue 2 migration, most read-only callers already have `view.provider_name`. For write-path
callers or callers that don't have a view, use the new `get_window_provider()` helper:

```python
# Pattern A — caller already has view from Issue 2
view = session_manager.view_window(window_id)
if view:
    provider = get_provider_for_window(window_id, view.provider_name)

# Pattern B — caller only has window_id
provider_name = session_manager.get_window_provider(window_id)
provider = get_provider_for_window(window_id, provider_name)
```

`session_monitor.py:61` also calls `get_provider_for_window(window_id)` without a name — this site
also needs the `get_window_provider()` helper.

### Issue 4 — window_tick decomposition with `TickContext`

The `decide_tick` pure function needs a richer input object to capture all real dependencies.
Codex confirmed: decision logic depends on queue emptiness, interactive-window ownership,
`supports_hook`, `chat_first_command_path`, notification mode, `seen_status`, `startup_time`.

```python
@dataclass(frozen=True)
class TickContext:
    """All inputs to the tick decision — pure data, no I/O."""
    window_id: str
    clean_lines: list[str]
    spinner_active: bool
    interactive_prompt: bool
    last_activity_ts: float | None
    provider_name: str | None
    supports_hook: bool
    chat_first: bool
    notification_mode: str
    seen_status: str | None       # last status text sent
    startup_time: float           # when this window started polling
    queue_has_content: bool       # True if message queue non-empty

@dataclass(frozen=True)
class TickDecision:
    send_status: bool
    status_text: str | None
    trigger_idle: bool
    show_recovery: bool
    clear_status: bool
```

`decide_tick(ctx: TickContext) -> TickDecision` — pure function, no I/O, no sibling imports.

Keep in the coordinator path (not extracted to decide_tick):

- Transcript discovery / provider-switch side effects
- Pane scanning (multi-pane windows)
- Passive shell relay

`polling_coordinator.py` reads `get_active_monitor().get_last_activity(session_id)` once per cycle
and passes `last_activity_ts` into `tick_window()` as a parameter.

### Issue 3 — session_monitor split (EventReader-first)

`_detect_and_cleanup_changes()` owns many intertwined things: session-map diffing, `claude_task_state`
cleanup, provider sync for new windows, and cleanup of `MonitorState`, `_file_mtimes`, `_pending_tools`,
`_last_activity`, throttling keys. Hook activity resolves `window_id → session_id` via `_last_session_map`
before touching `_last_activity`. So `SessionLifecycle` and `IdleTracker` are not fully independent.

**Extraction strategy:**

1. **`event_reader.py`** — `EventReader` class: reads `events.jsonl` incrementally by byte offset;
   yields `HookEvent` objects; pure I/O; no state beyond byte offset. Clean extraction.
2. **`session_lifecycle.py`** — `SessionLifecycle` class: owns session-map diffing + tracked-session
   cache cleanup (`MonitorState`, `_file_mtimes`, `_pending_tools`, throttle keys); single authority
   for `claude_task_state.clear_window()`; normalizes all activity updates to `session_id` before
   passing to `IdleTracker`. Emits `NewWindowEvent`.
3. **`idle_tracker.py`** — `IdleTracker` class: per-session idle timer; accepts only `session_id`
   inputs (normalized by `SessionLifecycle`); emits idle callbacks. Pure timer logic, no I/O.
4. **`session_monitor.py`** (thin coordinator, ~150 lines): wires the three above; owns poll loop;
   keeps `get_active_monitor()` singleton; public callback API unchanged.

Remove duplicate `claude_task_state.clear_window()` calls from `hook_events.py` and
`topic_lifecycle.py` — delegate to `session_lifecycle.handle_session_end()`.

## Implementation Steps

### Task 1: Remove `providers.registry` from `window_state_store` + add `get_window_provider()` (Issue 5 + prep)

**Files:**

- Modify: `src/ccgram/window_state_store.py`
- Modify: `src/ccgram/session.py`
- Modify: `tests/ccgram/test_window_state_store.py` (if exists)

- [ ] Read `window_state_store.set_window_provider` (lines 175–208) fully
- [ ] Add `new_provider_supports_hook: bool = True` parameter to `set_window_provider`; remove lazy `from .providers import registry` import; use the bool directly with all three guards preserved (see Technical Details)
- [ ] Read `session.py` `set_window_provider` delegation method; update to resolve `supports_hook` via `registry.get(provider_name)` before calling `_store.set_window_provider`
- [ ] Add `SessionManager.get_window_provider(window_id: str) -> str | None` helper to `session.py`
- [ ] Verify `window_state_store.py` has zero `from .providers` imports
- [ ] Update any existing test for `set_window_provider` to pass the new bool parameter
- [ ] Run `make check` — must be green

### Task 2: Migrate read-only `get_window_state()` call sites to `view_window()` (Issue 2)

**Files:**

- Modify: handler files with read-only `get_window_state()` usage (up to 31 files)
- No changes to `session.py` itself

- [ ] Grep all `get_window_state` usages: `grep -rn "get_window_state" src/ccgram/handlers/`
- [ ] Classify each: read-only (only reads fields, no mutations) → migrate to `view_window()`; write (calls setters or mutates state) → leave as `get_window_state()`
- [ ] Migrate read-only sites: replace `state = session_manager.get_window_state(window_id)` with `view = session_manager.view_window(window_id)` and add `if view is None: return` guard where needed
- [ ] Verify `WindowView` has all fields accessed by migrated sites; add any missing fields as read-only properties delegating to `WindowState` in `window_view.py`
- [ ] Run `make check` — must be green

### Task 3: Eliminate lazy `session_manager` import from `providers/__init__` (Issue 1)

**Files:**

- Modify: `src/ccgram/providers/__init__.py`
- Modify: all handler files that call `get_provider_for_window(window_id)` without `provider_name`
- Modify: `src/ccgram/session_monitor.py` (line 61)

- [ ] Grep all bare call sites: `grep -rn "get_provider_for_window(window_id)" src/` (without second arg)
- [ ] For callers that already have `view` from Task 2: pass `view.provider_name` as second arg
- [ ] For write-path callers with only `window_id`: use new `session_manager.get_window_provider(window_id)` helper
- [ ] Fix `session_monitor.py:61` using `get_window_provider()` (it has no view or state nearby)
- [ ] In `providers/__init__.py`: remove the `if provider_name is None:` branch and the lazy `from ccgram.session import session_manager` import
- [ ] Verify `providers/__init__.py` has zero imports from `ccgram.session`
- [ ] Write test: `get_provider_for_window(window_id, "claude")` resolves without touching session state
- [ ] Run `make check` — must be green

### Task 4: Decompose `window_tick.py` with `TickContext` observe→decide→act (Issue 4)

**Files:**

- Modify: `src/ccgram/handlers/window_tick.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`
- Modify or extend: `src/ccgram/handlers/polling_strategies.py`
- Create: `tests/ccgram/handlers/test_tick_decision.py`

- [ ] Read `window_tick.py` fully; identify the status/idle decision kernel vs. coordinator paths
- [ ] Define `TickContext` frozen dataclass (see Technical Details) in `polling_strategies.py`
- [ ] Define `TickDecision` frozen dataclass
- [ ] Extract `decide_tick(ctx: TickContext) -> TickDecision` — pure function; no I/O; no imports from sibling handlers; only depends on `TickContext` fields
- [ ] Identify what stays in coordinator path: transcript discovery, pane scanning, passive shell relay, interactive UI detection — these read I/O and are NOT extracted to `decide_tick`
- [ ] Rewrite `tick_window()` as coordinator: builds `TickContext`, calls `decide_tick`, applies decision; receives `last_activity_ts: float | None` as parameter
- [ ] Update `polling_coordinator.py`: read `get_active_monitor().get_last_activity(session_id)` once per cycle and pass as `last_activity_ts` into `tick_window()`
- [ ] Write tests for `decide_tick` (pure function — just construct `TickContext` instances, no mocks)
- [ ] Run `make check` — must be green

### Task 5: Split `session_monitor.py` — EventReader-first strategy (Issue 3)

**Files:**

- Create: `src/ccgram/event_reader.py`
- Create: `src/ccgram/session_lifecycle.py`
- Create: `src/ccgram/idle_tracker.py`
- Modify: `src/ccgram/session_monitor.py` (reduce to ~150 lines coordinator)
- Modify: `src/ccgram/handlers/hook_events.py` (delegate claude_task_state cleanup)
- Modify: `src/ccgram/handlers/topic_lifecycle.py` (same delegation)
- Modify: `src/ccgram/bot.py` (import new modules if wiring changes)
- Create: `tests/ccgram/test_event_reader.py`
- Create: `tests/ccgram/test_idle_tracker.py`

- [ ] Read `session_monitor.py` fully; map which lines belong to which responsibility
- [ ] Extract `event_reader.py` first: `EventReader` with `read_new_events(path, offset) -> list[HookEvent]`; pure I/O; no references to session state, claude_task_state, or \_last_session_map
- [ ] Extract `idle_tracker.py`: `IdleTracker` with `record_activity(session_id)`, `get_last_activity(session_id) -> float | None`, `check_idle(session_id, threshold) -> bool`; pure timer; accepts only session_id inputs (not window_id)
- [ ] Extract `session_lifecycle.py`: `SessionLifecycle` with `detect_changes(session_map, live_windows, tracked_sessions) -> list[LifecycleEvent]`; owns single authority for `claude_task_state.clear_window()`; normalizes window_id→session_id lookups internally; also clears `MonitorState`, `_file_mtimes`, `_pending_tools`, throttle keys on cleanup
- [ ] Add `handle_session_end(window_id)` and `handle_session_start(window_id, session_id)` to `SessionLifecycle` for use by `hook_events.py`
- [ ] Rewrite `session_monitor.py` as coordinator: instantiates and wires the three classes; owns the poll loop; keeps `get_active_monitor()` singleton; public callback API unchanged
- [ ] Update `hook_events.py`: replace direct `claude_task_state.clear_window()` calls on `SessionEnd` with `session_lifecycle.handle_session_end(window_id)`
- [ ] Update `topic_lifecycle.py`: same delegation for any `claude_task_state` writes
- [ ] Write tests for `EventReader.read_new_events` (with temp file fixtures)
- [ ] Write tests for `IdleTracker.record_activity` and `check_idle` (mock `time.monotonic`)
- [ ] Run `make check` — must be green

### Task 6: Verify acceptance criteria

- [ ] Verify `providers/__init__.py` has zero `from ccgram.session` imports
- [ ] Verify `window_state_store.py` has zero `from .providers` imports
- [ ] Verify `session_monitor.py` is ≤200 lines
- [ ] Verify `window_tick.py` import count reduced (target: ≤20)
- [ ] Verify `view_window()` adoption ≥ 60% of all `get_window_state`+`view_window` call sites
- [ ] Run `make check` (fmt + lint + typecheck + test) — must be fully green
- [ ] Run `make test-integration` — must pass

### Task 7: [Final] Update docs and close

**Files:**

- Modify: `docs/modularity-review/2026-04-15/modularity-review.md` (add post-fix notes)
- Move: this plan to `docs/plans/completed/`

- [ ] Update modularity review doc with "resolved" markers on the 5 issues
- [ ] Move plan: `mkdir -p docs/plans/completed && mv docs/plans/20260415-modularity-decouple.md docs/plans/completed/`

## Post-Completion

**Manual verification:**

- Run `./scripts/restart.sh start` and send a message from Telegram to verify full round-trip still works
- Verify live view, hook events (Stop, SubagentStart), and shell provider all behave normally
- Check `ccgram doctor` reports no issues

**Architecture note:**
After this refactor, `session.py` remains the single wiring layer that imports from both `window_state_store` and `providers` — this is intentional and correct. The `providers` layer should never again import from `session`.
