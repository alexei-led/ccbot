# Provider Abstraction — Test Specification

## Unit Tests

### ProviderCapabilities / Registry

| Name                                     | Scenario                             | Expected         |
| ---------------------------------------- | ------------------------------------ | ---------------- |
| `test_registry_returns_singleton`        | `get_provider("claude")` twice       | Same instance    |
| `test_registry_unknown_provider_raises`  | `get_provider("nonsense")`           | Raises           |
| `test_has_yolo_confirmation_claude_only` | Flag true on Claude, false on others | Per provider     |
| `test_supports_hook_claude_only`         | Flag check                           | Only Claude True |

### AgentProvider.scrape_current_mode (NEW capability)

| Name                                      | Scenario                            | Expected                                                 |
| ----------------------------------------- | ----------------------------------- | -------------------------------------------------------- |
| `test_default_returns_none`               | Base Protocol default               | `await ShellProvider().scrape_current_mode("@5")` → None |
| `test_claude_returns_edit_mode`           | Fixture pane "auto-accept edits on" | Returns "Edit"                                           |
| `test_claude_returns_plan_mode`           | "Plan mode on"                      | Returns "Plan"                                           |
| `test_claude_returns_none_for_other_text` | Random shell output                 | Returns None                                             |
| `test_codex_returns_none`                 | Default impl                        | None                                                     |
| `test_gemini_returns_yolo_if_yolo_on`     | Fixture "YOLO mode"                 | Returns "YOLO" or None (design choice)                   |

### ClaudeProvider

| Name                                     | Scenario                        | Expected                        |
| ---------------------------------------- | ------------------------------- | ------------------------------- |
| `test_parse_hook_payload_session_start`  | SessionStart JSON               | Returns `SessionStartEvent`     |
| `test_parse_hook_payload_unknown_event`  | Unknown event type              | Returns None                    |
| `test_make_launch_args_fresh`            | mode="fresh"                    | `["claude"]`                    |
| `test_make_launch_args_resume`           | mode="resume", session_id="abc" | `["claude", "--resume", "abc"]` |
| `test_parse_transcript_entries_tool_use` | JSONL fixture with tool_use     | Yields structured entries       |
| `test_read_transcript_file_incremental`  | Seek past first half            | Yields only new entries         |
| `test_detect_from_pane_title_claude`     | Pane title = "claude"           | Returns `ClaudeProvider`        |

### CodexProvider / GeminiProvider / ShellProvider

| Name                                  | Scenario            | Expected                        |
| ------------------------------------- | ------------------- | ------------------------------- |
| `test_codex_parse_transcript_entries` | Codex JSONL fixture | Yields structured entries       |
| `test_gemini_whole_file_read`         | Gemini JSON fixture | Returns all entries in one read |
| `test_shell_make_launch_args_noop`    | mode=anything       | Returns `[]` or `[$SHELL]`      |

### Detection

| Name                                             | Scenario                          | Expected                         |
| ------------------------------------------------ | --------------------------------- | -------------------------------- |
| `test_detect_provider_from_command_claude`       | basename = "claude"               | `ClaudeProvider`                 |
| `test_detect_provider_from_command_node`         | JS wrapper                        | Falls back to `detect_from_pane` |
| `test_detect_provider_from_pane_ps_fallback`     | PGID-cached ps lookup             | Returns detected provider        |
| `test_get_provider_for_window_uses_window_state` | WindowState.provider_name="codex" | Returns `CodexProvider`          |

## Integration Contract Tests

| Name                                               | Scenario                                               | Expected                                                      |
| -------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------- |
| `test_hook_write_to_session_map`                   | ClaudeProvider.parse_hook_payload → write              | `session_map.json` has new entry                              |
| `test_transcript_round_trip`                       | Write + incremental read                               | All entries seen exactly once                                 |
| `test_provider_lazy_import_break` (AFTER refactor) | `get_provider_for_window(wid, provider_name="claude")` | No import of `session_manager` inside `providers/__init__.py` |

## Boundary Tests

| Name                                       | Scenario                  | Expected                            |
| ------------------------------------------ | ------------------------- | ----------------------------------- |
| `test_parse_hook_payload_malformed_json`   | `{`                       | Raises or returns None (documented) |
| `test_scrape_current_mode_tmux_error`      | `capture_pane` raises     | Returns None                        |
| `test_transcript_file_disappears_mid_read` | Delete file between reads | Graceful None / empty               |

## Behavior Tests

| Name                                                 | Scenario                                     | Expected                                 |
| ---------------------------------------------------- | -------------------------------------------- | ---------------------------------------- |
| `test_scenario_add_new_capability_flag`              | Add a flag, check default provider behaviour | Existing providers unaffected            |
| `test_scenario_provider_switch_from_shell_to_claude` | Detect claude in existing shell pane         | Returns `ClaudeProvider`                 |
| `test_scenario_foreign_window_detection`             | emdash-claude-main-abc:@0 foreign window     | Provider auto-detected from session name |
