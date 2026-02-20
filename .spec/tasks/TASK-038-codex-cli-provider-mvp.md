---
id: TASK-038
title: Add Codex CLI provider MVP
status: todo
priority: medium
req: REQ-008
epic: EPIC-008
depends: [TASK-037]
---

# TASK-038: Add Codex CLI provider MVP

Implement first working Codex provider with stable core flows and explicit
capability limits.

## Implementation Steps

1. Implement Codex provider launch/session/event integration using available
   terminal and transcript signals.
2. Declare unsupported features explicitly via capability policy (if any).
3. Add provider-specific tests and contract tests.
4. Verify core flows: new session, message forwarding, response delivery,
   status polling, dead-window handling.
5. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- ccbot runs with Codex provider in MVP mode.
- Unsupported features are safely gated (no broken UI paths).
- Contract and integration tests pass for Codex path.
- All quality gates pass.
