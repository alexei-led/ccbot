---
id: REQ-004
title: Telegram UI Modernization
status: todo
priority: medium
phase: 4
---

# REQ-004: Telegram UI Modernization

Richer Telegram UI with topic status emoji, sessions dashboard, and contextual quick actions.

## Success Criteria

1. Topic emoji reflects session state: Active (working), Idle (waiting), Dead (expired)
2. Graceful degradation: if bot lacks "Manage Topics" permission, skip emoji silently
3. `/sessions` dashboard shows all active sessions with status, expandable details, and actions
4. Status messages include quick action buttons (`[Esc]`, `[Screenshot]`)
5. Buttons removed when status clears
6. Kill action requires confirmation dialog
7. Expandable blockquote formatting verified for thinking content

## Constraints

- Bot must be admin with "Manage Topics" permission for emoji feature
- Dashboard should be pinned in General topic
