---
id: TASK-032
title: Fix cold-start auto-topic creation with CCBOT_GROUP_ID
status: done
priority: high
epic: EPIC-001
depends: [TASK-002]
---

# TASK-032: Fix cold-start auto-topic creation with CCBOT_GROUP_ID

When no thread bindings exist (cold start), `_handle_new_window` cannot determine
which group chat to create topics in. When `CCBOT_GROUP_ID` is configured, use it
as the fallback target group for auto-topic creation.

## Implementation Steps

1. In `_handle_new_window` (bot.py), after collecting `seen_chats` from bindings,
   fall back to `config.group_id` when `seen_chats` is empty.
2. Add guard: skip auto-topic if no group ID available from either source.
3. When using `config.group_id` fallback, create topic but skip user binding
   (no user context available yet — binding happens on first message).
4. Write tests for: cold-start with CCBOT_GROUP_ID, cold-start without, normal flow.

## Acceptance Criteria

- New tmux windows get topics auto-created even with zero existing bindings (when CCBOT_GROUP_ID set)
- Without CCBOT_GROUP_ID and no bindings, auto-topic is gracefully skipped
- Existing flow (topics from bindings) unchanged
- All tests pass: `make check`
