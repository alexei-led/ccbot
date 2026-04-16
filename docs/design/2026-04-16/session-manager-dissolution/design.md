# SessionManager Facade Dissolution

## Functional Responsibilities

Remove pure delegation methods from `SessionManager` so callers import the actual owning module directly. After this change, SessionManager owns only:

1. **Startup orchestration** — `__post_init__`, `_wire_singletons`, `_load_state`, `resolve_stale_ids`
2. **Write coordination** — methods that trigger `_save_state` after mutating one or more sub-objects: `set_display_name`, `sync_display_names`, `set_window_provider`, `set_window_cwd`, `set_window_approval_mode`, `set_notification_mode`, `cycle_notification_mode`, `set_batch_mode`, `cycle_batch_mode`
3. **Cross-cutting operations** — `audit_state`, `prune_stale_state`, `prune_stale_window_states`, `flush_state`

## Encapsulated Knowledge

SessionManager knows:

- How to wire the `_schedule_save` callbacks on sub-objects (`_wire_singletons`)
- How to assemble the full state blob from all sub-objects for persistence (`_serialize_state`)
- How to orchestrate startup recovery across all sub-objects (`resolve_stale_ids`)
- How to cross-reference multiple sub-objects for audit and pruning
- Which write operations require coordinated side-effects (e.g., `set_display_name` touches both `thread_router` and `WindowState.window_name`)

No other module should know the persistence wiring protocol or the cross-object invariants.

## Subdomain Classification

**Core** — session/window state management is the product's central abstraction. Changes as features evolve (new per-window modes, new providers, new lifecycle events).

## Changes

### Phase 1: Delete dead delegation methods (zero external callers)

These SessionManager methods have **no callers outside `session.py` itself**:

| Method                       | Delegates to       | External call sites                                                   |
| ---------------------------- | ------------------ | --------------------------------------------------------------------- |
| `get_display_name`           | `thread_router`    | 0 (all 30+ callers already use `thread_router` directly)              |
| `get_window_for_chat_thread` | `thread_router`    | 0 (all callers already use `thread_router` directly)                  |
| `get_window_state`           | `window_store`     | 0 (callers use `window_query.view_window` or `window_store` directly) |
| `prune_stale_offsets`        | `user_preferences` | 0 (only called from `prune_stale_state` which is on SessionManager)   |

**Action**: Delete these 4 methods. No caller migration needed.

### Phase 2: Migrate callers to existing `window_query` functions

`session_manager.get_window_provider(window_id)` has 7 external callers but `window_query.get_window_provider(window_id)` already exists and is identical:

| Caller                  | Line          | Change                                                                                |
| ----------------------- | ------------- | ------------------------------------------------------------------------------------- |
| `bot.py`                | 149, 173, 227 | `from .window_query import get_window_provider` or use existing `window_query` import |
| `status_bar_actions.py` | 126           | Same                                                                                  |
| `toolbar_keyboard.py`   | 118           | Same                                                                                  |
| `resume_command.py`     | 239           | Same                                                                                  |
| `recovery_callbacks.py` | 69, 501       | Same                                                                                  |

Similarly migrate `session_manager.get_session_id_for_window()` (already in `window_query`) and `session_manager.clear_window_session()` (2 callers: `command_orchestration.py`, `session_lifecycle.py` — these import `window_store.clear_window_session` directly).

**Action**: Update 7 import sites for `get_window_provider`, 2 for `clear_window_session`. Delete 3 more passthrough methods from SessionManager.

### Phase 3: Create `session_query.py` for session resolution reads

`resolve_session_for_window`, `find_users_for_session`, `get_recent_messages` are read-only operations delegating to `session_resolver`. 4 call sites across 2 handler files (`message_routing.py`, `history.py`).

**Action**: Create `session_query.py` with 3 free functions wrapping `session_resolver`. Migrate 4 call sites. Delete 3 passthrough methods from SessionManager.

### Phase 4: Let callers import `session_map_sync` directly

`wait_for_session_map_entry` (4 callers), `load_session_map` (1 caller), `prune_session_map` (2 callers), `register_hookless_session` (1 caller), `write_hookless_session_map` (1 caller) — these are mostly write operations called from specific lifecycle points.

**Action**: Callers import `from .session_map import session_map_sync` directly. Delete 5 passthrough methods from SessionManager.

### Net Result

SessionManager public API shrinks from **39 methods + 5 properties** to **~20 methods + 2 properties** (`window_states` stays for write operations, `thread_bindings` stays for iteration in `polling_coordinator`). All remaining methods add real logic — no pure passthroughs.

## Integration Contracts

### SessionManager -> sub-objects (unchanged)

- `_wire_singletons` installs `_schedule_save` callbacks on `window_store`, `thread_router`, `user_preferences`, `session_map_sync`
- Direction: SessionManager depends on all sub-objects for startup wiring
- Contract type: Functional coupling (SessionManager knows the wiring protocol)
- This coupling is essential — it's the reason SessionManager exists

### Handlers -> `window_query` (existing, expand usage)

- Direction: Handlers depend on `window_query` for reads
- Contract type: Contract coupling (read-only free functions)
- What is shared: Window state projections (`WindowView`, mode strings, provider names)

### Handlers -> `session_query` (new)

- Direction: `message_routing`, `history` depend on `session_query` for reads
- Contract type: Contract coupling (read-only free functions)
- What is shared: Session resolution results, message history

### Handlers -> `session_map_sync` (direct)

- Direction: Lifecycle handlers depend on `session_map_sync` for session map operations
- Contract type: Model coupling (shared session map model)
- What is shared: Session map entries, window-to-session mapping

## Change Vectors

- **New per-window setting**: add to `WindowStateStore` + `window_query` (read) + `SessionManager` (write). No passthrough needed.
- **New read-only query**: add to `window_query` or `session_query`. SessionManager not touched.
- **New sub-object**: only `SessionManager._wire_singletons` and `_serialize_state` change.
- **Splitting persistence**: `_serialize_state` splits naturally per sub-object.
