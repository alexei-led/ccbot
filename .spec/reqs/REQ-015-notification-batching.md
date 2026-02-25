---
id: REQ-015
title: Smart Notification Batching for Tool Calls
type: feature
status: open
priority: medium
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-015: Smart Notification Batching for Tool Calls

## Motivation

When an agent executes a multi-step tool chain (e.g., read 5 files, run 3 bash
commands), CCBot sends each tool_use + tool_result as separate Telegram messages.
On a busy session, this floods the chat with 10–20 individual messages per task.

Users lose the actual useful response in the noise.

## Success Criteria

1. Tool call sequences (`tool_use` + `tool_result` pairs) within a configurable
   time window (default: 3 seconds) are **batched into a single collapsible message**
2. Batched message shows:
   - Header: `🔧 N tool calls` (expandable blockquote)
   - Inside: each tool name + short result summary (first line, max 80 chars)
3. If only 1 tool call: send normally (no batching overhead)
4. Final assistant text response always sent as a separate, clean message
5. Configurable batch window via `CCBOT_TOOL_BATCH_SECONDS` (default: 3)
6. `notification_mode` "errors_only" continues to work (batch, then filter)

## Implementation Notes

- Batch window timer: when first `tool_use` arrives, start a 3s timer
- Accumulate tool pairs during timer; send batch on timer expiry or on
  assistant text arrival (whichever first)
- Store accumulated batch in `context.user_data` or per-window state in
  `message_queue.py`
- Batch message uses expandable blockquote: `EXPANDABLE_QUOTE_START` sentinel
  (already used for thinking content)
- Existing `response_builder.py` can be extended with `build_tool_batch_parts()`

## Constraints

- Must not delay delivery of final assistant response
- Backward compatible: old behavior preserved when batch window = 0
- Must not break existing `test_response_builder.py` tests
