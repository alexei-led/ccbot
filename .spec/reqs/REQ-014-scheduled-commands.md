---
id: REQ-014
title: Scheduled Commands (Deferred Task Execution)
type: feature
status: open
priority: medium
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-014: Scheduled Commands (Deferred Task Execution)

## Motivation

Users often want to queue a command to run after the current agent task
completes, or schedule work for a future time. Currently the only way is to
manually send the next message when the agent becomes idle.

Example use cases:
- "Run tests in 5 minutes"
- "After the refactor is done, run `/compact`"
- "At 9 PM: commit and push"

## Success Criteria

1. `/schedule <delay> <command>` syntax: e.g. `/schedule 5m /compact`
2. `/schedule at <HH:MM> <command>`: e.g. `/schedule at 21:00 git push`
3. `/schedule on-idle <command>`: fires when current agent transitions to idle
4. `/scheduled` command lists all pending scheduled tasks for the topic
5. `/cancel <task_id>` cancels a scheduled task
6. Scheduled tasks are persisted to disk (survive bot restart)
7. Confirmation message shows: task ID, scheduled time, command preview
8. When task fires: sends the command to the window + notifies user in topic

## Implementation Notes

- Persistent schedule store: `~/.ccbot/schedule.json`
  (list of `{id, user_id, thread_id, window_id, fire_at, command}`)
- Background asyncio task: `schedule_poll_loop()` runs every 30s, checks
  `fire_at <= now()`
- `on-idle` variant: hook into status polling — detect transition from
  "working" → "idle" and fire queued on-idle tasks
- Task IDs: short 4-char alphanumeric for easy cancellation
- `/schedule` parses natural-language delays via a simple parser
  (`5m` → 300s, `1h30m` → 5400s, `at HH:MM` → next occurrence)
- `python-dateutil` for time parsing (already likely in deps)

## Constraints

- No external scheduler (Celery, APScheduler) — pure asyncio
- Max 10 scheduled tasks per topic to prevent abuse
- Time zone: use system timezone (same as bot host)
- Commands that reference a dead window at fire time → notify user, discard
