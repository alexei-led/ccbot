# Message Handling

## Message Queue Architecture

Per-user message queues + worker pattern for all send tasks:
- Messages are sent in receive order (FIFO)
- Status messages always follow content messages
- Multi-user concurrent processing without interference

**Module layout**: Task types (`ContentTask`, `StatusTask`, `ToolResultTask`) live in `message_task.py` — a dependency-free sum type imported by `message_queue.py`, `tool_batch.py`, and `status_bubble.py` without circular imports. Inbound message routing (SessionMonitor → Telegram topics) lives in `message_routing.py`.

**Message merging**: The worker automatically merges consecutive mergeable content messages on dequeue:
- Content messages for the same window can be merged (including text, thinking)
- tool_use breaks the merge chain and is sent separately (message ID recorded for later editing)
- tool_result breaks the merge chain and is edited into the tool_use message (preventing order confusion)
- Merging stops when combined length exceeds 3800 characters (to avoid pagination)

## Status Message Handling

**Conversion**: The status message is edited into the first content message, reducing message count:
- When a status message exists, the first content message updates it via edit
- Subsequent content messages are sent as new messages

**Polling**: Background task polls terminal status for all active windows at 1-second intervals. Send-layer rate limiting ensures flood control is not triggered.

**Deduplication**: The worker compares `last_text` when processing status updates; identical content skips the edit, reducing API calls.

## Rate Limiting

- Minimum 1.1-second interval between messages per user
- Status polling interval: 1 second (send layer has rate limiting protection)
- Automated outbound messages (queue worker, status updates) go through `rate_limit_send()`

## Performance Optimizations

**mtime cache**: The monitoring loop maintains an in-memory file mtime cache, skipping reads for unchanged files.

**Byte offset incremental reads**: Each tracked session records `last_byte_offset`, reading only new content. File truncation (offset > file_size) is detected and offset is auto-reset.

## No Message Truncation

Historical messages (tool_use summaries, tool_result text, user/assistant messages) are always kept in full — no character-level truncation at the parsing layer. Long text is handled exclusively at the send layer: `split_message` splits by Telegram's 4096-character limit; real-time messages get `[1/N]` text suffixes, history pages get inline keyboard navigation.
