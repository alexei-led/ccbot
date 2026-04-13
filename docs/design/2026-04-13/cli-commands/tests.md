# CLI Commands (no-bot) — Test Specification

## Unit Tests

### doctor_cmd

| Name                                 | Scenario                                | Expected                    |
| ------------------------------------ | --------------------------------------- | --------------------------- |
| `test_check_hooks_installed_present` | Fixture settings.json with ccgram hooks | OK                          |
| `test_check_hooks_installed_missing` | Settings without hooks                  | Reports issue               |
| `test_check_session_map_readable`    | Valid file                              | OK                          |
| `test_check_state_json_readable`     | Valid file                              | OK                          |
| `test_check_tmux_session_exists`     | Mocked tmux list-sessions               | OK                          |
| `test_check_provider_cli_on_path`    | Mocked `shutil.which`                   | Reports status per provider |
| `test_fix_installs_missing_hooks`    | `--fix` mode                            | `hook.install()` called     |
| `test_fix_kills_orphans`             | Orphan process detected                 | `kill` called               |

### status_cmd

| Name                         | Scenario          | Expected                 |
| ---------------------------- | ----------------- | ------------------------ |
| `test_status_no_bot_running` | No active session | Reports "not running"    |
| `test_status_with_bindings`  | Seeded state      | Reports count + bindings |

### hook.py

| Name                                         | Scenario                             | Expected                    |
| -------------------------------------------- | ------------------------------------ | --------------------------- |
| `test_hook_install_merges_with_existing`     | Existing user hooks in settings.json | Merged without clobbering   |
| `test_hook_install_all_event_types`          | Fresh install                        | All 9 event types added     |
| `test_hook_uninstall_preserves_user_entries` | Install + uninstall                  | User hooks intact           |
| `test_hook_session_start_writes_session_map` | Stdin SessionStart JSON              | Entry in session_map.json   |
| `test_hook_notification_writes_events_jsonl` | Stdin Notification JSON              | Line appended               |
| `test_hook_respects_claude_config_dir_env`   | `CLAUDE_CONFIG_DIR` set              | Install targets custom dir  |
| `test_hook_status_reports_all_types`         | Partial install                      | Reports which types missing |

## Integration Contract Tests

| Name                                      | Scenario                                  | Expected            |
| ----------------------------------------- | ----------------------------------------- | ------------------- |
| `test_doctor_fix_end_to_end`              | Run `ccgram doctor --fix` on broken setup | Setup becomes valid |
| `test_hook_install_uninstall_idempotent`  | Install twice, uninstall twice            | Final state clean   |
| `test_msg_cli_send_creates_mailbox_entry` | `ccgram msg send peer "hi"`               | File in peer inbox  |

## Boundary Tests

| Name                                        | Scenario                  | Expected                 |
| ------------------------------------------- | ------------------------- | ------------------------ |
| `test_hook_install_corrupted_settings_json` | Invalid JSON              | Refuses, doesn't clobber |
| `test_hook_install_readonly_filesystem`     | Read-only home            | Clear error message      |
| `test_doctor_tmux_not_installed`            | `which tmux` returns None | Reports missing dep      |

## Behavior Tests

| Name                                          | Scenario       | Expected                                  |
| --------------------------------------------- | -------------- | ----------------------------------------- |
| `test_scenario_first_time_setup_via_doctor`   | Fresh machine  | `doctor --fix` results in a working setup |
| `test_scenario_upgrade_preserves_hook_config` | Upgrade ccgram | Existing hooks stay installed             |
