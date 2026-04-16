# SessionManager Facade Dissolution — Test Specification

## Unit Tests

### test_dead_delegations_removed

- **Scenario**: After refactoring, SessionManager should not have the removed delegation methods
- **Expected behavior**: `hasattr(session_manager, "get_display_name")` returns `False`. Same for `get_window_for_chat_thread`, `get_window_state`, `prune_stale_offsets`, `get_window_provider` (moved to window_query), `get_session_id_for_window` (moved to window_query), `clear_window_session` (callers use window_store directly)

### test_remaining_methods_are_substantive

- **Scenario**: Every remaining public method on SessionManager adds logic beyond delegation
- **Expected behavior**: No method body is a single return statement forwarding to a sub-object. Audit by inspecting the class — each method should either touch multiple sub-objects, validate input, trigger persistence, or perform orchestration.

### test_wire_singletons_installs_callbacks

- **Scenario**: After `__post_init__`, all sub-objects have working `_schedule_save` callbacks
- **Expected behavior**: Calling `window_store._schedule_save()` does not raise `RuntimeError`. Same for `thread_router`, `user_preferences`, `session_map_sync`.

### test_serialize_state_assembles_all_sources

- **Scenario**: `_serialize_state` produces a dict with keys from all sub-objects
- **Expected behavior**: Result contains `window_states`, `thread_bindings`, `group_chat_ids`, `window_display_names`, `user_window_offsets`, `user_dir_favorites`

## Integration Contract Tests

### test_window_query_matches_session_manager_reads

- **Scenario**: For every window_query function, compare its result to the equivalent direct call on the sub-object
- **Expected behavior**: `window_query.view_window(wid)` returns the same `WindowView` as constructing one from `window_store.get_window_state(wid)`. Same for `get_window_provider`, `get_approval_mode`, etc.

### test_session_query_matches_session_resolver

- **Scenario**: `session_query.resolve_session_for_window(wid)` returns the same result as `session_resolver.resolve_session_for_window(wid)`
- **Expected behavior**: Identical return values for all three session_query functions

### test_callers_no_longer_import_session_manager_for_reads

- **Scenario**: Grep the codebase for `session_manager.get_window_provider`, `session_manager.get_display_name`, etc.
- **Expected behavior**: Zero matches. All read callers use `window_query`, `session_query`, `thread_router`, or `window_store` directly.

## Boundary Tests

### test_session_query_handles_missing_window

- **Scenario**: Call `session_query.resolve_session_for_window("@999")` for a non-existent window
- **Expected behavior**: Returns `None` without raising

### test_session_query_handles_missing_session

- **Scenario**: Call `session_query.find_users_for_session("nonexistent-uuid")` for an unknown session
- **Expected behavior**: Returns empty list

### test_window_query_handles_missing_window

- **Scenario**: Call `window_query.view_window("@999")` for a non-existent window
- **Expected behavior**: Returns `None`

## Behavior Tests

### test_handler_reads_work_after_dissolution

- **Scenario**: Simulate the full message routing flow — SessionMonitor detects a new message, `message_routing.py` resolves the session, finds users, delivers the message
- **Expected behavior**: Flow completes successfully using `session_query` functions instead of `session_manager` delegations

### test_session_map_direct_import_works

- **Scenario**: `directory_callbacks.py` calls `session_map_sync.wait_for_session_map_entry(wid)` directly
- **Expected behavior**: Behaves identically to the old `session_manager.wait_for_session_map_entry(wid)` path

### test_write_operations_still_persist

- **Scenario**: Call `session_manager.set_window_provider(wid, "codex")` — a write operation that stays on SessionManager
- **Expected behavior**: `window_store.window_states[wid].provider_name` is `"codex"` and state is persisted
