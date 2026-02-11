---
id: TASK-007
title: Demote /esc, /kill, /screenshot to inline buttons
status: todo
req: REQ-002
epic: EPIC-002
depends: [TASK-006]
---

# TASK-007: Demote /esc, /kill, /screenshot to inline buttons

Remove top-level `/esc`, `/kill`, `/screenshot` commands. Actions available via contextual inline buttons.

## Implementation Steps

1. Remove `CommandHandler` registrations for `/esc`, `/kill`, `/screenshot` from `bot.py`
2. Add `[Esc]` and `[Screenshot]` buttons to status messages in `status_polling.py`
3. Add `[Kill Session]` button to `/sessions` dashboard with confirmation
4. Add corresponding callback handlers in `callback_data.py` and `bot.py`
5. Kill confirmation: two-step (show warning, then confirm)
6. When status clears, edit message to remove buttons

## Acceptance Criteria

- `/esc`, `/kill`, `/screenshot` no longer work as commands
- `[Esc]` button appears on active status messages
- `[Screenshot]` button available on status messages
- `[Kill]` available in sessions dashboard with confirmation
- Buttons removed when status clears
