---
id: TASK-041
title: Docs, rollout plan, and final verification
status: done
priority: medium
req: REQ-008
epic: EPIC-008
depends: [TASK-040]
---

# TASK-041: Docs, rollout plan, and final verification

Finalize documentation and operator rollout guidance for multi-provider support.

## Implementation Steps

1. Update README/docs with provider configuration and capability matrix.
2. Add migration notes for existing Claude users and state compatibility behavior.
3. Add rollout checklist (default provider, fallback strategy, observability points).
4. Validate full suite and finish evidence capture.
5. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- Docs clearly describe Claude/Codex/Gemini setup and limits.
- Migration guidance exists for existing deployments.
- Rollout checklist is documented and actionable.
- All quality gates pass.
