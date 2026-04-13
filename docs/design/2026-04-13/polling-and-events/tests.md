# Polling and Events — Test Specification

## Unit Tests

### Topic State Registry (`handlers/topic_state_registry.py`) — with bound-method support

| Name                                            | Scenario                                                | Expected                                                 |
| ----------------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------- |
| `test_register_free_function_window_scope`      | `@topic_state.register("window")` on free function      | `fire("window", "@5")` calls it with `"@5"`              |
| `test_register_bound_method_window_scope` (NEW) | `topic_state.register_bound("window", instance.method)` | `fire("window", "@5")` calls `instance.method("@5")`     |
| `test_register_bound_topic_scope`               | Bound method on `"topic"` scope                         | `fire("topic", user_id, thread_id)` calls with both args |
| `test_fire_unknown_scope`                       | `fire("foo", ...)`                                      | Raises or logs; no callback invoked                      |
| `test_multiple_callbacks_fire_in_order`         | Two `@register` on same scope                           | Both called in registration order                        |
| `test_failing_callback_does_not_block_others`   | First callback raises                                   | Second still called                                      |

### Terminal Screen Buffer (split from `TerminalStatusStrategy`)

| Name                                           | Scenario                             | Expected                             |
| ---------------------------------------------- | ------------------------------------ | ------------------------------------ |
| `test_get_screen_buffer_creates_on_first_call` | Window not in cache                  | New `ScreenBuffer` returned          |
| `test_clear_screen_buffer_removes_entry`       | Cached buffer, then clear            | Cache empty for that window          |
| `test_parse_with_pyte_renders_ansi`            | Fixture ANSI text                    | Returns plain-text render            |
| `test_pane_count_cache_ttl`                    | Record count, advance clock past TTL | Cache expired                        |
| `test_pane_count_cache_single_pane_detection`  | Count = 1                            | `is_single_pane_cached` returns True |
| `test_get_rendered_text_falls_back`            | No render cached                     | Returns fallback text                |

### Terminal Poll State (split from `TerminalStatusStrategy`)

| Name                                       | Scenario                            | Expected                                  |
| ------------------------------------------ | ----------------------------------- | ----------------------------------------- |
| `test_rc_debounce_on_removal`              | Set RC true, then false immediately | Still shows RC (debounced)                |
| `test_rc_debounce_clears_after_interval`   | After debounce window elapsed       | RC now false                              |
| `test_probe_failure_counter_increments`    | Record 3 failures                   | `should_skip_probe` returns True          |
| `test_probe_failure_reset`                 | Reset counter                       | Below threshold again                     |
| `test_startup_grace_period`                | Begin timer, check before elapsed   | `is_startup_expired` False                |
| `test_startup_grace_expired`               | Begin timer, advance past grace     | True                                      |
| `test_unbound_timer_expiry`                | Set timer, advance past TTL         | `get_expired_unbound` includes the window |
| `test_seen_status_tracking`                | `mark_seen_status(@5)`              | `check_seen_status(@5)` True              |
| `test_is_recently_active_with_activity_ts` | Last activity 2s ago                | True                                      |
| `test_is_recently_active_stale`            | Last activity 60s ago               | False                                     |

### Topic Lifecycle Strategy

| Name                                 | Scenario                       | Expected                                      |
| ------------------------------------ | ------------------------------ | --------------------------------------------- |
| `test_autoclose_timer_set_and_clear` | Start timer, clear             | `iter_autoclose_timers` returns empty         |
| `test_dead_notified_dedup`           | Mark dead, query               | `is_dead_notified` True; second mark is no-op |
| `test_typing_throttle_debounce`      | Record sent, immediately check | `is_typing_throttled` True                    |

### Interactive UI Strategy

| Name                                | Scenario                                 | Expected                                              |
| ----------------------------------- | ---------------------------------------- | ----------------------------------------------------- |
| `test_set_pane_alert`               | Set alert for pane                       | `has_pane_alert` True, `get_pane_alert` returns tuple |
| `test_prune_stale_pane_alerts`      | Alert for dead pane, prune with live set | Alert removed                                         |
| `test_clear_pane_alerts_for_window` | Two alerts in one window                 | Both cleared                                          |

### Hook Event Processing (`handlers/hook_events.py`)

| Name                                   | Scenario                                           | Expected                                                      |
| -------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------- |
| `test_handle_session_start`            | Event `SessionStartEvent(session_id=..., cwd=...)` | `session_map_sync.write_entry` called                         |
| `test_handle_stop_enqueues_status`     | Stop event                                         | `status_bubble.enqueue_status_update` called with "Done" text |
| `test_handle_stop_failure_alerts`      | StopFailure event                                  | Error-flagged status update enqueued                          |
| `test_handle_notification_interactive` | Notification event with interactive payload        | `interactive_ui.show_interactive_alert` called                |
| `test_handle_subagent_start`           | SubagentStart event                                | `claude_task_state._active_subagents` updated                 |
| `test_handle_subagent_stop`            | SubagentStop event                                 | Subagent entry removed                                        |
| `test_handle_teammate_idle`            | TeammateIdle event                                 | Notification routed to correct topic                          |

### Claude Task State (`claude_task_state.py`)

| Name                                 | Scenario                          | Expected                              |
| ------------------------------------ | --------------------------------- | ------------------------------------- |
| `test_build_subagent_label_single`   | One active subagent "write-tests" | Returns `"🤖 write-tests"`            |
| `test_build_subagent_label_multiple` | Two active                        | Returns `"🤖 2 subagents"` or similar |
| `test_build_subagent_label_none`     | Empty dict                        | Returns None                          |
| `test_claude_task_snapshot`          | Window with task list             | Returns structured snapshot           |

## Integration Contract Tests

| Name                                              | Scenario                                                        | Expected                                                 |
| ------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------- |
| `test_cleanup_fires_bound_method`                 | Instantiate `TerminalScreenBuffer`, call `fire("window", "@5")` | `clear_screen_buffer("@5")` called (instance method)     |
| `test_status_poll_loop_single_tick`               | Mocked bot, one bound thread, mocked tmux                       | Loop iterates once without error, status update enqueued |
| `test_polling_update_status_skips_missing_window` | Binding points to dead window                                   | Dead window notification dispatched, window pruned       |
| `test_polling_interactive_only_check`             | Pane has pending prompt                                         | `interactive_ui.show_interactive_alert` called           |

## Boundary Tests

| Name                                      | Scenario                                     | Expected                                     |
| ----------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| `test_register_bound_no_instance_raises`  | Register unbound method                      | Raises or rejects                            |
| `test_terminal_screen_buffer_large_pane`  | 10MB pane text                               | Handled without crash (streamed / truncated) |
| `test_poll_loop_exception_in_one_binding` | Binding raises, others proceed               | Loop continues, error logged                 |
| `test_autoclose_timer_negative_ttl`       | TTL of 0                                     | Immediate expiration                         |
| `test_fire_during_register`               | Callback that calls `register` inside itself | No infinite loop (or documented ordering)    |

## Behavior Tests

| Name                                              | Scenario                                                   | Expected                                                                               |
| ------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `test_scenario_cleanup_on_window_close`           | User closes topic; `@topic_state.fire("window", @5)` fires | All registered cleanup callbacks (screen buffer, poll state, toolbar labels, etc.) run |
| `test_scenario_dead_window_detection`             | Window disappears from tmux                                | Dead notification enqueued; state pruned; topic emoji updated                          |
| `test_scenario_subagent_lifecycle`                | SubagentStart → SubagentStop events                        | Label appears in status bubble during; disappears after                                |
| `test_scenario_autoclose_timer_reset_on_activity` | Timer running, new status update arrives                   | Timer cleared; topic stays open                                                        |
