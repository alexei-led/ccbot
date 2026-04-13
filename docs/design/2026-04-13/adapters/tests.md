# Adapters — Test Specification

## Unit Tests

### tmux_manager

| Name                                       | Scenario                   | Expected                                                              |
| ------------------------------------------ | -------------------------- | --------------------------------------------------------------------- |
| `test_list_windows_maps_ids`               | Mocked libtmux             | Returns list of (id, name) tuples                                     |
| `test_find_window_by_id_exists`            | Known @5                   | Returns window object                                                 |
| `test_find_window_by_id_missing`           | Unknown @99                | Returns None                                                          |
| `test_send_keys_escape_sequences`          | Literal `\x1b[Z`           | Uses `send-keys -H -l` via subprocess for foreign, libtmux for native |
| `test_capture_pane_strips_newlines`        | Fixture                    | Returns normalised text                                               |
| `test_foreign_window_routes_to_subprocess` | Foreign `emdash-claude:@0` | Subprocess path, not libtmux                                          |
| `test_create_window_sets_env_and_cwd`      | Create @N in cwd /tmp      | tmux command has `-c /tmp`                                            |

### terminal_parser

| Name                                     | Scenario                  | Expected             |
| ---------------------------------------- | ------------------------- | -------------------- |
| `test_parse_terminal_status_idle`        | Pane at shell prompt      | Status = idle        |
| `test_parse_terminal_status_spinner`     | Pane with spinner glyph   | Status = active      |
| `test_parse_terminal_status_interactive` | Pane with AskUserQuestion | Status = interactive |
| `test_detect_separator_present`          | Pane with separator line  | Returns index        |
| `test_detect_separator_absent`           | Normal output             | Returns None         |

### screen_buffer

| Name                            | Scenario      | Expected                       |
| ------------------------------- | ------------- | ------------------------------ |
| `test_screen_buffer_feed_ansi`  | ANSI bytes    | Rendered grid matches expected |
| `test_screen_buffer_reset`      | After reset   | Grid empty                     |
| `test_screen_buffer_size_bound` | 80×24 default | Grid dimensions correct        |

### transcript_parser

| Name                                  | Scenario                          | Expected                                        |
| ------------------------------------- | --------------------------------- | ----------------------------------------------- |
| `test_tool_use_result_pairing`        | Entries with matching tool_use_id | Paired                                          |
| `test_tool_use_without_result`        | Orphan tool_use                   | Remains unpaired (pending)                      |
| `test_build_response_parts_text_only` | Text message                      | Returns list with text                          |
| `test_build_response_parts_tool_use`  | Tool use                          | Returns formatted summary with tool name + args |

## Integration Contract Tests

| Name                                  | Scenario           | Expected                          |
| ------------------------------------- | ------------------ | --------------------------------- |
| `test_tmux_manager_real_session`      | Real tmux          | Round-trip send_keys/capture_pane |
| `test_transcript_parser_fixture_file` | Real JSONL fixture | Produces expected message list    |

## Boundary Tests

| Name                                  | Scenario       | Expected                                 |
| ------------------------------------- | -------------- | ---------------------------------------- |
| `test_libtmux_command_failure`        | Raises         | Falls back to subprocess or returns None |
| `test_capture_pane_large_output`      | 10MB pane      | Handled without crash                    |
| `test_transcript_parser_invalid_line` | Malformed JSON | Skipped, logged                          |

## Behavior Tests

| Name                                          | Scenario                         | Expected                                   |
| --------------------------------------------- | -------------------------------- | ------------------------------------------ |
| `test_scenario_foreign_window_full_lifecycle` | emdash window created externally | Discovered, send_keys works, capture works |
| `test_scenario_transcript_incremental`        | Parse file then append           | Second parse picks up appended entries     |
