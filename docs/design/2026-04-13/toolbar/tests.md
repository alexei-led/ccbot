# Toolbar — Test Specification

## Unit Tests

### Keyboard builder (`handlers/toolbar_keyboard.py`)

| Name                                                | Scenario                                                    | Expected                                                                    |
| --------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------- |
| `test_build_keyboard_default_claude_layout`         | Provider "claude", no TOML                                  | 3×3 emoji_text grid matching built-in defaults                              |
| `test_build_keyboard_fallback_for_unknown_provider` | Provider "aider" (unknown)                                  | Falls back to Claude layout                                                 |
| `test_build_keyboard_with_label_override`           | `_set_action_label("@5", "mode", "Plan")` then build        | "Plan" appears on the mode button                                           |
| `test_build_keyboard_style_emoji_only`              | TOML style = "emoji"                                        | Buttons show emoji only, no text                                            |
| `test_build_keyboard_style_text_only`               | TOML style = "text"                                         | Buttons show text only, no emoji                                            |
| `test_build_keyboard_callback_data_format`          | Built keyboard                                              | Every button's callback_data = `tb:{window_id}:{action_name}` and ≤64 bytes |
| `test_clear_labels_on_window_cleanup`               | Register, set label, fire `@topic_state.fire("window", @5)` | Label dict empty for @5                                                     |

### Callback parsing (`handlers/toolbar_callbacks.py`)

| Name                                      | Scenario                       | Expected                                 |
| ----------------------------------------- | ------------------------------ | ---------------------------------------- |
| `test_parse_callback_data_valid`          | `"tb:@5:mode"`                 | Returns `("@5", "mode")`                 |
| `test_parse_callback_data_foreign_window` | `"tb:emdash-claude-x:@0:mode"` | Returns `("emdash-claude-x:@0", "mode")` |
| `test_parse_callback_data_malformed`      | `"garbage"`                    | Returns `None`                           |
| `test_parse_callback_data_missing_action` | `"tb:@5"`                      | Returns `None`                           |

### Dispatch (`handlers/toolbar_callbacks.py`)

| Name                               | Scenario                                            | Expected                                                          |
| ---------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------- |
| `test_dispatch_key_action`         | Action type="key", payload="C-c"                    | `tmux_manager.send_keys("@5", "C-c", enter=False)`                |
| `test_dispatch_text_action`        | Action type="text", payload="/clear"                | `tmux_manager.send_keys("@5", "/clear", raw=True)` + Enter        |
| `test_dispatch_literal_key`        | Action type="key", literal=True, payload=`'\x1b[Z'` | `send_keys(..., literal=True)`                                    |
| `test_dispatch_builtin_screenshot` | Action type="builtin", payload="screen"             | `_builtin_screenshot` called                                      |
| `test_dispatch_unknown_builtin`    | Action type="builtin", payload="nonsense"           | `query.answer("Unknown builtin: nonsense", show_alert=True)`      |
| `test_dispatch_rejects_non_owner`  | `user_owns_window` returns False                    | `query.answer("Not your session", show_alert=True)` — no key sent |

### Mode scraping (moved to `providers/claude.py`)

| Name                                      | Scenario                                           | Expected       |
| ----------------------------------------- | -------------------------------------------------- | -------------- |
| `test_scrape_current_mode_auto_accept`    | Pane text contains "auto-accept edits on"          | Returns "Edit" |
| `test_scrape_current_mode_plan`           | Pane text contains "Plan mode on"                  | Returns "Plan" |
| `test_scrape_current_mode_full_tool`      | Pane text contains "Full tool access on"           | Returns "Full" |
| `test_scrape_current_mode_default`        | Pane text contains no mode indicator               | Returns None   |
| `test_scrape_current_mode_empty_pane`     | Empty capture                                      | Returns None   |
| `test_scrape_current_mode_other_provider` | `ShellProvider.scrape_current_mode` (default impl) | Returns None   |

## Integration Contract Tests

| Name                                              | Scenario                                     | Expected                                                                                                                  |
| ------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `test_refresh_button_label_claude_plan`           | Provider = Claude, pane shows "Plan mode on" | `_set_action_label` stores "Plan"; keyboard rebuilt with new label                                                        |
| `test_refresh_button_label_no_scraping_for_shell` | Provider = Shell                             | `scrape_current_mode` returns None; static default label stays                                                            |
| `test_builtin_send_uses_window_view`              | `_builtin_send` call                         | `session_manager.view_window(window_id)` called; cwd extracted; `send_command.open_file_browser` called with correct args |
| `test_toolbar_config_reload`                      | `reload_toolbar_config()`                    | Next `_get_toolbar_config()` returns a fresh instance                                                                     |

## Boundary Tests

| Name                                  | Scenario                                    | Expected                                |
| ------------------------------------- | ------------------------------------------- | --------------------------------------- |
| `test_callback_data_at_64_byte_limit` | Action name = 24 chars, window_id = `@9999` | Callback data ≤ 64 bytes                |
| `test_action_name_truncation`         | Action name exceeds 24 chars at config load | Config loader drops the action and logs |
| `test_toolbar_config_malformed_toml`  | Invalid TOML on disk                        | Falls back to defaults, logs            |
| `test_scrape_current_mode_pane_error` | `tmux_manager.capture_pane` raises          | Returns None, no crash                  |

## Behavior Tests

| Name                                       | Scenario                                  | Expected                                                                                           |
| ------------------------------------------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `test_scenario_mode_toggle_updates_button` | User taps "Mode" button                   | Shift+Tab sent; pane scraped after 250ms; button label updates to new mode; toast echoes the label |
| `test_scenario_send_builtin_opens_browser` | User taps "Send" on toolbar               | File browser appears with cwd listing                                                              |
| `test_scenario_live_builtin_starts_view`   | User taps "Live" button                   | `live_view.start_live_view` called, auto-refresh begins                                            |
| `test_scenario_custom_text_action`         | User-defined action with payload="/clear" | `/clear` + Enter sent to tmux                                                                      |
