---
id: REQ-001
title: Multi-Instance Architecture
status: todo
priority: high
phase: 1
---

# REQ-001: Multi-Instance Architecture

Multiple ccbot instances can share one Telegram bot token, each owning a different Telegram group.

## Success Criteria

1. Two ccbot instances with different `CCBOT_GROUP_ID` values can run simultaneously against the same bot token
2. Each instance only processes updates from its own group (silently ignores others)
3. Single-instance mode (no `CCBOT_GROUP_ID`) still works unchanged -- accepts all groups
4. Each instance has isolated state via separate `CCBOT_DIR` paths
5. `CCBOT_INSTANCE_NAME` is available for display purposes (defaults to hostname)

## Constraints

- No cross-instance coordination, IPC, or distributed locking
- Filtering happens at the earliest point in every handler
- Existing single-instance deployments must work without config changes
