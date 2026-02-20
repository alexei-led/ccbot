---
id: TASK-036
title: Extract Claude provider with behavior parity
status: done
priority: high
req: REQ-008
epic: EPIC-008
depends: [TASK-035]
---

# TASK-036: Extract Claude provider with behavior parity

Move Claude-specific logic behind provider interfaces without changing user-visible
behavior.

## Implementation Steps

1. Create Claude provider module wrapping existing hook, transcript parsing,
   terminal parsing, command discovery, and resume semantics.
2. Route core call sites through the provider abstraction while preserving behavior.
3. Keep compatibility with existing `.claude` layout and current env defaults.
4. Run characterization suite from TASK-034 and fix regressions.
5. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- Core behavior for Claude users remains unchanged.
- Claude-specific logic is isolated to provider module(s).
- Existing tests plus characterization tests pass.
- All quality gates pass.
