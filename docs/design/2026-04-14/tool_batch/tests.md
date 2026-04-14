# `handlers/tool_batch` — Test Specification

Tests the batch state machine in isolation. The critical shape guarantee
is that the module **takes and returns `ContentTask`** and never calls
back into `message_queue`.

## Unit Tests

### `test_is_batch_eligible_tool_use`

- **Scenario**: `ContentTask(content_type="tool_use", window_id=...)`
  for a Claude-provider window with batch mode enabled.
- **Expected**: `True`.

### `test_is_batch_eligible_tool_result`

- **Scenario**: `ContentTask(content_type="tool_result", ...)`.
- **Expected**: `True`.

### `test_is_batch_eligible_text_false`

- **Scenario**: `ContentTask(content_type="text", ...)`.
- **Expected**: `False` — text is not batchable.

### `test_is_batch_eligible_non_claude_false`

- **Scenario**: `ContentTask(content_type="tool_use", ...)` for a
  Codex-provider window.
- **Expected**: `False`. Batching is Claude-only.

### `test_process_tool_use_opens_batch`

- **Scenario**: First `tool_use` task for a new `(user_id, thread_id)`.
- **Expected**: Returns `None` (absorbed); `_active_batches` now
  contains one entry; Telegram `send_message` called once.

### `test_process_tool_result_edits_batch_message`

- **Scenario**: Active batch with one `tool_use` entry. Enqueue a
  `tool_result` for the same `tool_use_id`.
- **Expected**: Returns `None`; the batch entry's `tool_result_text`
  is populated; Telegram `edit_message_text` called (no new send).

### `test_process_tool_use_overflow_returns_followup`

- **Scenario**: Active batch at `BATCH_MAX_ENTRIES`. Enqueue another
  `tool_use`.
- **Expected**: The current batch is flushed (edit-in-place with final
  state); returns the new `ContentTask` so the queue worker delivers
  it as a fresh message.

### `test_process_tool_use_overflow_by_length`

- **Scenario**: Active batch near `BATCH_MAX_LENGTH = 2800`. Enqueue a
  `tool_use` whose text pushes the total over the limit.
- **Expected**: Same as above — flush, return the overflow task.

### `test_tool_result_without_matching_tool_use_returns_followup`

- **Scenario**: Enqueue a `tool_result` whose `tool_use_id` does not
  match any active batch entry.
- **Expected**: Returns the `tool_result` as a `ContentTask` for the
  queue worker to deliver normally.

### `test_flush_if_active_flushes_and_clears`

- **Scenario**: Active batch with 2 entries. Call `flush_if_active`
  with a non-batchable content task.
- **Expected**: Batch message finalized (edit); `_active_batches` no
  longer has the entry.

### `test_flush_if_active_noop_when_empty`

- **Scenario**: No active batch. Call `flush_if_active`.
- **Expected**: No Telegram calls; no errors.

## Integration Contract Tests

### `test_no_import_from_message_queue`

- **Scenario**: AST walk of `handlers/tool_batch.py`.
- **Expected**: Zero imports from `.message_queue` — including local
  function-scope imports and `TYPE_CHECKING`-only imports.
- **Rationale**: Same purpose as the equivalent test in
  `message_queue/tests.md` — belt and suspenders for the Issue A fix.

### `test_public_api_takes_content_task`

- **Scenario**: Type-check `process_tool_event`, `is_batch_eligible`,
  `flush_if_active` signatures.
- **Expected**: Parameters are typed as `ContentTask`, never
  `MessageTask` (the union). Enforced by pyright at CI.

### `test_process_tool_event_returns_content_task_or_none`

- **Scenario**: Type-check the return annotation.
- **Expected**: `ContentTask | None` — never `MessageTask`.

## Boundary Tests

### `test_clear_all_batches_for_topic`

- **Scenario**: Register batches for multiple `(user_id, thread_id)`
  pairs. Call `clear_all_batches_for_topic(user_id_1, thread_id_1)`.
- **Expected**: Only the matching entry is removed; other topics'
  batches untouched.

### `test_batch_survives_formatter_exception`

- **Scenario**: Inject a malformed tool_use text that crashes the
  formatter.
- **Expected**: Error logged; batch state remains consistent; next
  `process_tool_event` still works.

### `test_cleanup_hook_registered_via_topic_state_registry`

- **Scenario**: Import the module, then inspect `topic_state._callbacks`.
- **Expected**: `clear_all_batches_for_topic` is registered as a
  bound callback via `register_bound`.

## Behavior Tests

### `behavior_rapid_tool_use_burst_one_edited_message`

- **Scenario**: Claude emits 5 `tool_use`s within batch limits, then
  5 matching `tool_result`s.
- **Expected**: Exactly one Telegram `send_message` (the first
  tool_use) and N `edit_message_text` calls. Final message shows all
  5 tool calls with their results.

### `behavior_mixed_task_tools_formatted_as_task_section`

- **Scenario**: Batch contains `TaskCreate`, `TaskUpdate`, `TaskList`
  interleaved with other tools.
- **Expected**: Task section grouped together; non-task tools in their
  own section; error/success glyphs applied per-entry.
