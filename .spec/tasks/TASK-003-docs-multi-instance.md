---
id: TASK-003
title: Update docs for multi-instance
status: done
req: REQ-001
epic: EPIC-001
depends: [TASK-001, TASK-002]
---

# TASK-003: Update docs for multi-instance

Update `.env.example`, README, and architecture docs for multi-instance setup.

## Implementation Steps

1. Add `CCBOT_GROUP_ID` and `CCBOT_INSTANCE_NAME` to `.env.example` with comments
2. Add multi-instance section to README.md explaining the setup
3. Update `.claude/rules/architecture.md` if needed

## Acceptance Criteria

- `.env.example` documents both new variables
- README has a "Multi-Instance" section with example setup
