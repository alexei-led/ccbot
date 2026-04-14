# `handlers/polling_coordinator` — Test Specification

The coordinator has almost no logic of its own post-refactor. Tests are
intentionally shallow — they protect the _shape_ of the loop, not its
contents.

## Unit Tests

### `test_status_poll_loop_iterates_all_bindings`

- **Scenario**: Stub `thread_router.iter_thread_bindings` to return
  three tuples. Stub `window_tick.tick_window` to count calls. Run one
  iteration.
- **Expected**: `tick_window` called three times with the expected
  args.

### `test_status_poll_loop_delegates_periodic_tasks`

- **Scenario**: One iteration with empty bindings.
- **Expected**: `periodic_tasks.run_periodic_tasks` called once before
  the iteration; `run_lifecycle_tasks` called once after.

### `test_status_poll_loop_passes_window_lookup_to_tick`

- **Scenario**: `tmux_manager.list_windows` returns `[W_A, W_B]`. One
  binding for window `@A`.
- **Expected**: `tick_window` called with `W_A` as the `window` arg,
  from the lookup — no separate `find_window_by_id` call per binding.

### `test_status_poll_loop_handles_external_sessions`

- **Scenario**: `discover_external_sessions` returns emdash windows
  with qualified IDs (`emdash-claude-main-abc:@0`).
- **Expected**: Those windows appear in the lookup map.

### `test_status_poll_loop_respects_config_interval`

- **Scenario**: Config `status_poll_interval` = 2.5.
- **Expected**: After one iteration, sleeps for 2.5 seconds.

## Integration Contract Tests

### `test_imports_are_minimal`

- **Scenario**: AST walk of `polling_coordinator.py`.
- **Expected**: Imports only from `window_tick`, `periodic_tasks`,
  `tmux_manager`, `thread_router`, `config`, `utils`, `structlog`, and
  `telegram.error` (for backoff). The full list is explicit in the
  design doc and this test uses it as a whitelist.

### `test_does_not_import_per_window_modules`

- **Scenario**: Same AST walk.
- **Expected**: Zero imports from `interactive_ui`, `message_queue`,
  `message_sender`, `topic_emoji`, `transcript_discovery`,
  `recovery_callbacks`, `claude_task_state`, `session_monitor`,
  `polling_strategies`, `cleanup`.

### `test_module_line_count_under_ceiling`

- **Scenario**: `wc -l` on `polling_coordinator.py`.
- **Expected**: ≤ 120 lines. This is a canary — the whole point of the
  refactor is that the file stays small. If it grows past the ceiling,
  someone has smuggled per-window logic back in.

## Boundary Tests

### `test_backoff_on_telegram_error`

- **Scenario**: Stub `tmux_manager.list_windows` to raise
  `TelegramError` twice, then succeed.
- **Expected**: Backoff delay doubles between attempts up to
  `_BACKOFF_MAX`; error_streak resets after the successful iteration.

### `test_backoff_bounded_by_max`

- **Scenario**: Raise errors in a tight loop.
- **Expected**: Delay is capped at `_BACKOFF_MAX = 30s`.

### `test_per_binding_error_does_not_abort_loop`

- **Scenario**: `tick_window` raises `TelegramError` on the second of
  three bindings.
- **Expected**: First and third are still ticked; error is logged via
  `log_throttled`; loop continues.

### `test_per_binding_unknown_error_does_abort_inner_loop`

- **Scenario**: `tick_window` raises a `ValueError`.
- **Expected**: The inner `for` loop bails out to the outer `except`
  which triggers backoff. (Design decision — matches current behavior.)

## Behavior Tests

### `behavior_three_users_concurrent_progress`

- **Scenario**: Three thread bindings, each with a different window
  state. Run one loop iteration.
- **Expected**: All three bindings make progress — one status update
  enqueued, one interactive prompt surfaced, one idle transition —
  independent of each other.

### `behavior_loop_continues_after_tmux_outage`

- **Scenario**: `list_windows` fails for 2 iterations, then recovers.
- **Expected**: After recovery, normal iteration resumes without
  manual intervention.
