# Shell Provider UX — Test Specification

## Unit Tests

### Shell Prompt Orchestrator (`handlers/shell_prompt_orchestrator.py`)

Table-driven: rows are `(trigger, skip_flag, marker_present, was_offered) → expected_action`.

| Name                                               | Trigger            | Skip  | Marker | Offered | Expected                                        |
| -------------------------------------------------- | ------------------ | ----- | ------ | ------- | ----------------------------------------------- |
| `test_auto_always_runs`                            | "auto"             | —     | —      | —       | `setup_shell_prompt(clear=True)` called         |
| `test_lazy_no_op_when_marker_present`              | "lazy"             | False | True   | —       | No call                                         |
| `test_lazy_runs_when_marker_missing`               | "lazy"             | False | False  | —       | `setup_shell_prompt(clear=False)` called        |
| `test_lazy_respects_skip_flag`                     | "lazy"             | True  | False  | —       | No call                                         |
| `test_external_bind_shows_offer`                   | "external_bind"    | False | False  | False   | Offer keyboard sent; no setup yet               |
| `test_external_bind_no_offer_if_marker_present`    | "external_bind"    | False | True   | False   | No offer (already set up)                       |
| `test_provider_switch_reoffers_after_skip_cleared` | "provider_switch"  | False | False  | True    | New offer shown                                 |
| `test_provider_switch_respects_skip`               | "provider_switch"  | True  | False  | True    | No offer                                        |
| `test_accept_offer_runs_setup`                     | `accept_offer(@5)` | —     | False  | —       | `setup_shell_prompt` called, `was_offered=True` |
| `test_record_skip_sets_flag`                       | `record_skip(@5)`  | —     | —      | —       | State has `skip_flag=True`                      |

### Shell Context (`handlers/shell_context.py`)

| Name                                     | Scenario                                        | Expected                                |
| ---------------------------------------- | ----------------------------------------------- | --------------------------------------- |
| `test_gather_llm_context_truncates_pane` | Pane text 10000 chars                           | Returns last N lines under token budget |
| `test_gather_llm_context_empty_pane`     | Empty capture                                   | Returns empty-context marker            |
| `test_gather_llm_context_non_shell_pane` | Pane running agent, not shell                   | Returns empty or early return           |
| `test_redact_for_llm_env_var`            | Context contains `AWS_ACCESS_KEY_ID=AKIA...`    | Redacted to `AWS_ACCESS_KEY_ID=***`     |
| `test_redact_for_llm_bearer_token`       | Context contains `Authorization: Bearer abc123` | Redacted                                |
| `test_redact_for_llm_safe_text`          | Regular shell output                            | Unchanged                               |
| `test_mark_telegram_command_adds_marker` | New command dispatched                          | Pending-command dict has entry          |
| `test_detect_shell_tools_modern_in_path` | `rg`/`fd`/`bat` on PATH                         | Returns detected list                   |

### Shell Commands (`handlers/shell_commands.py`)

| Name                                                  | Scenario                   | Expected                                                     |
| ----------------------------------------------------- | -------------------------- | ------------------------------------------------------------ |
| `test_is_dangerous_command_rm_rf`                     | `rm -rf /`                 | True                                                         |
| `test_is_dangerous_command_safe_ls`                   | `ls -la`                   | False                                                        |
| `test_ensure_prompt_marker_delegates_to_orchestrator` | Called pre-send            | `shell_prompt_orchestrator.ensure_setup(..., "lazy")` called |
| `test_build_approval_keyboard`                        | Command + explanation      | Keyboard has Run / Edit / Cancel buttons                     |
| `test_cancel_stuck_input_sends_ctrl_c`                | Pane shows partial command | `tmux_manager.send_keys("C-c")` called                       |

### Shell Capture (`handlers/shell_capture.py`)

| Name                                       | Scenario                            | Expected                         |
| ------------------------------------------ | ----------------------------------- | -------------------------------- |
| `test_parse_output_with_marker`            | Pane contains cmd + output + marker | Returns (output_text, exit_code) |
| `test_parse_output_baseline_diff_fallback` | No marker found                     | Uses baseline-diff fallback      |
| `test_strip_glyphs`                        | Text with decorative Unicode        | Cleaned text                     |
| `test_format_relay_success`                | Exit code 0                         | Relay without error indicator    |
| `test_format_relay_failure`                | Exit code 127                       | Relay with error suggestion      |
| `test_error_suggestion_command_not_found`  | "command not found: fd"             | Suggests "install fd"            |

### Shell Infra (`providers/shell_infra.py`)

| Name                                       | Scenario                          | Expected                               |
| ------------------------------------------ | --------------------------------- | -------------------------------------- |
| `test_match_prompt_wrap_mode`              | Line contains `⌘5⌘`               | Returns `PromptMatch(sequence=5, ...)` |
| `test_match_prompt_replace_mode`           | Line = `ccgram:5❯`                | Returns `PromptMatch(sequence=5, ...)` |
| `test_match_prompt_no_match`               | Regular shell line                | Returns None                           |
| `test_has_prompt_marker_cached`            | Called twice                      | Second call hits cache                 |
| `test_detect_pane_shell_bash`              | Pane command = "bash"             | Returns "bash"                         |
| `test_detect_pane_shell_with_args`         | Pane command = "fish -l"          | Returns "fish"                         |
| `test_wrap_setup_commands_fish`            | shell="fish"                      | Returns fish-specific prompt wrap      |
| `test_wrap_setup_commands_zsh`             | shell="zsh"                       | Returns zsh-specific prompt wrap       |
| `test_is_interactive_shell_at_prompt`      | Pane shows shell prompt           | True                                   |
| `test_is_interactive_shell_running_script` | Pane shows running command        | False                                  |
| `test_setup_shell_prompt_skips_own_window` | window_id == config.own_window_id | No-op                                  |

## Integration Contract Tests

| Name                                    | Scenario                        | Expected                                                  |
| --------------------------------------- | ------------------------------- | --------------------------------------------------------- |
| `test_handle_shell_message_with_llm`    | Text message, LLM configured    | LLM called, approval keyboard shown                       |
| `test_handle_shell_message_bang_prefix` | `!ls -la`                       | Command sent raw, no LLM                                  |
| `test_handle_shell_message_no_llm`      | Text message, no LLM configured | All text sent as raw command                              |
| `test_shell_capture_relay_to_queue`     | Fresh pane output               | `message_queue.enqueue_content_message` called with parts |

## Boundary Tests

| Name                                        | Scenario                              | Expected                                       |
| ------------------------------------------- | ------------------------------------- | ---------------------------------------------- |
| `test_ensure_setup_unknown_shell`           | `detect_pane_shell` returns "unknown" | Falls back to bash-compatible wrapper, logs    |
| `test_ensure_setup_own_window`              | window_id == own                      | Orchestrator early-returns before setup        |
| `test_ensure_setup_tmux_error`              | `tmux_manager.send_keys` raises       | Exception logged, orchestrator state unchanged |
| `test_capture_no_prompt_marker_no_baseline` | Fresh window, nothing to diff         | Returns empty, no crash                        |
| `test_redact_multiple_secrets_same_line`    | Line with 2 bearer tokens             | Both redacted                                  |

## Behavior Tests

| Name                                                    | Scenario                                               | Expected                                                                                                       |
| ------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `test_scenario_auto_setup_on_new_shell_topic`           | Directory browser creates shell topic                  | `ensure_setup(wid, "auto")` → marker injected immediately                                                      |
| `test_scenario_external_bind_offer_flow`                | User binds existing tmux shell window                  | Offer keyboard shown; tap Set up → marker injected                                                             |
| `test_scenario_skip_is_session_scoped`                  | User taps Skip on one bind; later re-binds same window | Offer shown again (skip is session-scoped, not persistent)                                                     |
| `test_scenario_lazy_recovery_after_exec_bash`           | Running window runs `exec bash`, marker lost           | Next command dispatch triggers lazy re-setup                                                                   |
| `test_scenario_nl_to_command_round_trip`                | User sends "list the largest files"                    | LLM returns `du -ah \| sort -rh \| head`, approval keyboard shown, user approves, command runs, output relayed |
| `test_scenario_dangerous_command_requires_confirmation` | LLM returns `rm -rf /tmp/*`                            | Approval keyboard has Confirm-Danger button instead of Run                                                     |
