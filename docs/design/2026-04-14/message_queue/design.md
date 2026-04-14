# `handlers/message_queue` — Queue Primitives + Dispatcher

## Functional Responsibilities

- Owns per-user `asyncio.Queue[MessageTask]` instances and worker tasks.
- Implements FIFO ordering across task kinds for a single user.
- Implements the **merge-at-dequeue** policy for consecutive mergeable
  content tasks (MERGE_MAX_LENGTH = 3800 chars).
- Dispatches each task variant to the owning module (`tool_batch` for
  batchable content, `status_bubble` for status tasks).
- Drains the queue on topic close (via `topic_state_registry`).
- Owns the `_tool_msg_ids` map that lets tool_result edits find the
  original tool_use Telegram message id.

## Encapsulated Knowledge

- **Queue ordering rules**: the invariant that a `StatusUpdateTask` never
  overtakes a `ContentTask`, and that `ContentTask`s preserve receive
  order.
- **Merge eligibility**: which pairs of `ContentTask`s can be combined
  into one Telegram message (same window, same user, merged length under
  the 3800 char ceiling, same `content_type`).
- **Per-user rate isolation**: one worker per user — no cross-user
  interference.
- **Dispatcher wiring**: which task kind goes to which processor.
- **The tool_use ↔ tool_result message id pairing** (via `_tool_msg_ids`)
  — the queue is the one place that knows how a tool_result edits the
  message a prior tool_use created. This stays here because both sides of
  the pairing are `ContentTask`s that the queue is already processing.

## Subdomain Classification

**Core** — message routing and delivery ordering is the most volatile part
of the bot. Every feature that touches Telegram output reopens this
module. The design must absorb that volatility without cascading.

## Integration Contracts

| Integration            | Direction               | Strength   | What is shared                                                                                                                                                           |
| ---------------------- | ----------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `message_task`         | `message_queue` → reads | Contract   | Task dataclasses (`ContentTask`, `StatusUpdateTask`, `StatusClearTask`, `MessageTask`)                                                                                   |
| `tool_batch`           | `message_queue` → calls | Functional | `is_batch_eligible(task)`, `process_tool_event(task) -> ContentTask \| None`, `flush_if_active(window_id, thread_id)`, `clear_all_batches_for_topic(user_id, thread_id)` |
| `status_bubble`        | `message_queue` → calls | Functional | `process_status_update(task) -> ContentTask \| None`, `process_status_clear(task)`                                                                                       |
| `message_sender`       | `message_queue` → calls | Functional | `rate_limit_send_message`, `send_kwargs`, `edit_with_fallback` — shared send primitives                                                                                  |
| `topic_state_registry` | `message_queue` → calls | Functional | `topic_state.register_bound(self._drain_on_topic_close)` for cleanup                                                                                                     |
| `thread_router`        | `message_queue` → calls | Functional | `resolve_chat_id(user_id, thread_id)`                                                                                                                                    |

**Critical rule: none of the modules above call back into `message_queue`
from module scope.** `tool_batch` and `status_bubble` return `ContentTask`
values when they need the queue to re-process something. This eliminates
the bidirectional cycles that existed in the pre-refactor design.

### Dispatcher contract

```python
async def _process(bot: Bot, user_id: int, task: MessageTask) -> None:
    match task:
        case ContentTask() as ct:
            if tool_batch.is_batch_eligible(ct):
                followup = await tool_batch.process_tool_event(bot, user_id, ct)
                if followup is not None:
                    await _process_content_task(bot, user_id, followup)
            else:
                await tool_batch.flush_if_active(bot, user_id, ct)
                await _process_content_task(bot, user_id, ct)
        case StatusUpdateTask() as st:
            followup = await status_bubble.process_status_update(bot, user_id, st)
            if followup is not None:
                await _process_content_task(bot, user_id, followup)
        case StatusClearTask() as cl:
            await status_bubble.process_status_clear(bot, user_id, cl)
```

`_process_content_task` is the **private** content delivery primitive —
it is the only function in the cluster that calls `rate_limit_send_message`
with a `ContentTask`. Everything else feeds data into it.

## Change Vectors

Changes this module is designed to support with minimal ripple:

1. **New merge rules** (e.g., allow merging across `content_type`
   boundaries in some cases) — the `_can_merge_tasks` function is the
   only site to change.
2. **New dispatch branch** for a new `MessageTask` variant — one new
   `case` clause; the existing branches are unaffected.
3. **Per-user worker lifecycle changes** (graceful shutdown, cancellation
   propagation) — isolated to worker management code.
4. **Rate limit tuning** — lives in `message_sender` already; no change
   required here.

Changes this module is **not** designed for (and for which ripple is
accepted):

- Changing the shape of `ContentTask` (renames ripple to `message_task.py`
  and downstream `match` statements).
- Fundamentally changing how tool_use/tool_result pairing works — this
  would reopen both `message_queue` and `tool_batch`.
