# Message Delivery — Test Specification

## Unit Tests

### Tool Batch (`handlers/tool_batch.py`)

| Name                                         | Scenario                                          | Expected                                           |
| -------------------------------------------- | ------------------------------------------------- | -------------------------------------------------- |
| `test_format_batch_single_tool_call`         | Batch with one `ToolBatchEntry` (Read src/foo.py) | `"⚡ 1 tool call\n📖 Read  src/foo.py  ..."`       |
| `test_format_batch_three_mixed_tools`        | Read + Edit + Bash entries                        | `"⚡ 3 tool calls\n..."` with three lines in order |
| `test_format_task_create_run`                | Two `TaskCreate` entries + one `TaskUpdate`       | Task list section with bullets, no generic header  |
| `test_format_batch_with_subagent_label`      | Any batch + non-None subagent_label "write-tests" | Header contains `[🤖 write-tests]`                 |
| `test_format_batch_with_task_tool_subagent`  | TaskCreate + subagent_label                       | Label on second line, not in header                |
| `test_task_create_title_extraction_markdown` | Entry summary `"**TaskCreate** `Fix bug`"`        | Returns `"Fix bug"`                                |
| `test_task_create_title_extraction_plain`    | Entry summary `"TaskCreate: Fix bug"`             | Returns `"Fix bug"`                                |
| `test_batch_result_prefix_ok`                | Result text not containing "error"                | Returns `"⎿"`                                      |
| `test_batch_result_prefix_error`             | Result text containing "Error: ..."               | Returns `"⏳"` or error prefix                     |
| `test_is_batch_eligible_tool_use`            | Task with `content_type="tool_use"`               | `True`                                             |
| `test_is_batch_eligible_text`                | Task with `content_type="text"`                   | `False`                                            |
| `test_should_batch_window_disabled`          | Window batch_mode = "verbose"                     | `False`                                            |
| `test_should_batch_window_enabled`           | Window batch_mode = "batched"                     | `True`                                             |

### Message Queue Primitives (`handlers/message_queue.py`)

| Name                                  | Scenario                                  | Expected                               |
| ------------------------------------- | ----------------------------------------- | -------------------------------------- |
| `test_enqueue_creates_worker`         | First enqueue for user_id=123             | Worker task started, queue exists      |
| `test_enqueue_reuses_worker`          | Second enqueue for same user              | No new worker                          |
| `test_merge_consecutive_text_tasks`   | Enqueue 3 text tasks in a row             | Worker processes 1 merged task         |
| `test_merge_stops_on_tool_use`        | Text, text, tool_use                      | Worker processes 1 merged + 1 tool_use |
| `test_merge_stops_at_3800_chars`      | Two large text tasks totalling 4000 chars | Worker processes 2 separate sends      |
| `test_status_update_coalesces`        | 3 status updates before worker dequeues   | Only last survives                     |
| `test_shutdown_workers_cancels_tasks` | Start 3 workers, call shutdown            | All tasks cancelled, no pending        |

### Status Bubble (`handlers/status_bubble.py`)

| Name                                        | Scenario                                      | Expected                                                             |
| ------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------- |
| `test_build_status_keyboard_idle`           | State = idle, no subagents                    | Keyboard has "🔔 Notify", "🔄 Refresh", "📷", "Recall", "🎛 Toolbar" |
| `test_build_status_keyboard_active`         | State = active                                | Keyboard has "⏹ Stop" and "📷" only                                  |
| `test_build_status_keyboard_with_subagents` | Two subagents active                          | Keyboard shows subagent count in header                              |
| `test_format_claude_task_status_no_tasks`   | Window has no active claude task              | Returns base text unchanged                                          |
| `test_format_claude_task_status_with_wait`  | Window has claude wait header "Waiting 5s..." | Wait header prepended                                                |

### Message Routing (`handlers/message_routing.py`)

| Name                                             | Scenario                                                   | Expected                                           |
| ------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------- |
| `test_handle_new_message_muted_window`           | WindowView.notification_mode = "muted", plain text message | Message dropped (no enqueue)                       |
| `test_handle_new_message_errors_only_with_error` | Mode = "errors_only", message contains error marker        | Enqueued                                           |
| `test_handle_new_message_errors_only_with_ok`    | Mode = "errors_only", non-error text                       | Dropped                                            |
| `test_handle_new_message_thinking_block_gate`    | Thinking block with small character count                  | Dropped (below threshold)                          |
| `test_handle_new_message_unbound_window`         | No thread binding for the window                           | Dropped with debug log                             |
| `test_handle_new_message_interactive_tool`       | Tool that triggers interactive UI                          | Routed to `interactive_ui.show_*` instead of queue |

## Integration Contract Tests

| Name                                               | Scenario                                         | Expected                                                                                |
| -------------------------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| `test_tool_batch_clears_status_before_send`        | Queue has active status bubble; tool_use arrives | `_flush_batch` calls `status_bubble.clear_status_text` before sending the batch message |
| `test_queue_worker_dispatches_to_tool_batch`       | Enqueue eligible task                            | `tool_batch.process_tool_event` called, not `_process_content_task`                     |
| `test_queue_worker_dispatches_to_content_for_text` | Enqueue text task                                | `_process_content_task` called, `tool_batch.process_tool_event` NOT called              |
| `test_status_bubble_edit_in_place`                 | Pinned status exists; new status update arrives  | `edit_message_text` called with the same message_id                                     |
| `test_message_routing_uses_view_window`            | Handler call                                     | `session_manager.view_window` called once; `get_window_state` not called                |

## Boundary Tests

| Name                                                | Scenario                                           | Expected                                             |
| --------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------- |
| `test_batch_overflow_creates_new_batch`             | 11 entries when `BATCH_MAX_ENTRIES=10`             | First 10 flushed, 11th starts a new batch            |
| `test_batch_length_overflow`                        | Cumulative entry length exceeds `BATCH_MAX_LENGTH` | Flush triggered, overflow entry starts new batch     |
| `test_tool_result_no_matching_tool_use`             | Result arrives for unknown tool_use_id             | Batch flushed, result routed as standalone content   |
| `test_format_batch_empty_entries`                   | `format_batch_message([])`                         | Returns header only or raises — documented behaviour |
| `test_queue_worker_handles_enqueue_during_shutdown` | Enqueue after `shutdown_workers` called            | No crash; task dropped silently                      |
| `test_ghost_window_content_task_at_enqueue`         | Enqueue content for an unbound window              | Dropped early via `_is_ghost_window_task_at_enqueue` |

## Behavior Tests

| Name                                            | Scenario                                                        | Expected                                                                 |
| ----------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `test_scenario_batched_toolcall_round_trip`     | Enqueue 3 tool_use tasks + 3 tool_result tasks, different order | Batch message sent once, edited twice, final state shows all three pairs |
| `test_scenario_status_to_content_conversion`    | Status exists, then content arrives                             | Status message is edited into content message (not duplicated)           |
| `test_scenario_notification_filtering`          | Muted window receives 5 messages including one error            | Only the error reaches Telegram                                          |
| `test_scenario_ordering_preserved_across_merge` | Enqueue: text, text, status, text                               | Worker emits: merged(2 texts), status, text — FIFO preserved per type    |
