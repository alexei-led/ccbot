# `handlers/status_bubble` — Test Specification

## Unit Tests

### `test_send_status_text_creates_bubble_on_first_call`

- **Scenario**: No existing `_status_msg_info` entry. Call
  `send_status_text(user_id, window_id, "thinking", thread_id=5)`.
- **Expected**: Telegram `send_message` called once; entry recorded in
  `_status_msg_info`.

### `test_send_status_text_edits_existing_bubble`

- **Scenario**: `_status_msg_info` has an entry. Call with different
  text.
- **Expected**: Telegram `edit_message_text` called; no new send.

### `test_send_status_text_dedup_skips_identical`

- **Scenario**: `_status_msg_info` has entry with text `"idle"`. Call
  with `"idle"` again.
- **Expected**: Zero Telegram API calls.

### `test_build_status_keyboard_layout`

- **Scenario**: Call with a state of `"active"` and `window_id="@0"`.
- **Expected**: Returns a keyboard with the configured action buttons
  for the active state; callback_data prefixed with the expected
  dispatcher prefix.

### `test_format_claude_task_status_with_snapshot`

- **Scenario**: `claude_task_state.get_task_snapshot` returns two
  tasks. Call `format_claude_task_status(window_id, "running")`.
- **Expected**: Returns a string with the task header prepended.

### `test_format_claude_task_status_without_snapshot`

- **Scenario**: No snapshot available.
- **Expected**: Returns the base text unchanged.

### `test_clear_status_msg_info_single_topic`

- **Scenario**: Entries for (user=1, thread=5) and (user=1, thread=7).
  Call `clear_status_msg_info(user_id=1, thread_id=5)`.
- **Expected**: Only the thread=5 entry removed.

### `test_clear_status_msg_info_all_user`

- **Scenario**: Call with `thread_id=None`.
- **Expected**: All entries for user=1 removed.

## Integration Contract Tests

### `test_no_import_from_message_queue`

- **Scenario**: AST walk of `handlers/status_bubble.py`.
- **Expected**: Zero imports from `.message_queue`.

### `test_process_status_update_returns_content_task_or_none`

- **Scenario**: Type-check `process_status_update` signature.
- **Expected**: Parameter is `StatusUpdateTask`; return is
  `ContentTask | None`.

### `test_process_status_update_returns_none_when_absorbed`

- **Scenario**: Stub send and edit primitives. Call
  `process_status_update` with a status update that fits the normal
  path.
- **Expected**: Returns `None`; bubble updated in place.

### `test_process_status_update_returns_content_on_promotion`

- **Scenario**: Active bubble; trigger the "another message arrived"
  promotion path (specific mechanism TBD in implementation — may be
  based on whether last message is content or status).
- **Expected**: Returns a `ContentTask` carrying the bubble's text;
  `_status_msg_info` entry removed (bubble is no longer a bubble).

### `test_process_status_clear`

- **Scenario**: Active bubble. Call `process_status_clear`.
- **Expected**: Telegram `edit_message_text` called with a blank or
  placeholder text; `_status_msg_info` entry removed.

### `test_cleanup_hook_registered`

- **Scenario**: Inspect `topic_state._callbacks`.
- **Expected**: `clear_status_msg_info` registered via `register_bound`.

## Boundary Tests

### `test_send_status_text_handles_telegram_error`

- **Scenario**: Stub `send_message` to raise `BadRequest("message to
edit not found")`.
- **Expected**: The old `_status_msg_info` entry is cleared and a new
  bubble is sent. Matches current recovery behavior.

### `test_dedup_respects_window_id_change`

- **Scenario**: `_status_msg_info` has entry with text `"idle"` for
  window `@0`. Call with `"idle"` for window `@5`.
- **Expected**: Treated as a different bubble (dedup does not apply).

### `test_promotion_no_bubble_active`

- **Scenario**: Call `convert_status_to_content` when no bubble is
  active for the topic.
- **Expected**: Returns `None`; no error.

## Behavior Tests

### `behavior_status_dedup_reduces_api_calls`

- **Scenario**: 10 identical status updates in rapid succession.
- **Expected**: 1 send + 0 edits (all deduped).

### `behavior_status_then_content_produces_one_message`

- **Scenario**: Status bubble is "thinking", then a content task
  arrives.
- **Expected**: The bubble is converted to content in place; user sees
  one message with the content text, not a bubble followed by content.

### `behavior_status_keyboard_action_callbacks_resolve`

- **Scenario**: Build the keyboard, invoke each callback handler by
  its prefix.
- **Expected**: Each callback is routed to `status_bar_actions`
  handlers correctly.
