---
id: TASK-034
title: Provider baseline characterization and contracts
status: done
priority: high
req: REQ-008
epic: EPIC-008
---

# TASK-034: Provider baseline characterization and contracts

Create regression coverage for current Claude behavior and define normalized
provider contracts/events that all providers must implement.

## Implementation Steps

1. Add characterization tests for current Claude flows (launch, command forwarding,
   transcript updates, status parsing, interactive detection, resume/recovery entry points).
2. Introduce provider protocol types (interfaces + normalized events + capabilities schema).
3. Add provider contract tests (test doubles) to enforce interface semantics.
4. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- Characterization tests lock current Claude behavior before refactor.
- Provider contracts are explicit, typed, and test-covered.
- Contract test suite can be reused for future providers.
- All quality gates pass.
