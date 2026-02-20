---
id: TASK-039
title: Add Gemini CLI provider MVP
status: todo
priority: medium
req: REQ-008
epic: EPIC-008
depends: [TASK-037]
---

# TASK-039: Add Gemini CLI provider MVP

Implement first working Gemini provider with the same core guarantees as Codex MVP.

## Implementation Steps

1. Implement Gemini provider launch/session/event integration using available
   terminal and transcript signals.
2. Declare unsupported features explicitly via capability policy (if any).
3. Add provider-specific tests and contract tests.
4. Verify core flows: new session, message forwarding, response delivery,
   status polling, dead-window handling.
5. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- ccbot runs with Gemini provider in MVP mode.
- Unsupported features are safely gated (no broken UI paths).
- Contract and integration tests pass for Gemini path.
- All quality gates pass.
