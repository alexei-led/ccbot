# Directory Browser — Test Specification

## Unit Tests

| Name                                        | Scenario                  | Expected                                                                |
| ------------------------------------------- | ------------------------- | ----------------------------------------------------------------------- |
| `test_project_markers_git`                  | Dir with `.git`           | Highlighted as project                                                  |
| `test_project_markers_pyproject`            | Dir with `pyproject.toml` | Highlighted                                                             |
| `test_project_markers_none`                 | Plain dir                 | Not highlighted                                                         |
| `test_build_root_keyboard_favorites_first`  | Favorites present         | Favorites above plain dirs                                              |
| `test_build_provider_keyboard_all_options`  | All providers             | Claude/Codex/Gemini/Shell buttons                                       |
| `test_build_mode_keyboard_capability_gated` | Claude only               | YOLO button present for Claude, absent for others (via capability flag) |
| `test_parse_fav_index_valid`                | `"fav:3"`                 | Returns 3                                                               |
| `test_parse_fav_index_invalid`              | `"fav:xyz"`               | Returns None                                                            |
| `test_parse_mode_select`                    | `"mode:claude:yolo"`      | Returns `("claude", "yolo")`                                            |

## Integration Contract Tests

| Name                                         | Scenario                                          | Expected                                                                                                             |
| -------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `test_create_window_and_bind_ordering`       | Mocked tmux, shell_prompt_orchestrator, msg_skill | Order: create_window → set_display_name → set_provider → install_skill → ensure_shell_setup → bind → forward pending |
| `test_yolo_confirmation_via_capability_flag` | Claude with yolo mode                             | `_accept_yolo_confirmation` called                                                                                   |
| `test_yolo_confirmation_skipped_for_codex`   | Codex (no capability)                             | `_accept_yolo_confirmation` NOT called                                                                               |
| `test_install_messaging_skill_claude_only`   | Shell provider                                    | `msg_skill.install` NOT called                                                                                       |

## Boundary Tests

| Name                                | Scenario          | Expected                                       |
| ----------------------------------- | ----------------- | ---------------------------------------------- |
| `test_browser_deep_path_truncation` | Very long path    | Label truncated to ≤24 chars for callback_data |
| `test_browser_no_readable_dirs`     | Permission errors | Handled gracefully                             |
| `test_show_hidden_dirs_flag`        | Config flag true  | Dotfiles visible                               |
| `test_cancel_cleans_user_state`     | User taps cancel  | `context.user_data` cleared of browser keys    |

## Behavior Tests

| Name                                               | Scenario                                                                    | Expected                                                     |
| -------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `test_scenario_full_topic_creation_flow`           | First message → root → navigate → select → provider → mode → window created | Topic bound, message forwarded                               |
| `test_scenario_favorite_creation_via_star`         | Navigate to dir → star → view favorites                                     | Dir appears                                                  |
| `test_scenario_external_bind_via_window_callbacks` | Existing tmux window picker                                                 | Bind without window creation, correct provider auto-detected |
