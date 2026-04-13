# Message Delivery

## Functional Responsibilities

End-to-end delivery of assistant output (text, thinking, tool calls, tool results, status updates) from the session monitor to the user's Telegram topic. The module is the pipeline spine — every message that reaches a user passes through it.

Internally split into four files that map to four distinct concerns:

- **`message_queue.py` (queue primitives, ~500 lines)** — per-user FIFO `asyncio.Queue`, worker task, drain-and-merge, rate limiting via `rate_limit_send()`, worker shutdown. Owns nothing provider-specific.
- **`tool_batch.py` (NEW, ~350 lines)** — Claude tool-use batching: `ToolBatchEntry`, `ToolBatch`, `_active_batches`, `process_tool_event()`, `flush_batch()`, `format_batch_message()` + the 9 formatting helpers (`_format_task_create_batch`, `_format_mixed_batch_lines`, `_format_task_create_section`, `_format_task_update_section`, `_format_task_list_section`, `_batch_result_prefix`, `_format_batch_entry`, `_extract_task_create_title`, `_extract_task_tool_suffix`). Owns everything that knows Claude's `tool_use`/`tool_result`/`TaskCreate`/`TaskUpdate`/`TaskList` semantics.
- **`status_bubble.py` (expanded from 81 → ~300 lines)** — status bubble send/edit/clear lifecycle: `send_status_text()`, `clear_status_text()`, `edit_status_in_place()`, `build_status_keyboard()`, `format_claude_task_status()`. Owns the pinned message that tracks idle/active/done state.
- **`message_routing.py` (~130 lines, existing)** — first-hop dispatcher from `NewMessage` events to queue enqueue, with notification-mode filtering, thinking-block gating, interactive-tool detection, offset tracking.

A fifth file, **`message_sender.py`** (rate-limit primitives, `safe_reply`/`safe_edit`/`safe_send`), is infrastructure used by all four above and by other modules. It stays where it is.

## Encapsulated Knowledge

- **Queue ordering guarantees.** Messages for a user are delivered FIFO; merges happen at dequeue time, not enqueue time. Tool_use and tool_result break merge chains.
- **Claude tool-event vocabulary.** Only `tool_batch.py` knows that `TaskCreate` is a sub-task spawn and renders it as a task list header. No other module in the system references these tool names.
- **Status bubble message lifecycle.** Only `status_bubble.py` knows when a status message exists, how to convert it to a content message, how to edit it in place, and how to clear it. The Telegram `message_id` of the pinned bubble is private to this module.
- **Rate-limit timing.** Only `message_sender.py` knows the 0.5s minimum interval per user and holds the per-user `_last_send_time` and `_rate_limit_locks`.
- **Notification-mode gating predicates.** Only `message_routing.py` decides whether to drop or pass a message based on the window's `notification_mode` and the message classification (pure-text assistant, tool event, error).

## Subdomain Classification

**Core.** Message delivery quality is the product's primary differentiator. Users choose ccgram over polling `tmux capture-pane` because the Telegram experience is legible. Every new agent-CLI behaviour (mode change, new tool event, subagent spawn) touches one of the four files. High volatility.

## Integration Contracts

### Inbound

| From                                                               | Kind     | Contract                                                                                        |
| ------------------------------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------- |
| `session_monitor` → `message_routing.handle_new_message(msg, bot)` | Contract | `NewMessage` event (dataclass) with `session_id`, `entries`, `is_tool_use`, `is_thinking`, etc. |
| `hook_events` → `status_bubble.enqueue_status_update(...)`         | Contract | Text, window_id, optional tick timestamp                                                        |
| `polling_coordinator` → `status_bubble.enqueue_status_update(...)` | Contract | Same                                                                                            |
| `shell_capture` → `message_queue.enqueue_content_message(...)`     | Contract | Parts list, window_id, content_type="text"                                                      |

### Outbound

| To                                                              | Kind     | Contract                                                  |
| --------------------------------------------------------------- | -------- | --------------------------------------------------------- |
| `message_queue` → `message_sender.rate_limit_send_message(...)` | Contract | Chat id, text, reply markup, thread id kwargs             |
| `status_bubble` → `telegram bot API` (via `message_sender`)     | Contract | Same                                                      |
| `tool_batch` → `telegram bot API` (via `message_sender`)        | Contract | Same                                                      |
| `tool_batch` → `status_bubble.clear_status_text(...)`           | Contract | user_id, thread_id — coordinate edit-in-place exclusivity |
| `tool_batch` → `claude_task_state.build_subagent_label()`       | Contract | window_id → optional label string                         |
| `message_routing` → `interactive_ui.is_interactive_tool(...)`   | Contract | Tool name classification                                  |
| `message_routing` → `session_manager.view_window(window_id)`    | Contract | Read-only `WindowView` for notification mode and cwd      |

### Data types crossing boundaries

```python
# message_queue.py
@dataclass
class MessageTask:
    """Discriminated by task_type — see below for type split recommendation."""
    task_type: Literal["content", "status_update", "status_clear"]
    # ... union fields

# Recommended split (optional follow-up):
@dataclass
class ContentTask:
    text: str
    parts: list[str]
    tool_use_id: str | None
    tool_name: str | None
    content_type: Literal["text", "tool_use", "tool_result", "thinking"]
    window_id: str
    thread_id: int

@dataclass
class StatusUpdateTask:
    text: str
    window_id: str
    thread_id: int | None

@dataclass
class StatusClearTask:
    window_id: str
    thread_id: int | None

Task = ContentTask | StatusUpdateTask | StatusClearTask  # Python 3.12+ PEP 695
```

## Change Vectors

Reasonable future changes that should touch ONE of the four files, not all four:

- **Adding a new Claude tool format** — touches `tool_batch.py` only (new helper in `_format_mixed_batch_lines`).
- **Changing the idle→active transition policy** — touches `status_bubble.py` only.
- **Tightening rate-limit timing** — touches `message_sender.py` only.
- **New notification mode (e.g., "errors and subagent spawns only")** — touches `message_routing.py` only.
- **Adding a second provider's batching (if it ever happens)** — creates a sibling file (e.g., `codex_tool_batch.py`) and a routing switch in `message_routing`. No change to queue primitives or status bubble.

Changes that **should** ripple across multiple files:

- **Redefining the `MessageTask` type union** — the whole pipeline has to adapt because the worker dispatches on it. This is the type system doing its job.

## Refactor Plan (from today's state)

1. Create `handlers/tool_batch.py`. Move: `BATCH_MAX_ENTRIES`, `BATCH_MAX_LENGTH`, `_TASK_TOOL_NAMES`, `ToolBatchEntry`, `ToolBatch`, `_active_batches`, `_is_batch_eligible`, `_should_batch`, `_process_batch_task`, `_flush_batch`, `_handle_content_task` (batch branch), `format_batch_message` + all 9 `_format_*` helpers. Public API: `async def process_tool_event(bot, user_id, task) -> None`, `async def flush_batch(bot, user_id, thread_id) -> None`, `def is_batch_eligible(task, window_id) -> bool`.
2. Expand `handlers/status_bubble.py`. Move from `message_queue.py`: `_process_status_update_task`, `_process_status_clear_task`, `_do_send_status_message`, `_do_clear_status_message`, `_convert_status_to_content`, `_format_claude_task_status`, `_status_msg_info`. Keep `build_status_keyboard` (already here). Public API: `async def send_status_text(...)`, `async def clear_status_text(...)`, `async def edit_status_in_place(...)`, `def clear_status_msg_info(user_id, thread_id)`.
3. Slim `handlers/message_queue.py` to the queue primitives: `MessageTask` (or the split types), `_message_queue_worker`, `_handle_content_task` (routing branch only), `_process_content_task`, `_merge_content_tasks`, `_coalesce_status_updates`, `_can_merge_tasks`, `enqueue_content_message`, `enqueue_status_update`, `get_or_create_queue`, `shutdown_workers`. Expected: ~500 lines.
4. (Optional follow-up) Split `MessageTask` into three discriminated types. Run pyright; fix the worker's dispatch to `match task:` on the union.

## Testability Goals

- Unit-test `tool_batch.format_batch_message([...])` without any bot, session, or Telegram fixtures. Pure formatting takes entries in and returns a string.
- Unit-test `status_bubble.build_status_keyboard(state)` without any bot.
- Unit-test `message_routing.handle_new_message` with a mocked `Bot`, a mocked `queue`, and a `WindowView` literal (no `SessionManager` wiring).
- `tool_batch._active_batches` remains a module-level dict but its cleanup is registered once (not scattered), and tests reset it via a `reset_state()` helper.
