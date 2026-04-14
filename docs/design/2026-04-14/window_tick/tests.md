# `handlers/window_tick` — Test Specification

The module has wide fan-out (~12 cooperating modules). Tests stub the
collaborators and assert the _orchestration_ — the right decisions fire
for the right inputs. Deep state-machine behavior tests live alongside
the current polling tests and should be moved here as part of the
refactor.

## Unit Tests

Pure decision logic — each test exercises one branch of the state
machine with all other collaborators stubbed.

### `test_tick_window_dead_window`

- **Scenario**: `window=None` passed to `tick_window`.
- **Expected**: `_handle_dead` called; no other collaborators touched.

### `test_tick_window_with_pending_queue_skips_status_update`

- **Scenario**: `get_message_queue(user_id)` returns a non-empty queue.
- **Expected**: `_check_interactive_only` called; `_update_status`
  **not** called; `_scan_window_panes` and `_maybe_check_passive_shell`
  both called.

### `test_tick_window_empty_queue_runs_status_update`

- **Scenario**: Queue is empty.
- **Expected**: `_update_status` called; then `_scan_window_panes`;
  then `_maybe_check_passive_shell`.

### `test_update_status_interactive_ui_wins`

- **Scenario**: Pane parse returns `status.is_interactive == True`.
- **Expected**: `handle_interactive_ui` called; no emoji update, no
  enqueue status.

### `test_update_status_active_with_status_line`

- **Scenario**: Provider returns a status line, not interactive.
- **Expected**: `claude_task_state.set_last_status` called;
  `terminal_poll_state.mark_seen_status` called; typing throttle
  called; topic emoji updated to `"active"`; status update enqueued.

### `test_update_status_subagent_label_appended`

- **Scenario**: `claude_task_state.get_subagent_names` returns
  `["subagent-1"]`.
- **Expected**: Enqueued status text includes the subagent label in
  parentheses.

### `test_update_status_notification_mode_muted_skips_enqueue`

- **Scenario**: `session_manager.get_notification_mode` returns
  `"muted"`.
- **Expected**: Status line is set on `claude_task_state` but not
  enqueued to Telegram; typing still throttled.

### `test_handle_no_status_active_transcript`

- **Scenario**: No status from provider, but transcript activity
  detected.
- **Expected**: `clear_wait_header` called; typing throttle called;
  topic emoji set to `"active"`; autoclose timer cleared; does **not**
  enqueue anything.

### `test_handle_no_status_shell_idle_claude_provider`

- **Scenario**: No provider status, pane shows a shell prompt, window
  provider is Claude (not shell/codex/gemini).
- **Expected**: `update_topic_emoji` called with `"done"`; autoclose
  timer started for `"done"`; status enqueue with `None`.

### `test_handle_no_status_shell_idle_shell_provider`

- **Scenario**: Same as above but provider is `"shell"`.
- **Expected**: Transitions to idle via `_transition_to_idle`, not
  `"done"` — provider-specific path.

### `test_handle_no_status_startup_timer`

- **Scenario**: No status yet; startup timer not yet started.
- **Expected**: Timer begun; typing throttle; emoji `"active"`;
  autoclose cleared.

### `test_handle_no_status_startup_expired`

- **Scenario**: Startup timer past expiry window.
- **Expected**: Transitions to idle.

### `test_scan_panes_single_pane_cache_fast_path`

- **Scenario**: `terminal_screen_buffer.is_single_pane_cached` returns
  `True`.
- **Expected**: `list_panes` not called; function returns early.

### `test_scan_panes_surfaces_interactive_alert`

- **Scenario**: Two panes; non-active pane has interactive prompt.
- **Expected**: `interactive_strategy.set_pane_alert` called;
  `handle_interactive_ui` called with `pane_id` kwarg.

### `test_scan_panes_clears_stale_alerts`

- **Scenario**: Previous pane alert existed for pane `%5`; current
  panes do not include `%5`.
- **Expected**: `interactive_strategy.prune_stale_pane_alerts` called
  with the live pane id set.

### `test_maybe_check_passive_shell_non_shell_noop`

- **Scenario**: Window provider is Claude.
- **Expected**: Function returns without calling
  `check_passive_shell_output`.

### `test_maybe_check_passive_shell_shell_provider`

- **Scenario**: Window provider is shell; rendered text available.
- **Expected**: `check_passive_shell_output` called with the rendered
  text.

### `test_check_interactive_only_already_interactive`

- **Scenario**: `get_interactive_window(user_id, thread_id) ==
window_id`.
- **Expected**: Returns early; no pane capture.

## Integration Contract Tests

### `test_tick_window_is_sole_public_function`

- **Scenario**: Import the module; inspect public names.
- **Expected**: Only `tick_window` is public. All `_handle_*`,
  `_update_*`, `_scan_*`, `_check_*`, `_maybe_*` helpers are
  underscore-prefixed.

### `test_polling_coordinator_imports_only_tick_window`

- **Scenario**: AST walk of `polling_coordinator.py`.
- **Expected**: It imports `window_tick.tick_window` and **nothing
  else** from `window_tick`.

### `test_polling_coordinator_does_not_import_per_window_collaborators`

- **Scenario**: AST walk of `polling_coordinator.py`.
- **Expected**: No imports of `claude_task_state`, `providers.base`,
  `session_monitor`, `cleanup`, `interactive_ui`, `message_queue`,
  `message_sender`, `recovery_callbacks`, `topic_emoji`,
  `transcript_discovery`, `polling_strategies` (beyond what the outer
  loop still needs — verify against the design doc's list).

## Boundary Tests

### `test_tick_window_swallows_per_window_errors`

- **Scenario**: Stub `_update_status` to raise `TelegramError`.
- **Expected**: Error is logged; `tick_window` returns normally. The
  coordinator can continue with the next binding.
- **Note**: Error handling may live in either `window_tick` or
  `polling_coordinator` — the design doc says the outer loop owns
  error handling, so this test verifies that `window_tick` re-raises
  and the coordinator catches.

### `test_tick_window_handles_tmux_find_window_none`

- **Scenario**: `tmux_manager.find_window_by_id` returns `None` inside
  `_update_status`.
- **Expected**: Falls back to enqueueing a None status and returning.

### `test_tick_window_clears_structlog_contextvars`

- **Scenario**: The outer loop binds `window_id` via contextvars.
- **Expected**: `tick_window` does not leak that binding across
  iterations (the outer loop is responsible; this test verifies the
  contract is respected).

## Behavior Tests

These are the tests that currently live in
`test_status_polling.py` and should migrate here.

### `behavior_dead_window_notification_once`

- **Scenario**: Bound window is killed out-of-band. Run `tick_window`
  twice.
- **Expected**: First call sends the recovery keyboard; second call
  is a no-op (`is_dead_notified` guard).

### `behavior_idle_transition_after_startup_timeout`

- **Scenario**: New Claude window, no status for longer than startup
  timeout.
- **Expected**: Status message transitions from "starting" to idle.

### `behavior_active_to_done_on_shell_prompt_detection`

- **Scenario**: Claude session finishes, pane shows shell prompt.
- **Expected**: Emoji transitions to `"done"`; autoclose timer armed.

### `behavior_interactive_pane_in_multipane_window`

- **Scenario**: Two-pane window; non-active pane shows a permission
  prompt.
- **Expected**: Alert surfaced via `interactive_ui`; pane_id included
  in callback data.
