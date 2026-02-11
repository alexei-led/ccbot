---
id: TASK-008
title: Update forward_command_handler for discovered commands
status: todo
req: REQ-002
epic: EPIC-002
depends: [TASK-004]
---

# TASK-008: Update forward_command_handler for discovered commands

Ensure `forward_command_handler` correctly forwards all discovered CC commands to tmux.

## Implementation Steps

1. `forward_command_handler` already forwards unknown commands to CC via tmux keystrokes
2. Verify it works for skill commands (e.g., `/commit`, `/review-pr`)
3. Verify it works for custom commands (e.g., `/group:name` format)
4. Add prefix stripping if needed (Telegram sends `/command@botname`)

## Acceptance Criteria

- All discovered CC commands forwarded to tmux correctly
- Skill commands work (e.g., `/commit`)
- Custom commands with group prefix work
- Bot-native commands (`/new`, `/sessions`, `/resume`, `/history`) are NOT forwarded
