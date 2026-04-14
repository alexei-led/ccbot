# `handlers/message_task` — Shared Message Contract

## Functional Responsibilities

Defines the **data shape** of every task the message queue processes. It is
pure data: no I/O, no telegram calls, no tmux access, no side effects.
It is the explicit contract that replaces the previous union dataclass
(`MessageTask`) whose discriminator and optional fields were spread across
`message_queue`, `tool_batch`, and `status_bubble`.

## Encapsulated Knowledge

- The **set of task kinds** the messaging cluster supports today:
  content delivery, status update, status clear.
- For each kind, the **exact fields that are legal and required** — no
  optional grab-bag.
- The **sum type** (`MessageTask = ContentTask | StatusUpdateTask |
StatusClearTask`) that downstream modules discriminate via `match`.

## Subdomain Classification

**Supporting** — even though messaging itself is a _core_ subdomain, the
_shape of the task record_ is a stable contract within it. The fields
evolve when a new message kind is introduced (rare), not when routing,
merging, or send logic changes (frequent). That is why the data lives in
its own module: it acts as a firebreak between the volatile implementation
modules and gives them something cheap to share.

## Integration Contracts

| Direction                        | Contract type | What is shared                                                                          |
| -------------------------------- | ------------- | --------------------------------------------------------------------------------------- |
| `message_queue` ← `message_task` | Contract      | Imports `ContentTask`, `StatusUpdateTask`, `StatusClearTask`, `MessageTask` (the Union) |
| `tool_batch` ← `message_task`    | Contract      | Imports `ContentTask` only                                                              |
| `status_bubble` ← `message_task` | Contract      | Imports `ContentTask`, `StatusUpdateTask`, `StatusClearTask`                            |

`message_task` itself imports **nothing from `handlers/`**. It imports
only from `typing`, `dataclasses`, and Python stdlib. This is the single
rule that keeps the cluster acyclic.

### Contract definition

```python
from dataclasses import dataclass, field
from typing import Literal

ContentType = Literal["text", "tool_use", "tool_result"]


@dataclass(frozen=True, slots=True)
class ContentTask:
    """A Telegram message to deliver — text, tool_use, or tool_result."""

    window_id: str
    parts: tuple[str, ...]
    content_type: ContentType = "text"
    tool_use_id: str | None = None
    tool_name: str | None = None
    thread_id: int | None = None


@dataclass(frozen=True, slots=True)
class StatusUpdateTask:
    """An update to the status bubble (edit-in-place or send if missing)."""

    window_id: str
    text: str | None
    thread_id: int | None = None


@dataclass(frozen=True, slots=True)
class StatusClearTask:
    """A request to clear the status bubble for a topic."""

    window_id: str | None
    thread_id: int | None = None


MessageTask = ContentTask | StatusUpdateTask | StatusClearTask
```

### Design notes

- **Frozen + slots**: tasks cross queue boundaries; immutability eliminates
  aliasing bugs during the merge pass. `slots=True` keeps memory low —
  this dataclass is allocated on every enqueue.
- **`parts: tuple[str, ...]`** (not `list`): immutability + hashability if
  needed. The `list[str]` today is a latent mutation hazard.
- **`tool_use_id` / `tool_name` only on `ContentTask`**: both fields are
  meaningless for status tasks today. Keeping them off the other variants
  is the whole point.
- **`ContentType` is `Literal`**, not `str`. Same discipline as the
  top-level discriminator.
- **No methods**: not even helpers. If a helper is needed (`is_mergeable`,
  `with_merged_parts`), it lives in `message_queue.py` where merging is
  the concern — not on the data itself.

## Change Vectors

The module is designed to support **one** kind of change with zero ripple:

1. **A new message kind** (e.g., a `MediaTask` for future image uploads):
   add a new dataclass, extend the `MessageTask` union alias, update the
   `match` statements in `message_queue.py`. The change is opt-in — any
   module that does not care about the new kind keeps working.

Changes this module is **not** designed to support and for which ripple
across the cluster is still expected:

- Renaming an existing field (touches all three concrete modules —
  acceptable cost because renames are rare).
- Changing the shape of `content_type` (e.g., adding `"image"`) — touches
  every site that matches on it, which is by design.
