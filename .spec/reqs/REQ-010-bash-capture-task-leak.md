---
id: REQ-010
title: Bash Capture Task Reference Leak
type: bug
status: open
priority: low
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-010: Bash Capture Task Reference Leak

## Problem

In `handlers/text_handler.py`, `_capture_bash_output()` stores the asyncio
Task in `_bash_capture_tasks[(user_id, thread_id)]`. The `finally` block cleans
up with:

```python
if _bash_capture_tasks.get(key) is asyncio.current_task():
    _bash_capture_tasks.pop(key, None)
```

There is a subtle race: if the user sends a second `!` command before the first
task's finally block runs, `_bash_capture_tasks[key]` is already replaced by
the new task. The identity check fails → the old task's reference is never
cleaned from the dict. In practice, `_cancel_bash_capture()` is called before
creating the new task, so this race requires specific timing, but the pattern
is fragile.

Additionally: if `_capture_bash_output` raises an unexpected exception before
the identity check, the dict retains a reference to a dead Task object.

## Root Cause

`finally` cleanup uses identity comparison against `asyncio.current_task()`,
but the dict value may have been replaced by a concurrent `_cancel_bash_capture`
+ new task creation sequence.

Key file: `src/ccbot/handlers/text_handler.py`

## Success Criteria

1. No stale Task references in `_bash_capture_tasks` after task completion
2. Cleanup is unconditional in `finally` (remove the identity check)
3. `_cancel_bash_capture` cancels properly in all orderings
4. Add a test that verifies dict cleanup on normal completion and cancellation

## Implementation Notes

Simplest fix: remove the `asyncio.current_task()` identity guard and just pop
unconditionally. The cancel-before-create sequence in `_forward_message` already
prevents a new task from being poisoned. Alternatively, use a per-key generation
counter to detect replacement.

## Constraints

- No behavior change in the happy path
- Must handle rapid consecutive `!` commands correctly
