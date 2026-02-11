---
id: TASK-010
title: Implement Fresh/Continue/Resume recovery flows
status: todo
req: REQ-003
epic: EPIC-003
depends: [TASK-009]
---

# TASK-010: Implement Fresh/Continue/Resume recovery flows

Implement the three recovery options for dead sessions.

## Implementation Steps

1. **Fresh**: `tmux_manager.create_window(cwd=cwd)` → rebind topic → forward pending message
2. **Continue**: `tmux_manager.create_window(cwd=cwd, command="claude --continue")` → rebind → forward
3. **Resume picker**:
   - Scan `~/.claude/projects/` for sessions matching the dead session's cwd
   - Parse session index files for metadata (timestamp, last message preview)
   - Show inline keyboard with up to 6 recent sessions
   - On pick: `tmux_manager.create_window(cwd=cwd, command="claude --resume <id>")` → rebind → forward
4. Error handling:
   - `--continue` fails → fall back to Fresh
   - `--resume` fails → show error, offer Fresh/Continue
   - cwd gone → directory browser

## Acceptance Criteria

- Fresh creates new session in same directory
- Continue resumes most recent session
- Resume picker shows session list with timestamps
- Pending message forwarded after recovery
- Error cases handled gracefully
