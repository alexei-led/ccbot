# Session and State

## Functional Responsibilities

Owns all persistent and in-memory state about tmux windows and Telegram thread bindings. The [Session Map Resolution](../session-map-resolution/design.md) module reads the hook-written `session_map.json` and publishes events; this module owns the persistent `state.json` and the authoritative in-memory snapshot.

Files:

- **`session.py`** (~810 lines) — `SessionManager` facade (39+ methods). Wires the sub-objects via `_wire_singletons`, drives persistence via debounced `_save_state`, owns `resolve_stale_ids`, `prune_stale_state`, `audit_state`, `view_window`, plus thin delegators to `session_map_sync` and `thread_router`.
- **`window_state_store.py`** — `WindowState` dataclass + `WindowStateStore`. Per-window fields: `cwd`, `provider_name`, `session_id`, `transcript_path`, `approval_mode`, `notification_mode`, `batch_mode`, `external`. Atomic `_schedule_save` wiring via `unwired_save()` fail-loud default.
- **`thread_router.py`** — `ThreadRouter`. User × thread → window_id bindings, display-name map, group chat id map, reverse index. Public API: `set_display_name`, `get_display_name`, `pop_display_name`, `resolve_chat_id`, `set_group_chat_id`.
- **`user_preferences.py`** — directory favourites (starred/MRU) and per-user read offsets (for history pagination).
- **`window_view.py`** — `WindowView` frozen dataclass. Read-only projection: `window_id`, `cwd`, `provider_name`, `approval_mode`, `notification_mode`, `transcript_path`.
- **`state_persistence.py`** — `StatePersistence` (atomic JSON writes, debounced save) + `unwired_save(owner)` helper that raises `RuntimeError` if called before SessionManager initialisation.

## Encapsulated Knowledge

- **`state.json` schema** — owned by `SessionManager._serialize_state`. No other module writes this file.
- **Window state shape** — `WindowState` dataclass. Changes here cascade to handlers that read individual fields; `WindowView` is the relief valve for read-only consumers.
- **Display-name map access** — owned by `ThreadRouter`. After the refactor, `session.py` does not reach into `thread_router.window_display_names[wid]` directly; it uses the public helpers.
- **Save debouncing** — owned by `StatePersistence`. Handlers never call `_save_state` directly; they mutate through the store/router methods which schedule the save.
- **Test isolation** — `unwired_save("...")` raises `RuntimeError` if a test mutates state without wiring a save callback. This is the fail-loud default landed in Task 4 of the April 12 refactor.

## Subdomain Classification

**Core.** Session and state is the most active area of ccgram. Every new feature adds a field, a query, or a persistence concern. The 39-method facade is borderline god-object territory but works at solo-dev distance.

## Integration Contracts

### Inbound

| From                                                                                                                                           | Kind       | Contract                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------- |
| `handlers/*` → `session_manager.view_window(wid) → WindowView \| None`                                                                         | Contract   | Read-only projection — **preferred** for read-only handlers |
| `handlers/*` → `session_manager.get_window_state(wid) → WindowState`                                                                           | Model      | Full mutable state — for handlers that need to mutate       |
| `handlers/directory_callbacks._create_window_and_bind` → `session_manager.set_display_name`, `set_window_provider`, `set_window_approval_mode` | Contract   | Window creation flow                                        |
| `handlers/polling_coordinator` → `session_manager.get_notification_mode`, `prune_stale_offsets`, etc.                                          | Functional | Poll-loop reads/writes                                      |
| `session_map.py` (Session Map Resolution) → `thread_router.set_display_name(...)`                                                              | Contract   | Hook-driven display-name refresh                            |
| `session_resolver` → `window_store.update_cwd(wid, cwd)`, `window_store.clear_session_fields(wid)`                                             | Contract   | Public mutators (no `_schedule_save` direct access)         |
| `bot.py::post_init` → `session_manager.resolve_stale_ids()`, `prune_stale_state(...)`, `load_session_map()`                                    | Contract   | Startup wiring                                              |

### Outbound

| To                                                         | Kind     | Contract               |
| ---------------------------------------------------------- | -------- | ---------------------- |
| `StatePersistence.write_atomic(path, data)`                | Contract | File I/O               |
| `tmux_manager.list_windows`, `find_window_by_id`           | Contract | Stale ID re-resolution |
| `providers/process_detection.detect_provider_from_command` | Contract | Auto-detect on bind    |

### WindowView

```python
# window_view.py
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True, slots=True)
class WindowView:
    window_id: str
    cwd: str
    provider_name: str
    approval_mode: str
    notification_mode: str
    transcript_path: Path | None
```

### Facade leak fixes

Currently `session.py` has three direct accesses to the raw dict:

```python
# session.py:412, 414, 495
thread_router.window_display_names[wid]
del thread_router.window_display_names[wid]
```

These become:

```python
thread_router.get_display_name(wid)
thread_router.pop_display_name(wid)
```

The public helpers already exist — this is a 3-line fix.

## Change Vectors

- **Add a new per-window field** (e.g., `last_active_ts`) — add to `WindowState`, add to `WindowView` if reads are common, add to `_serialize_state` / `from_dict`, add a getter/setter on `WindowStateStore`. 4-file change for one concept; tolerable given volatility.
- **Rename an existing field** — cascades to every handler that reads it directly. `WindowView` mitigates this for the migrated handlers; the rest still cascade.
- **Add a new mode (notification / approval / batch)** — add cycle/set methods to `WindowStateStore`, add callbacks in `handlers/screenshot_callbacks._handle_notify_toggle` / etc.
- **Split `SessionManager` into multiple facades** — **don't**. The god-object pattern is tolerable at solo-dev distance and `WindowView` addresses the read-side cascade pain. Splitting would add ceremony without payback.
- **Persist across bot restarts** — already works via `state.json`. New fields become persistent automatically when added to `WindowState`.

## Refactor Plan

1. **Drive `WindowView` adoption.** Migrate one-call-read handlers opportunistically (when each is next touched):
   - `handlers/file_handler.py` — reads `cwd` only
   - `handlers/history.py` — reads `transcript_path` only
   - `handlers/shell_commands.py` — reads `cwd` only
   - `handlers/text_handler.py` — reads `cwd` only
   - `handlers/send_command.py` — reads `cwd` only
   - `handlers/screenshot_callbacks.py` — reads `notification_mode` via `cycle_notification_mode` (keep as get_window_state; it mutates)
   - `handlers/topic_emoji.py` — reads `approval_mode` only
2. **Fix the three direct `thread_router.window_display_names[wid]` accesses in `session.py`** — replace with public helpers. 3-line change.
3. **Track progress** — `grep -c 'session_manager\.get_window_state' src/ccgram/handlers/*.py`. Target: drop below 15. Currently ~20 read-side call sites.
4. **Optional: fold short-lived per-window state** (e.g., `toolbar_callbacks._window_action_labels`) into `WindowState` if it is session-scoped and useful across handler restarts. This removes a scattered dict without the cost of a full `WindowContext` aggregation.

## Testability Goals

- **Unit-test `WindowView`** — frozen dataclass, fixture-constructible. Tests that need a window just build `WindowView(window_id="@5", cwd="/tmp", ...)` without any session wiring.
- **Unit-test handler logic** using `WindowView` fixtures — no `SessionManager`, no `WindowStateStore`, no state.json.
- **Unit-test `WindowStateStore.cycle_notification_mode`** in isolation with a no-op save callback.
- **Fail-loud test for `unwired_save`** — instantiate a fresh `WindowStateStore` without wiring, call `update_cwd`, expect `RuntimeError("WindowStateStore not initialized")`.
- **Integration-test `resolve_stale_ids`** — seed a synthetic state.json with old window names, start with fake tmux list output, verify the re-resolution updates the IDs.
- **Integration-test `audit_state`** — verify the audit report catches seeded inconsistencies (window in state.json but not in session_map, etc.).
