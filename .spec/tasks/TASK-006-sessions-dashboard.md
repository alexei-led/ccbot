---
id: TASK-006
title: Add /sessions dashboard command
status: done
req: REQ-002
epic: EPIC-002
---

# TASK-006: Add /sessions dashboard command

New `/sessions` command showing all active sessions with status and actions.

## Implementation Steps

1. Create `handlers/sessions_dashboard.py`
2. Iterate all entries in `thread_bindings` to find active windows
3. For each window, get status from `status_polling` (active/idle/dead)
4. Format dashboard message with emoji indicators
5. Add `[Refresh]` and `[New Session]` inline buttons
6. Register `CommandHandler("sessions", sessions_command)` in `bot.py`
7. Add callback handlers for refresh and per-session actions

## Acceptance Criteria

- `/sessions` shows all bound sessions with status emoji
- Dead windows shown with dead indicator
- Refresh button re-renders dashboard
- New Session button triggers `/new` flow
