---
id: TASK-046
title: Team hook events (TeammateIdle, TaskCompleted)
status: done
priority: medium
req: REQ-021
epic: EPIC-009
---

# TASK-046: Team hook events (TeammateIdle, TaskCompleted)

Handle the two new Claude Code agent team hook events: `TeammateIdle` and `TaskCompleted`. Surface them as informational notifications in the Telegram topic.

## Background

Claude Code teams emit two hook events (in addition to the existing 5):

- **TeammateIdle**: fires when a teammate is about to go idle. Contains `teammate_name`, `team_name`, `session_id`.
- **TaskCompleted**: fires when a task is marked complete. Contains `task_id`, `task_subject`, `task_description`, `teammate_name`, `team_name`.

Both are written to `events.jsonl` by the existing hook infrastructure. The session monitor already reads events.jsonl — we just need to dispatch these new event types.

## Implementation Steps

1. Update `hook.py` to recognize the new event types:
   - The hook already writes all events to `events.jsonl` with the raw `hook_event_name`
   - Verify that `TeammateIdle` and `TaskCompleted` events are captured — they should be, since the hook writes any event it receives
   - If needed, add these to the hook install logic to register for these event types in Claude Code's settings

2. Update `hook_events.py` — add handlers:

   ```python
   async def _handle_teammate_idle(event: HookEvent, bot: Bot) -> None:
       """Handle TeammateIdle — notify topic that a teammate went idle."""
       users = _resolve_users_for_window_key(event.window_key)
       if not users:
           return
       teammate_name = event.data.get("teammate_name", "unknown")
       team_name = event.data.get("team_name", "")
       for user_id, thread_id, window_id in users:
           text = f"💤 Teammate '{teammate_name}' went idle"
           if team_name:
               text += f" (team: {team_name})"
           await enqueue_status_update(bot, user_id, window_id, text, thread_id=thread_id)

   async def _handle_task_completed(event: HookEvent, bot: Bot) -> None:
       """Handle TaskCompleted — notify topic that a task was completed."""
       users = _resolve_users_for_window_key(event.window_key)
       if not users:
           return
       task_subject = event.data.get("task_subject", "")
       teammate_name = event.data.get("teammate_name", "")
       for user_id, thread_id, window_id in users:
           text = f"✅ Task completed: {task_subject}"
           if teammate_name:
               text += f" (by '{teammate_name}')"
           await enqueue_status_update(bot, user_id, window_id, text, thread_id=thread_id)
   ```

3. Update `dispatch_hook_event` match statement:

   ```python
   case "TeammateIdle":
       await _handle_teammate_idle(event, bot)
   case "TaskCompleted":
       await _handle_task_completed(event, bot)
   ```

4. Update hook install to register for new event types:
   - In `hook.py`'s hook configuration, add `TeammateIdle` and `TaskCompleted` to the list of events
   - Both should be non-blocking (async): they are informational, not decision points
   - The hook command is the same as existing events (write to events.jsonl)

5. Verify the session monitor's event reader parses the new event types correctly:
   - The reader in `session_monitor.py` should already handle any `hook_event_name` — check that it passes through `teammate_name`, `team_name`, `task_subject`, `task_description`, `task_id` in the `data` dict

## Acceptance Criteria

- [ ] `TeammateIdle` events surface as "💤 Teammate went idle" in the topic
- [ ] `TaskCompleted` events surface as "✅ Task completed" in the topic
- [ ] Events route to the correct topic via window_key → thread binding
- [ ] Hook install registers for the 2 new event types (7 total)
- [ ] Events without bound users are silently ignored
- [ ] Tests cover: event dispatch, message formatting, no-user-bound case
- [ ] `make check` passes
