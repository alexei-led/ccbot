---
id: TASK-001
title: Add multi-instance config variables
status: todo
req: REQ-001
epic: EPIC-001
---

# TASK-001: Add multi-instance config variables

Add `CCBOT_GROUP_ID` and `CCBOT_INSTANCE_NAME` to the Config class.

## Implementation Steps

1. In `config.py`, add two new fields to `Config`:
   - `group_id: int | None` — from `CCBOT_GROUP_ID` env var, default `None` (single-instance mode)
   - `instance_name: str` — from `CCBOT_INSTANCE_NAME` env var, default `socket.gethostname()`
2. Parse `CCBOT_GROUP_ID` as int (Telegram chat IDs are negative for groups)
3. Add validation: if set, must be a valid integer

## Acceptance Criteria

- `Config.group_id` is `None` when `CCBOT_GROUP_ID` not set
- `Config.group_id` is parsed as `int` when set
- `Config.instance_name` defaults to hostname
- Existing tests still pass
- New tests cover both cases
