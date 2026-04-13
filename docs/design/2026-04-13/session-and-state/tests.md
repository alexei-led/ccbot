# Session and State — Test Specification

## Unit Tests

### WindowView (`window_view.py`)

| Name                            | Scenario                  | Expected                     |
| ------------------------------- | ------------------------- | ---------------------------- |
| `test_window_view_frozen`       | Attempt `view.cwd = "x"`  | Raises `FrozenInstanceError` |
| `test_window_view_construction` | Build from literal values | All fields accessible        |
| `test_window_view_path_field`   | transcript_path = Path    | Path object exposed          |

### SessionManager.view_window

| Name                                       | Scenario                      | Expected                        |
| ------------------------------------------ | ----------------------------- | ------------------------------- |
| `test_view_window_returns_snapshot`        | Existing window               | WindowView with matching fields |
| `test_view_window_returns_none_if_missing` | Unknown window_id             | Returns None                    |
| `test_view_window_is_snapshot_not_view`    | Mutate WindowState after call | WindowView values unchanged     |

### WindowStateStore

| Name                                          | Scenario                             | Expected                                           |
| --------------------------------------------- | ------------------------------------ | -------------------------------------------------- |
| `test_unwired_save_raises`                    | New store, no SessionManager, mutate | RuntimeError("WindowStateStore not initialized")   |
| `test_wire_save_callback_invoked_on_mutation` | Wire callback, call `update_cwd`     | Callback called once                               |
| `test_cycle_notification_mode_progression`    | Starting "all"                       | Progresses "all" → "errors_only" → "muted" → "all" |
| `test_set_window_provider_updates_field`      | Set to "codex"                       | Field updated, save scheduled                      |
| `test_clear_session_fields`                   | Window with session_id               | session_id and cwd cleared                         |
| `test_prune_stale_window_states`              | Windows in store not in live set     | Removed                                            |

### ThreadRouter

| Name                                        | Scenario                   | Expected                    |
| ------------------------------------------- | -------------------------- | --------------------------- |
| `test_set_display_name`                     | Set name, get back         | Returns the name            |
| `test_pop_display_name`                     | Pop existing               | Returns name, removes entry |
| `test_pop_display_name_missing`             | Pop unknown                | Returns None / default      |
| `test_resolve_chat_id`                      | Set group chat id, resolve | Returns id                  |
| `test_sync_display_names_updates_on_rename` | Window rename              | Map updated, save scheduled |

### SessionManager facade

| Name                                  | Scenario                                       | Expected                                      |
| ------------------------------------- | ---------------------------------------------- | --------------------------------------------- |
| `test_resolve_stale_ids`              | Old state.json with old window IDs + live tmux | IDs re-resolved to new @N                     |
| `test_load_session_map_delegates`     | Call `load_session_map`                        | `session_map_sync.load` called, no direct I/O |
| `test_audit_state_report`             | Seeded inconsistencies                         | Audit includes each issue                     |
| `test_flush_state_writes_immediately` | Mutate then flush                              | state.json on disk matches in-memory          |

## Integration Contract Tests

| Name                                                      | Scenario             | Expected                                                                   |
| --------------------------------------------------------- | -------------------- | -------------------------------------------------------------------------- |
| `test_session_manager_does_not_access_display_names_dict` | grep source          | No `thread_router.window_display_names[...]` direct access in `session.py` |
| `test_handler_uses_window_view_for_read`                  | Migrated handler     | Calls `view_window`, not `get_window_state`                                |
| `test_view_window_matches_get_window_state_fields`        | Both for same window | Common fields agree                                                        |

## Boundary Tests

| Name                                        | Scenario                               | Expected                                     |
| ------------------------------------------- | -------------------------------------- | -------------------------------------------- |
| `test_window_state_missing_transcript_path` | No transcript set                      | `view.transcript_path is None`               |
| `test_save_after_bot_shutdown`              | `flush_state()` called during shutdown | State persisted without error                |
| `test_load_state_corrupted_json`            | Corrupted state.json                   | Loads empty state, logs error, doesn't crash |
| `test_sync_display_names_empty_live_list`   | Empty list                             | No-op, no changes                            |

## Behavior Tests

| Name                                                 | Scenario                     | Expected                           |
| ---------------------------------------------------- | ---------------------------- | ---------------------------------- |
| `test_scenario_window_creation_persists`             | Create window, flush, reload | Window restored with same state    |
| `test_scenario_renaming_window_updates_display_name` | tmux rename → sync           | Display name updated in state.json |
| `test_scenario_migration_from_window_name_keys`      | Old-format state.json        | Migrated to window-id keys         |
