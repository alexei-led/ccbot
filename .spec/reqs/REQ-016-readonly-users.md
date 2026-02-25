---
id: REQ-016
title: Read-Only User Role for ALLOWED_USERS
type: feature
status: open
priority: low
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-016: Read-Only User Role for ALLOWED_USERS

## Motivation

Currently `ALLOWED_USERS` is binary: either full access or no access. There's
no way to give a teammate or observer read-only visibility into active sessions
without granting them full control (ability to send commands, kill sessions,
create new windows).

This is useful for:
- Sharing a session with a code reviewer
- Letting a manager observe without interfering
- Monitoring mode on a shared machine

## Success Criteria

1. New env var: `READONLY_USERS=<comma-separated-user-ids>`
2. Read-only users can:
   - Receive all session output (messages forwarded normally to their topics)
   - Use `/history` and `/sessions` for viewing
   - Use `/screenshot`
3. Read-only users cannot:
   - Send text to a window
   - Use `/kill`, `/new`, `/resume`, `/clear`
   - Access directory browser or window picker
   - Interact with permission prompts
4. Blocked actions show a clear message: "👁 You have read-only access"
5. Existing `is_user_allowed()` in `Config` extended with `is_readonly()`
6. Auth middleware in `bot.py` enforces restrictions

## Implementation Notes

- `Config.readonly_users: set[int]` from `READONLY_USERS` env var
- `Config.is_readonly(user_id: int) -> bool`
- In `bot.py` text handler: if `is_readonly(user.id)` → safe_reply with
  read-only notice + return
- In callback handler: check readonly before any mutating callbacks
- Read-only users can still be in `ALLOWED_USERS` OR just in `READONLY_USERS`
  (union determines total allowed set)

## Constraints

- `ALLOWED_USERS` behavior unchanged
- No database or ACL system — simple env var lists only
- Readonly restriction is per-user-id, not per-topic
