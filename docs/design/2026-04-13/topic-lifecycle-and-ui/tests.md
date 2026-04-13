# Topic Lifecycle and Interactive UI — Test Specification

## Unit Tests

### topic_state_registry (standalone, not the bound-method tests which are in polling-and-events)

| Name                                          | Scenario                         | Expected                                     |
| --------------------------------------------- | -------------------------------- | -------------------------------------------- |
| `test_register_scope_window_fires_for_window` | @register("window"), fire window | Called                                       |
| `test_register_scope_topic_fires_for_topic`   | @register("topic"), fire topic   | Called                                       |
| `test_fire_non_existent_id`                   | No registrations                 | Returns without error                        |
| `test_qualified_scope_routes_foreign_ids`     | `session:@N` fire                | Both "window" and "qualified" callbacks fire |

### topic_lifecycle

| Name                                      | Scenario                               | Expected                                      |
| ----------------------------------------- | -------------------------------------- | --------------------------------------------- |
| `test_autoclose_done_topic_after_timeout` | Done state, advance past autoclose TTL | Topic closed                                  |
| `test_autoclose_reset_on_activity`        | Timer running, activity arrives        | Timer reset                                   |
| `test_dead_ttl_prunes_binding`            | Dead state past TTL                    | Binding removed                               |
| `test_topic_closed_handler_cleans_state`  | Simulated topic close                  | `fire("topic", user_id, thread_id)` triggered |
| `test_unbound_window_ttl`                 | Window unbound past TTL                | Pruned                                        |

### topic_emoji

| Name                                       | Scenario                  | Expected           |
| ------------------------------------------ | ------------------------- | ------------------ |
| `test_debounce_prevents_rapid_updates`     | 5 state changes in 1s     | Only final applied |
| `test_active_badge_preserves_yolo`         | Active state + yolo flag  | Both badges shown  |
| `test_state_change_schedules_emoji_update` | Change from idle → active | Rename scheduled   |

### interactive_ui

| Name                                    | Scenario                   | Expected              |
| --------------------------------------- | -------------------------- | --------------------- |
| `test_build_ask_user_question_keyboard` | Options list               | Keyboard per option   |
| `test_build_permission_keyboard`        | Permission request         | Allow/Deny buttons    |
| `test_build_exit_plan_mode_keyboard`    | Plan mode exit             | Accept/Reject buttons |
| `test_cooldown_prevents_double_send`    | Send twice within cooldown | Second skipped        |

## Integration Contract Tests

| Name                                          | Scenario                           | Expected                                         |
| --------------------------------------------- | ---------------------------------- | ------------------------------------------------ |
| `test_interactive_alert_dispatches_to_tmux`   | User taps Enter on AskUserQuestion | `send_keys(window_id, "Enter")` called           |
| `test_polling_loop_fires_topic_cleanup`       | Polling detects topic closed       | `fire("topic", ...)` triggers registered cleanup |
| `test_topic_closed_handler_kills_tmux_window` | Topic close → cleanup              | `tmux_manager.kill_window` called                |

## Boundary Tests

| Name                                   | Scenario          | Expected                                         |
| -------------------------------------- | ----------------- | ------------------------------------------------ |
| `test_topic_closed_for_unbound_topic`  | No binding        | No-op, no error                                  |
| `test_interactive_ui_pane_id_routing`  | Multi-pane prompt | Callback data includes pane_id, routed correctly |
| `test_autoclose_timer_past_and_future` | Mix               | Correct pruning                                  |

## Behavior Tests

| Name                                          | Scenario                                                     | Expected                          |
| --------------------------------------------- | ------------------------------------------------------------ | --------------------------------- |
| `test_scenario_topic_full_lifecycle`          | Create → active → idle → done → autoclose                    | Topic removed, tmux window killed |
| `test_scenario_interactive_round_trip`        | AskUserQuestion appears → user taps option → agent continues | Correct key sent, state cleared   |
| `test_scenario_rapid_state_changes_debounced` | Active→idle→active within 1s                                 | Only one emoji update visible     |
