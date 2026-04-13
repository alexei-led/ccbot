# Screenshot and Live View — Test Specification

## Unit Tests

### Screenshot rendering

| Name                                       | Scenario                     | Expected                             |
| ------------------------------------------ | ---------------------------- | ------------------------------------ |
| `test_text_to_image_ansi_colours`          | Fixture ANSI text            | PNG bytes (hash matches fixture)     |
| `test_text_to_image_font_fallback`         | Text with emoji              | Renders without crash                |
| `test_build_screenshot_keyboard_no_pane`   | Single-pane window           | Keyboard has control keys + refresh  |
| `test_build_screenshot_keyboard_with_pane` | Multi-pane, specific pane_id | Keys encode pane_id in callback data |
| `test_parse_target_window_only`            | `"@5"`                       | `("@5", None)`                       |
| `test_parse_target_window_with_pane`       | `"@5:%3"`                    | `("@5", "%3")`                       |

### Status Bar Actions (NEW module)

| Name                                  | Scenario                    | Expected                                               |
| ------------------------------------- | --------------------------- | ------------------------------------------------------ |
| `test_notify_toggle_cycles_mode`      | Current="all", tap          | New="errors_only", status bubble re-rendered           |
| `test_status_recall_shows_history`    | Window with 3 past commands | Picker keyboard with 3 entries                         |
| `test_status_esc_sends_escape_key`    | Tap                         | `send_keys(window_id, "Escape")`                       |
| `test_remote_control_toggle`          | First tap                   | RC active; status bubble updated                       |
| `test_schedule_key_refresh`           | Tap quick-key button        | Refresh scheduled after delay, pane re-screenshot sent |
| `test_clear_key_refreshes_on_cleanup` | Window close                | Pending refresh cancelled                              |

### Live View

| Name                                  | Scenario                   | Expected                        |
| ------------------------------------- | -------------------------- | ------------------------------- |
| `test_start_live_view_creates_state`  | Start for topic            | `_active_views` has entry       |
| `test_start_live_view_rejects_second` | Already active             | Rejected or replaces            |
| `test_tick_skips_unchanged_content`   | Same hash as last          | `edit_message_media` NOT called |
| `test_tick_edits_on_change`           | Different hash             | `edit_message_media` called     |
| `test_auto_stop_after_timeout`        | Advance clock past timeout | View stopped, entry removed     |

## Integration Contract Tests

| Name                                         | Scenario                                 | Expected                                                                              |
| -------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------- |
| `test_screenshot_command_captures_and_sends` | Mocked tmux capture + bot.send_photo     | Photo sent with keyboard                                                              |
| `test_panes_command_lists_all_panes`         | Window with 3 panes                      | Per-pane screenshot buttons                                                           |
| `test_live_tick_driven_by_periodic_tasks`    | `periodic_tasks.run_periodic_tasks(bot)` | `live_view.tick_all_views(bot)` called                                                |
| `test_status_bar_actions_separate_module`    | Import check                             | Status-bar callbacks registered from `status_bar_actions`, not `screenshot_callbacks` |

## Boundary Tests

| Name                                | Scenario              | Expected                    |
| ----------------------------------- | --------------------- | --------------------------- |
| `test_screenshot_pane_too_large`    | 10000+ line pane      | Rendering truncated safely  |
| `test_live_view_pane_disappears`    | Tick when window gone | View stopped, user notified |
| `test_notify_toggle_unknown_window` | Stale window_id       | Error answer, no crash      |

## Behavior Tests

| Name                                       | Scenario                                   | Expected                                       |
| ------------------------------------------ | ------------------------------------------ | ---------------------------------------------- |
| `test_scenario_live_view_round_trip`       | Start → pane changes → auto-refresh → stop | 2-3 edits, then timeout and stop               |
| `test_scenario_screenshot_key_refresh`     | Tap "Esc" button on status                 | Escape sent; screenshot refreshed ~300ms later |
| `test_scenario_panes_command_empty_window` | Window with 0 panes (shouldn't happen)     | Empty picker or error                          |
