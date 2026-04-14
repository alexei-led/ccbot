# `handlers/message_task` — Test Specification

The module is pure data. The tests protect the contract — what shape
the downstream modules will receive — not behavior.

## Unit Tests

### `test_content_task_is_frozen`

- **Scenario**: Instantiate a `ContentTask`, attempt to mutate a field.
- **Expected**: `FrozenInstanceError` (via `@dataclass(frozen=True)`).

### `test_content_task_parts_is_tuple`

- **Scenario**: `ContentTask(window_id="@0", parts=("a", "b"))`.
- **Expected**: `parts` is a `tuple`, not a `list`. Attempting to pass
  a `list` at the type level should be rejected by pyright; at runtime
  it still works (Python doesn't enforce) but the test asserts
  `isinstance(task.parts, tuple)`.

### `test_content_task_type_literal`

- **Scenario**: Construct with each of `"text"`, `"tool_use"`,
  `"tool_result"`.
- **Expected**: Each succeeds. Construction with an arbitrary string
  (e.g., `"media"`) should fail `pyright --strict` — enforced via
  a mypy/pyright test if the project has one, otherwise documented.

### `test_status_update_task_optional_text`

- **Scenario**: `StatusUpdateTask(window_id="@0", text=None)`.
- **Expected**: Constructs successfully. `None` is the "clear"
  semantics that some status updates still use.

### `test_status_clear_task_optional_thread_id`

- **Scenario**: `StatusClearTask(window_id="@0")`.
- **Expected**: `thread_id` defaults to `None`.

## Integration Contract Tests

### `test_match_dispatches_all_three_variants`

- **Scenario**: A `match` statement over `MessageTask` handles each
  variant.
- **Expected**: pyright `--strict` reports exhaustiveness (no
  `reportMatchNotExhaustive`). This test is enforced at CI type-check
  time, not at runtime.

### `test_union_alias_covers_all_concrete_variants`

- **Scenario**: Assert at runtime that `MessageTask.__args__` contains
  exactly `{ContentTask, StatusUpdateTask, StatusClearTask}`.
- **Expected**: Guard against silently dropping a variant from the
  alias.

## Boundary Tests

### `test_content_task_requires_window_id`

- **Scenario**: Attempt `ContentTask(parts=("x",))` without `window_id`.
- **Expected**: `TypeError` at construction — `window_id` is required.

### `test_frozen_dataclass_is_hashable`

- **Scenario**: Use a `ContentTask` as a dict key.
- **Expected**: Works. Guards against accidental `unsafe_hash` or
  mutable field additions.

## Behavior Tests

This module has no behavior. Skip. Any "behavior" lives in the modules
that consume the data.
