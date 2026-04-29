"""Inter-agent messaging subpackage.

Bundles the modules that implement agent-to-agent messaging via the
file-based mailbox: ``msg_broker`` (delivery cycle injecting messages
into idle agent windows via send_keys), ``msg_delivery`` (per-window
delivery state — rate limiting, loop detection, crash recovery),
``msg_telegram`` (Telegram notifications for sent/delivered/reply/loop
events), and ``msg_spawn`` (Telegram approval flow for spawn requests
and auto-creation of bound topics).

Public surface re-exported here is the entry point for ``bot.py``,
``polling/periodic_tasks.py`` and the rest of ``handlers/``; internals
stay in the per-module files.
"""

from .msg_broker import (
    BROKER_CYCLE_INTERVAL,
    SWEEP_INTERVAL,
    broker_delivery_cycle,
    format_file_reference,
    format_injection_text,
    merge_injection_texts,
    write_delivery_file,
)
from .msg_delivery import (
    DeliveryState,
    MessageDeliveryStrategy,
    clear_delivery_state,
    delivery_strategy,
    reset_delivery_state,
)
from .msg_spawn import (
    CB_SPAWN_APPROVE,
    CB_SPAWN_DENY,
    handle_spawn_approval,
    handle_spawn_denial,
    post_spawn_approval_keyboard,
)
from .msg_telegram import (
    CB_MSG_LOOP_ALLOW,
    CB_MSG_LOOP_PAUSE,
    clear_loop_alerts,
    notify_loop_detected,
    notify_message_sent,
    notify_messages_delivered,
    notify_pending_shell,
    notify_reply_received,
    resolve_topic,
)

__all__ = [
    "BROKER_CYCLE_INTERVAL",
    "CB_MSG_LOOP_ALLOW",
    "CB_MSG_LOOP_PAUSE",
    "CB_SPAWN_APPROVE",
    "CB_SPAWN_DENY",
    "DeliveryState",
    "MessageDeliveryStrategy",
    "SWEEP_INTERVAL",
    "broker_delivery_cycle",
    "clear_delivery_state",
    "clear_loop_alerts",
    "delivery_strategy",
    "format_file_reference",
    "format_injection_text",
    "handle_spawn_approval",
    "handle_spawn_denial",
    "merge_injection_texts",
    "notify_loop_detected",
    "notify_message_sent",
    "notify_messages_delivered",
    "notify_pending_shell",
    "notify_reply_received",
    "post_spawn_approval_keyboard",
    "reset_delivery_state",
    "resolve_topic",
    "write_delivery_file",
]
