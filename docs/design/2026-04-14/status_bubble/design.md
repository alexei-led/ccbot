# `handlers/status_bubble` — Status Message Lifecycle

## Functional Responsibilities

- Owns the "status bubble" — the single edit-in-place message that
  represents the agent's current status in a Telegram topic.
- Sends the bubble on first status update, edits it in place on
  subsequent updates, clears or promotes it when content arrives.
- Formats Claude task-list status headers (reads from `claude_task_state`).
- Builds the status keyboard (action buttons on the bubble).
- Deduplicates consecutive identical updates (skips the edit API call
  when `last_text` is unchanged).
- Converts the status bubble into a regular content message in place
  when the worker needs to send content and the bubble is the most
  recent message (avoids a stale "idle" message above fresh content).
- Registers per-topic cleanup via `topic_state_registry.register_bound()`.

## Encapsulated Knowledge

- **The `_status_msg_info` dict**: `(user_id, thread_id) → (message_id,
text, kind, sent_at)` — the single source of truth for "is there an
  active status bubble for this topic, and what does it say?"
- **The status keyboard layout** (which buttons to show, in what order,
  for which state).
- **The dedup rule** (skip edit when text is identical).
- **The conversion semantics**: a status bubble _promoted_ to content
  stops being tracked as a bubble — from that point it is a regular
  content message.
- **The idle-history lookup** (`_get_idle_history`) for the status recall
  button.
- **Claude task status formatting** (`format_claude_task_status`).

## Subdomain Classification

**Core** — status UX is the main way users perceive agent activity.
Formatting, dedup rules, and conversion logic are tweaked frequently.

## Integration Contracts

**The fundamental rule (same as `tool_batch`)**: `status_bubble` **returns
data, never calls back**. When a status update needs to be promoted to
content (because another message arrived in the meantime), it returns a
`ContentTask` that the queue worker processes.

| Integration            | Direction               | Strength   | What is shared                                                                                                                                                    |
| ---------------------- | ----------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `message_task`         | `status_bubble` → reads | Contract   | `ContentTask`, `StatusUpdateTask`, `StatusClearTask`                                                                                                              |
| `message_sender`       | `status_bubble` → calls | Functional | `edit_with_fallback`, `rate_limit_send_message`, `send_kwargs` — same shared primitives                                                                           |
| `thread_router`        | `status_bubble` → calls | Functional | `resolve_chat_id`, `get_display_name`                                                                                                                             |
| `claude_task_state`    | `status_bubble` → reads | Model      | `get_task_snapshot(window_id)` — used to format task-list headers. Provider-specific coupling; acceptable because task-list presentation _is_ Claude-shaped today |
| `topic_state_registry` | `status_bubble` → calls | Functional | `topic_state.register_bound(self._clear_for_topic)`                                                                                                               |

### Public API

```python
def build_status_keyboard(
    window_id: str, state: str, ...
) -> InlineKeyboardMarkup:
    """Build the action keyboard shown on the status bubble."""

async def send_status_text(
    bot: Bot, user_id: int, window_id: str, text: str,
    thread_id: int | None = None, *, kind: str = "status",
) -> None:
    """Send or edit the status bubble with new text."""

async def process_status_update(
    bot: Bot, user_id: int, task: StatusUpdateTask
) -> ContentTask | None:
    """Update the status bubble.

    Returns:
        None  if the update was handled (edit or send).
        ContentTask  if the status needed to be promoted to a regular
                     content message — the queue worker should process
                     the returned task.
    """

async def process_status_clear(
    bot: Bot, user_id: int, task: StatusClearTask
) -> None:
    """Clear the status bubble for this topic (delete or blank)."""

async def convert_status_to_content(
    bot: Bot, user_id: int, window_id: str, thread_id: int,
) -> ContentTask | None:
    """Internal helper: convert the active status bubble into a
    ContentTask carrying the bubble's text. Returns None if no bubble
    is active for this topic."""

def clear_status_msg_info(user_id: int, thread_id: int | None = None) -> None:
    """Synchronous cleanup hook (called from topic_state_registry)."""
```

### Why `status_bubble` does not import `message_queue`

The only reason it needed to in the pre-refactor design was that
`process_status_update_task` wanted to call `process_content_task` when
promoting a status bubble to content. In the new design, it returns a
`ContentTask` and the queue worker calls its own `_process_content_task`.

## Change Vectors

1. **New status kinds / buttons** — extend `build_status_keyboard` and
   the keyboard callback dispatch. Isolated.
2. **New dedup rules** (e.g., dedup by hash instead of equality) — isolated
   to the `_status_msg_info` comparison in `send_status_text`.
3. **New conversion policy** (e.g., promote status on a timer instead of
   on next content) — isolated to `convert_status_to_content` and the
   queue worker's dispatch.
4. **Different task-list rendering** — isolated to
   `format_claude_task_status`.

Changes that still ripple:

- Replacing `claude_task_state` with a generic provider task snapshot —
  this is the same generic-provider concern as `tool_batch`. Acceptable
  for now (low volatility on the second-provider axis).
