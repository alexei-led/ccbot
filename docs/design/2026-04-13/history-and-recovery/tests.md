# History and Recovery — Test Specification

## Unit Tests

| Name                                                       | Scenario                            | Expected                                                                |
| ---------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------- |
| `test_history_build_page_pagination`                       | 50 entries, page 2 of 3             | Correct slice + prev/next keyboard                                      |
| `test_history_expandable_quote_atomicity`                  | Long tool result spans pages        | Quote not split mid-sentinel                                            |
| `test_resume_list_scans_past_sessions`                     | Mocked provider.discover_transcript | Returns session picker list                                             |
| `test_resume_picker_pagination`                            | 100 past sessions                   | Pages shown with 10 per page                                            |
| `test_restore_recovery_keyboard_claude`                    | Claude dead window                  | Fresh/Continue/Resume buttons                                           |
| `test_restore_recovery_keyboard_shell`                     | Shell dead window                   | Fresh only (no continue/resume)                                         |
| `test_command_history_keep_last_20`                        | Add 25 commands                     | Oldest 5 dropped                                                        |
| `test_command_history_per_topic_isolation`                 | Add in topic A, query topic B       | B empty                                                                 |
| `test_sync_command_audit_report`                           | Seed inconsistency                  | Report includes issue                                                   |
| `test_transcript_discovery_codex`                          | Codex session file appears          | `register_hookless_session` called                                      |
| `test_transcript_discovery_triggers_shell_setup_on_switch` | Claude pane → shell pane            | `shell_prompt_orchestrator.ensure_setup(..., "provider_switch")` called |

## Integration Contract Tests

| Name                                                | Scenario                          | Expected                                                        |
| --------------------------------------------------- | --------------------------------- | --------------------------------------------------------------- |
| `test_history_uses_window_view_for_transcript_path` | History call                      | `view_window(wid).transcript_path` read, not `get_window_state` |
| `test_sessions_dashboard_kill_action`               | Tap kill                          | `tmux_manager.kill_window` called; state pruned                 |
| `test_recovery_continue_uses_provider_capability`   | Provider without continue support | Button disabled or absent                                       |

## Boundary Tests

| Name                                       | Scenario                                | Expected                 |
| ------------------------------------------ | --------------------------------------- | ------------------------ |
| `test_history_empty_window`                | No transcript                           | "No history" message     |
| `test_resume_unknown_session`              | Session deleted between list and select | Error handled            |
| `test_sync_no_changes`                     | All state consistent                    | "Nothing to sync" report |
| `test_transcript_discovery_race_with_hook` | Hook fires during discovery             | No duplicate entries     |

## Behavior Tests

| Name                                          | Scenario                                           | Expected                                  |
| --------------------------------------------- | -------------------------------------------------- | ----------------------------------------- |
| `test_scenario_history_pagination_round_trip` | Open history → next → prev                         | Same page returned                        |
| `test_scenario_restore_dead_window`           | Window dies → /restore → Continue → Claude resumes | Window recreated with resume flag         |
| `test_scenario_codex_transcript_discovery`    | Start codex externally                             | Session discovered and shown in /sessions |
