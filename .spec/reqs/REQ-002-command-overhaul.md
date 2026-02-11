---
id: REQ-002
title: Command Overhaul
status: todo
priority: high
phase: 2
---

# REQ-002: Command Overhaul

Reorganize commands into three tiers: bot-native, auto-discovered CC commands, and contextual inline actions.

## Success Criteria

1. `/start` renamed to `/new` (creates new session via directory browser / window picker)
2. `/resume` command allows resuming closed sessions by project
3. `/sessions` command shows dashboard of all active sessions with status
4. `/history` retained as-is
5. CC commands (builtins + skills + custom commands) auto-discovered from filesystem
6. Discovered commands registered via `set_my_commands()` in Telegram menu
7. `/esc`, `/kill`, `/screenshot` removed as top-level commands, replaced by inline buttons
8. CC command discovery refreshed periodically (every 10 minutes)

## Constraints

- Telegram limit: 50 commands per menu (4 bot-native + up to 46 discovered)
- Telegram limit: 256 chars per command description
- Callback data must stay under 64 bytes
