# Session Map Resolution — Test Specification

## Unit Tests

| Name                                          | Scenario                          | Expected                                |
| --------------------------------------------- | --------------------------------- | --------------------------------------- |
| `test_session_map_load_valid_json`            | Seeded valid json                 | Returns dict keyed by `session:@wid`    |
| `test_session_map_load_missing_file`          | No file                           | Returns empty dict                      |
| `test_session_map_load_corrupted`             | Invalid json                      | Returns empty, logs error               |
| `test_session_map_write_atomic`               | Write new entry                   | File replaced atomically (tmp → rename) |
| `test_session_map_prune_keeps_live`           | Live set has some, others removed | Survivors match live set                |
| `test_register_hookless_session`              | New Codex session                 | Entry added with provider_name="codex"  |
| `test_monitor_incremental_read`               | Append 3 lines between calls      | Second call yields only new 3           |
| `test_monitor_truncation_recovery`            | Offset > file_size                | Offset reset to 0, re-read              |
| `test_monitor_mtime_cache_skip`               | Unchanged mtime                   | Skip file read                          |
| `test_new_message_is_tool_use_classification` | Parsed tool_use entry             | `is_tool_use=True`                      |
| `test_new_message_is_thinking_classification` | Thinking block                    | `is_thinking=True`                      |

## Integration Contract Tests

| Name                                          | Scenario                   | Expected                                                                     |
| --------------------------------------------- | -------------------------- | ---------------------------------------------------------------------------- |
| `test_monitor_dispatches_to_routing_callback` | Write new line             | `message_callback(msg, bot)` called                                          |
| `test_monitor_dispatches_hook_events`         | Write events.jsonl line    | `hook_event_callback(event, bot)` called                                     |
| `test_session_resolver_via_provider`          | ClaudeSession with fixture | Uses provider's `parse_transcript_entries`                                   |
| `test_session_map_syncs_display_names`        | Hook writes new name       | `thread_router.set_display_name` called (via public helper, not dict access) |

## Boundary Tests

| Name                                      | Scenario                           | Expected                   |
| ----------------------------------------- | ---------------------------------- | -------------------------- |
| `test_monitor_concurrent_writes`          | Two writes during one poll         | Both read on next cycle    |
| `test_offset_persisted_across_restart`    | Write offset, recreate monitor     | Resumes from stored offset |
| `test_session_map_missing_provider_field` | Legacy entry without provider_name | Defaults to "claude"       |

## Behavior Tests

| Name                                                 | Scenario                                       | Expected                                |
| ---------------------------------------------------- | ---------------------------------------------- | --------------------------------------- |
| `test_scenario_hook_writes_and_monitor_reads`        | SessionStart hook → session_map.json → monitor | NewMessage events delivered             |
| `test_scenario_events_jsonl_reprocessing_on_restart` | Partial read then restart                      | Resumes from byte offset, no duplicates |
