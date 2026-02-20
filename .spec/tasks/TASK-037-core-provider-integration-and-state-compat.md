---
id: TASK-037
title: Integrate provider interfaces into core and migrate state compatibly
status: done
priority: high
req: REQ-008
epic: EPIC-008
depends: [TASK-036]
---

# TASK-037: Integrate provider interfaces into core and migrate state compatibly

Complete core migration so orchestration modules use provider interfaces, and add
backward-compatible state/session map evolution for provider metadata.

## Implementation Steps

1. Refactor core modules to consume provider contracts (session monitor, handlers,
   command registration, recovery/resume routing paths).
2. Introduce provider-aware session reference/state fields with backward-compatible
   read path for existing files.
3. Add migration tests for old/new state and session map formats.
4. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- Core orchestration no longer imports provider-specific modules directly.
- Existing persisted state remains readable after upgrade.
- State migration behavior is test-covered.
- All quality gates pass.
