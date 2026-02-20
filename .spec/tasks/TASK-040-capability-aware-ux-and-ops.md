---
id: TASK-040
title: Capability-aware UX and operational tooling
status: todo
priority: medium
req: REQ-008
epic: EPIC-008
depends: [TASK-038, TASK-039]
---

# TASK-040: Capability-aware UX and operational tooling

Ensure bot UX and operational commands are provider-aware through centralized
capability policy.

## Implementation Steps

1. Update menus/buttons/command registration to show only provider-supported flows.
2. Update doctor/status output to include provider diagnostics and capability hints.
3. Ensure recovery/resume/command discovery paths degrade gracefully per provider.
4. Add tests for capability matrix behavior across Claude/Codex/Gemini.
5. Verify: `make fmt && make test && make lint`.

## Acceptance Criteria

- No dead actions are exposed for unsupported provider features.
- Doctor/status expose provider-aware diagnostics.
- Capability matrix behavior is test-covered.
- All quality gates pass.
