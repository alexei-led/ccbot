---
id: REQ-008
title: Multi-Agent CLI Provider Architecture
version: 1
priority: high
status: in_progress
epic: EPIC-008
---

# REQ-008: Multi-Agent CLI Provider Architecture

Evolve ccbot from a Claude-specific integration to a provider-driven architecture
that supports Claude Code, Codex CLI, and Gemini CLI, while making future terminal
agent integrations straightforward.

## Success Criteria

1. **Provider abstraction**: Core orchestration is provider-agnostic and depends on
   stable provider interfaces, not Claude-specific modules.
2. **Supported providers**: ccbot can run with `claude`, `codex`, or `gemini`
   as the active provider per instance.
3. **Future extensibility**: Adding a new terminal CLI provider does not require
   modifying core routing/session orchestration modules.
4. **Capability-aware behavior**: Features (hook install, resume, command discovery,
   structured transcript parsing) are enabled/disabled through provider capability
   policy without provider-specific conditionals spread across handlers.
5. **Claude compatibility**: Existing Claude workflows, data files, and user-visible
   behavior remain stable after migration.
6. **State compatibility**: Existing state/session map files are migrated or read
   compatibly when provider metadata is introduced.
7. **Quality gates**: All checks pass for final implementation:
   `make fmt && make test && make lint`.

## Constraints

- Preserve core invariant: **1 topic = 1 tmux window = 1 active provider session**.
- One provider per ccbot instance in this phase (no mixed-provider routing in a
  single bot instance).
- Avoid provider-type branching in core modules (`if provider == ...`) by using
  interface dispatch and centralized capability policy.
- Keep migration incremental and low-risk: extract Claude provider first with no
  behavior change before introducing Codex/Gemini adapters.
