# Bot Composition Root — Test Specification

## Unit Tests

| Name                                     | Scenario                                    | Expected                |
| ---------------------------------------- | ------------------------------------------- | ----------------------- |
| `test_is_user_allowed_in_list`           | Config allowed_users = [123], user_id = 123 | True                    |
| `test_is_user_allowed_not_in_list`       | user_id = 999                               | False                   |
| `test_is_user_allowed_no_list`           | allowed_users = [] (allow-all)              | True                    |
| `test_new_command_calls_orchestration`   | Mocked `orchestrate_new_topic`              | Called once with update |
| `test_history_command_delegates`         | Mocked `history.show_history`               | Called                  |
| `test_text_handler_delegates_to_routing` | Mocked `message_routing.handle_text`        | Called                  |
| `test_global_exception_handler_swallows` | Raise `SomeError`                           | No propagation          |
| `test_error_handler_logs_retry_after`    | RetryAfter exception                        | Logged, not crashed     |

## Integration Contract Tests

| Name                                         | Scenario                            | Expected                                                                                                                      |
| -------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `test_create_bot_returns_application`        | Call create_bot() with valid config | Returns `Application` instance                                                                                                |
| `test_create_bot_registers_all_handlers`     | Count handlers after create_bot     | Matches expected count per group                                                                                              |
| `test_post_init_startup_order`               | Capture call order via mocks        | resolve_stale_ids → prune_stale_state → load_session_map → start_session_monitor → start_polling → check_hooks → notify_start |
| `test_post_stop_sends_shutdown_notification` | Configured group id                 | Notification sent                                                                                                             |
| `test_post_shutdown_flushes_state`           | Mutations pending                   | `flush_state()` called before cancel                                                                                          |

## Boundary Tests

| Name                                         | Scenario                             | Expected                         |
| -------------------------------------------- | ------------------------------------ | -------------------------------- |
| `test_create_bot_missing_token_raises`       | Config with empty token              | Raises before Application starts |
| `test_post_init_hooks_missing_warns`         | Claude hooks not installed           | Startup proceeds, warning logged |
| `test_post_shutdown_handles_cancelled_tasks` | Running tasks cancelled mid-shutdown | No unhandled exceptions          |

## Behavior Tests

| Name                                              | Scenario          | Expected                                       |
| ------------------------------------------------- | ----------------- | ---------------------------------------------- |
| `test_scenario_cold_start_startup`                | Empty state dir   | Bot starts, no errors, empty window list       |
| `test_scenario_warm_start_restores_bindings`      | Seeded state.json | Thread bindings restored, display names synced |
| `test_scenario_graceful_shutdown_preserves_state` | Mutate, shutdown  | state.json updated on disk                     |
