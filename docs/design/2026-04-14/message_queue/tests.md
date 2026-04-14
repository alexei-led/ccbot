# `handlers/message_queue` — Test Specification

Tests for queue primitives, merge policy, and dispatcher wiring. Uses
`AsyncMock` for `tool_batch` and `status_bubble` so the queue's own
routing logic is exercised in isolation.

## Unit Tests

### `test_get_or_create_queue_returns_same_instance_per_user`

- **Scenario**: Call `get_or_create_queue(bot, 42)` twice.
- **Expected**: Same queue object returned both times; only one worker
  task registered.

### `test_per_user_queues_are_independent`

- **Scenario**: Enqueue a blocking content task for user A, then a
  content task for user B.
- **Expected**: User B's task processes immediately; user A's worker
  is blocked but does not block user B.

### `test_merge_consecutive_text_content_tasks`

- **Scenario**: Enqueue three `ContentTask`s with `content_type="text"`,
  same `window_id`, combined length under 3800 chars.
- **Expected**: Worker dequeues them as one merged task; final
  `parts` is the concatenation.

### `test_merge_stops_at_max_length`

- **Scenario**: Enqueue content tasks whose combined length exceeds
  `MERGE_MAX_LENGTH = 3800`.
- **Expected**: First N that fit under the ceiling are merged; the
  remainder stay in the queue.

### `test_merge_breaks_on_tool_use`

- **Scenario**: Text task → tool_use task → text task, same window.
- **Expected**: Each task processed separately; the tool_use breaks the
  merge chain.

### `test_merge_breaks_on_different_window`

- **Scenario**: Two text tasks for different `window_id` values.
- **Expected**: Each processed separately.

### `test_tool_msg_ids_records_tool_use_message_id`

- **Scenario**: Process a `ContentTask` with `content_type="tool_use"`
  and a `tool_use_id`; stub send to return message id 123.
- **Expected**: `_tool_msg_ids[(tool_use_id, user_id, thread_id)] == 123`.

### `test_tool_msg_ids_cleared_on_topic_close`

- **Scenario**: Register tool_use message ids, then trigger topic close
  via `topic_state_registry`.
- **Expected**: All matching `_tool_msg_ids` entries are removed; other
  topics untouched.

## Integration Contract Tests

These tests cover the dispatcher — the critical new logic that replaces
the bidirectional imports.

### `test_dispatch_content_task_batchable`

- **Scenario**: Enqueue a `ContentTask` with `content_type="tool_use"`.
  Stub `tool_batch.is_batch_eligible` → `True`,
  `tool_batch.process_tool_event` → `None` (absorbed).
- **Expected**: `process_tool_event` called with the task. Content
  delivery primitive (`_process_content_task`) **not** called.

### `test_dispatch_content_task_batch_returns_followup`

- **Scenario**: Same as above, but `tool_batch.process_tool_event`
  returns a new `ContentTask` (simulating overflow).
- **Expected**: `_process_content_task` called with the _returned_
  task, not the original.

### `test_dispatch_content_task_not_batchable`

- **Scenario**: Enqueue a `ContentTask` with `content_type="text"`.
  Stub `tool_batch.is_batch_eligible` → `False`.
- **Expected**: `tool_batch.flush_if_active` called first, then
  `_process_content_task`.

### `test_dispatch_status_update_absorbed`

- **Scenario**: Enqueue a `StatusUpdateTask`. Stub
  `status_bubble.process_status_update` → `None`.
- **Expected**: `process_status_update` called; no content delivery
  happens.

### `test_dispatch_status_update_promotes_to_content`

- **Scenario**: Enqueue a `StatusUpdateTask`. Stub
  `status_bubble.process_status_update` → a `ContentTask` (promotion).
- **Expected**: `_process_content_task` called with the returned task.

### `test_dispatch_status_clear`

- **Scenario**: Enqueue a `StatusClearTask`.
- **Expected**: `status_bubble.process_status_clear` called; nothing
  else.

### `test_no_back_edge_imports`

- **Scenario**: Static import test. Walk the ASTs of
  `handlers/tool_batch.py` and `handlers/status_bubble.py`.
- **Expected**: Neither file contains `from .message_queue import` at
  any scope (module, function, TYPE_CHECKING).
- **Rationale**: This is the test that protects the whole Issue A fix.
  If someone adds a back-edge in a hurry, CI fails.

## Boundary Tests

### `test_worker_survives_dispatch_exception`

- **Scenario**: Enqueue three tasks. Stub the second to raise
  `TelegramError`.
- **Expected**: First and third tasks process normally; worker logs the
  error and continues.

### `test_dispatch_rejects_unknown_variant`

- **Scenario**: Enqueue an object that is not a `ContentTask`,
  `StatusUpdateTask`, or `StatusClearTask`.
- **Expected**: At type-check time, pyright rejects. At runtime, the
  `match` statement's default case logs a warning and drops the task
  (does not crash the worker).

### `test_draining_clears_queue_and_tool_msg_ids`

- **Scenario**: Register a topic, enqueue tasks, close the topic.
- **Expected**: Queue drained; per-topic `_tool_msg_ids` entries
  removed.

## Behavior Tests

### `behavior_text_messages_merge_end_to_end`

- **Scenario**: User receives three short text messages from a Claude
  session in rapid succession.
- **Expected**: Exactly one Telegram `send_message` call is made;
  combined text is all three messages joined.

### `behavior_tool_use_and_result_pair_edits_in_place`

- **Scenario**: Claude emits `tool_use` followed by `tool_result` for
  the same `tool_use_id`.
- **Expected**: `tool_use` sends a new Telegram message; `tool_result`
  edits that message. No second `send_message` call.

### `behavior_status_update_then_content_promotes_bubble`

- **Scenario**: Status bubble is active ("thinking…"), then a content
  task arrives for the same topic.
- **Expected**: Bubble is promoted to content in place (edited with
  content text), new content message sent only if `status_bubble`
  returns a followup.
