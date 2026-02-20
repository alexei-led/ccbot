---
id: EPIC-008
title: Multi-Agent CLI Providers
reqs: [REQ-008]
status: done
---

# EPIC-008: Multi-Agent CLI Providers

Introduce provider-driven architecture for terminal agent CLIs. Preserve Claude
behavior while enabling Codex and Gemini support and establishing a stable path
to add future providers.

## Tasks (in order)

1. TASK-034: Baseline characterization tests and provider contracts
2. TASK-035: Provider registry and capability policy
3. TASK-036: Claude provider extraction with parity
4. TASK-037: Core integration refactor + state/session map compatibility
5. TASK-038: Codex CLI provider MVP
6. TASK-039: Gemini CLI provider MVP
7. TASK-040: Capability-aware UX + operational commands
8. TASK-041: Documentation + rollout guide + final verification
