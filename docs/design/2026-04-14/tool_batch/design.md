# `handlers/tool_batch` — Claude Tool-Use Batching

## Functional Responsibilities

- Accumulates consecutive `tool_use` / `tool_result` events from a single
  Claude window into a single Telegram message, edited in place as
  results arrive.
- Implements the batch state machine: open → append → overflow → flush.
- Decides batch eligibility (a `ContentTask` is batchable if its
  `content_type` is `"tool_use"` or `"tool_result"`, its `window_id` maps
  to a Claude provider, and the user has batch mode enabled).
- Formats the combined batch message (task create / update / list
  sections, error/success glyph prefixes, result previews).
- Flushes the active batch on topic cleanup or on a mismatch (unknown
  `tool_use_id`, incompatible content type).
- Registers per-topic cleanup via `topic_state_registry.register_bound()`.

## Encapsulated Knowledge

- **Claude-specific tool names** that get special batch formatting
  (`TaskCreate`, `TaskUpdate`, `TaskList`).
- **Batch size/entry limits** (`BATCH_MAX_LENGTH = 2800`,
  `BATCH_MAX_ENTRIES = 10`).
- **The `_active_batches` dict**: `(user_id, thread_id_or_0) → ToolBatch`.
- **The internal `ToolBatch` / `ToolBatchEntry` dataclasses** — they never
  leave this module. They are implementation detail.
- **Result-to-entry matching** by `tool_use_id`.
- **The edit-in-place Telegram message id** for the active batch.

## Subdomain Classification

**Core** — batch presentation is part of the core "how ccgram renders
Claude output" subdomain, heavily volatile (formatting tweaks, new Claude
tool types, display preferences).

## Integration Contracts

**The fundamental rule**: `tool_batch` **returns data, never calls back**.
When the batch rejects a task (ineligible, overflow, mismatched result),
it returns the `ContentTask` that the queue worker should process normally.
The queue worker is the only module that owns the "deliver a content task
to Telegram" primitive.

| Integration            | Direction            | Strength   | What is shared                                                                                                                                    |
| ---------------------- | -------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `message_task`         | `tool_batch` → reads | Contract   | `ContentTask` dataclass (only)                                                                                                                    |
| `message_sender`       | `tool_batch` → calls | Functional | `edit_with_fallback`, `rate_limit_send_message`, `send_kwargs` — shared send primitives (the same ones `message_queue` uses; this is intentional) |
| `thread_router`        | `tool_batch` → calls | Functional | `resolve_chat_id(user_id, thread_id)`                                                                                                             |
| `topic_state_registry` | `tool_batch` → calls | Functional | `topic_state.register_bound(self._clear_for_topic)` for cleanup                                                                                   |
| `session_manager`      | `tool_batch` → reads | Model      | Used to read `provider_name` / `batch_mode` — should move to `WindowView` as part of Issue C                                                      |

### Public API

```python
def is_batch_eligible(task: ContentTask) -> bool:
    """Returns True if this task should go through the batching path."""

async def process_tool_event(
    bot: Bot, user_id: int, task: ContentTask
) -> ContentTask | None:
    """Add a tool_use or tool_result to the active batch.

    Returns:
        None  if the task was absorbed into the batch (no further action).
        ContentTask  if the caller must process the returned task as
                     normal content (e.g., the batch was flushed because
                     of overflow, or the task was ineligible after all).
    """

async def flush_if_active(
    bot: Bot, user_id: int, task: ContentTask
) -> None:
    """Flush the active batch for this user/topic before sending a
    non-batchable content task. No-op if no batch is active."""

def clear_all_batches_for_topic(user_id: int, thread_id: int) -> None:
    """Synchronous cleanup hook registered with topic_state."""
```

**What is deliberately absent**: no function takes or returns a
`MessageTask` union — only `ContentTask`. `tool_batch` is agnostic about
status tasks; `message_queue` never passes it one.

### Why `tool_batch` depends on `message_sender` directly

`tool_batch` owns the "edit the active batch message in place" path. That
is a Telegram send, and using `message_sender` primitives is the right
level: it is a shared kernel, not a back-edge into `message_queue`. The
same primitives are used by `message_queue`, `status_bubble`, and many
other handlers. `message_sender` itself does not import any of them.

## Change Vectors

1. **New Claude tool name** that deserves dedicated formatting (e.g., a
   future `TaskReassign`) — add to `_TASK_TOOL_NAMES` and the format
   helpers. Isolated.
2. **New batch limit / overflow policy** — change the two constants and
   the overflow branch in `_add_tool_use_entry`. Isolated.
3. **Different render for tool_result previews** — isolated to the
   format helpers.
4. **Disabling batching per-window dynamically** — extend
   `is_batch_eligible`. Isolated.

Changes that still ripple:

- Adding a batching concept for Codex/Gemini — these providers do not
  emit `tool_use`/`tool_result` pairs today. The module is genuinely
  Claude-shaped, and forcing a neutral abstraction now would be
  speculative generality. Revisit if a second provider starts emitting
  paired events.
