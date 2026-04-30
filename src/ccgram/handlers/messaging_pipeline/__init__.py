"""Messaging pipeline subpackage — per-user queue, sender, routing, batching.

Bundles the modules that turn assistant messages from SessionMonitor into
Telegram deliveries: queue primitives, the worker loop, content/status task
sum types, the safe-send helpers, and the tool-use batching state machine.

Public surface re-exported here is the entry point for ``bot.py`` and the
rest of ``handlers/``; internals stay in the per-module files.
"""

from .message_queue import (
    clear_tool_msg_ids_for_topic,
    enqueue_content_message,
    enqueue_status_update,
    get_message_queue,
    get_or_create_queue,
    shutdown_workers,
)
from .message_sender import (
    ALLOWED_REACTIONS,
    REACT_DONE,
    REACT_FAIL,
    REACT_INBOX,
    REACT_RUNNING,
    REACT_SEEN,
    REACT_THINKING,
    ack_reaction,
    clear_reaction,
    edit_with_fallback,
    is_thread_gone,
    rate_limit_send,
    rate_limit_send_message,
    react,
    safe_edit,
    safe_reply,
    safe_send,
    send_kwargs,
)
from .message_task import (
    ContentTask,
    ContentType,
    MessageTask,
    StatusClearTask,
    StatusUpdateTask,
    thread_key,
)
from .topic_commands import toolcalls_command, verbose_command
from .tool_batch import (
    ToolBatch,
    ToolBatchEntry,
    clear_all_batches,
    clear_batch_for_topic,
    flush_batch,
    flush_if_active,
    format_batch_message,
    has_active_batch,
    is_batch_eligible,
    process_tool_event,
)

__all__ = [
    "ALLOWED_REACTIONS",
    "REACT_DONE",
    "REACT_FAIL",
    "REACT_INBOX",
    "REACT_RUNNING",
    "REACT_SEEN",
    "REACT_THINKING",
    "ContentTask",
    "ContentType",
    "MessageTask",
    "StatusClearTask",
    "StatusUpdateTask",
    "ToolBatch",
    "ToolBatchEntry",
    "ack_reaction",
    "clear_all_batches",
    "clear_batch_for_topic",
    "clear_reaction",
    "clear_tool_msg_ids_for_topic",
    "edit_with_fallback",
    "enqueue_content_message",
    "enqueue_status_update",
    "flush_batch",
    "flush_if_active",
    "format_batch_message",
    "get_message_queue",
    "get_or_create_queue",
    "has_active_batch",
    "is_batch_eligible",
    "is_thread_gone",
    "process_tool_event",
    "rate_limit_send",
    "rate_limit_send_message",
    "react",
    "safe_edit",
    "safe_reply",
    "safe_send",
    "send_kwargs",
    "shutdown_workers",
    "thread_key",
    "toolcalls_command",
    "verbose_command",
]
