# Send Command — Test Specification

## Unit Tests

### send_security

| Name                                      | Scenario                         | Expected        |
| ----------------------------------------- | -------------------------------- | --------------- |
| `test_is_path_contained_inside`           | `/cwd/sub/file.txt` under `/cwd` | True            |
| `test_is_path_contained_traversal`        | `/cwd/../etc/passwd`             | False           |
| `test_is_path_contained_symlink_escape`   | Symlink pointing outside cwd     | False           |
| `test_is_hidden_dotfile`                  | `.env`                           | True            |
| `test_is_hidden_in_dotdir`                | `.git/config`                    | True            |
| `test_matches_secret_pattern_pem`         | `server.pem`                     | Returns pattern |
| `test_matches_secret_pattern_env`         | `.env.production`                | Returns pattern |
| `test_is_gitignored_via_git_check_ignore` | Mocked git                       | True            |
| `test_is_gitignored_pathspec_fallback`    | Non-git repo                     | Uses pathspec   |
| `test_check_gitleaks_rules`               | Fixture gitleaks.toml with rule  | Returns rule id |
| `test_check_size_limit_exceeded`          | 60MB file                        | Returns error   |
| `test_check_size_limit_ok`                | 1MB file                         | Returns None    |
| `test_is_excluded_dir_node_modules`       | `node_modules`                   | True            |

### send_command

| Name                                       | Scenario                       | Expected                     |
| ------------------------------------------ | ------------------------------ | ---------------------------- |
| `test_find_files_exact_match`              | `docs/arch.png` exists         | Returns [path]               |
| `test_find_files_glob`                     | `*.png` with 3 pngs            | Returns all                  |
| `test_find_files_substring`                | `arch` matches `docs/arch.png` | Returns path                 |
| `test_format_file_label_small`             | 1KB file                       | `"foo.txt (1.0K)"`           |
| `test_format_file_label_long_truncation`   | 30-char path + size            | Truncated to ≤24 chars total |
| `test_format_file_label_just_under_budget` | Exactly 23 chars               | Preserved                    |
| `test_is_image_png`                        | `.png`                         | True                         |
| `test_is_image_txt`                        | `.txt`                         | False                        |
| `test_walk_filtered_prunes_excluded_dirs`  | `node_modules` subdir          | Not walked                   |
| `test_safe_mtime_missing_file`             | Deleted file                   | Returns 0.0                  |

## Integration Contract Tests

| Name                                       | Scenario                     | Expected                                     |
| ------------------------------------------ | ---------------------------- | -------------------------------------------- |
| `test_send_command_exact_path_uploads`     | `/send docs/a.png`           | validate_sendable passes, upload_file called |
| `test_send_command_denied_path`            | `/send .env`                 | User notified, no upload                     |
| `test_send_callbacks_private_import_fixed` | grep for `_upload_file`      | Renamed to `upload_file` (public)            |
| `test_open_file_browser_public_api`        | `toolbar._builtin_send` call | Works with public signature                  |

## Boundary Tests

| Name                           | Scenario                                   | Expected                       |
| ------------------------------ | ------------------------------------------ | ------------------------------ |
| `test_file_deleted_mid_upload` | TOCTOU — file gone between list and upload | Error handled gracefully       |
| `test_path_with_spaces`        | `/send "file with spaces.png"`             | Resolves correctly             |
| `test_max_results_truncation`  | 100 matches, limit 50                      | First 50 shown with "... more" |
| `test_cancel_during_browse`    | Tap cancel in file picker                  | State cleared                  |

## Behavior Tests

| Name                                       | Scenario                                  | Expected                     |
| ------------------------------------------ | ----------------------------------------- | ---------------------------- |
| `test_scenario_browse_upload_flow`         | `/send` → root → navigate → file → upload | Photo appears in topic       |
| `test_scenario_gitignored_file_denied`     | `/send build/output.zip`                  | Denied with gitignore reason |
| `test_scenario_glob_with_multiple_matches` | `/send *.log` with 3 logs                 | Picker shown with 3 options  |
