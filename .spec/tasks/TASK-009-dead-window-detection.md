---
id: TASK-009
title: Dead window detection and recovery UI
status: done
req: REQ-003
epic: EPIC-003
---

# TASK-009: Dead window detection and recovery UI

When user messages a topic bound to a dead window, show recovery options.

## Implementation Steps

1. In `text_handler`, after resolving `window_id` from `thread_bindings`:
   - Call `tmux_manager.find_window_by_id(window_id)`
   - If `None`: window is dead, show recovery UI
2. Build recovery inline keyboard:
   ```
   [Fresh]  [Continue]  [Resume]
   ```
3. Store pending message text so it can be forwarded after recovery
4. Add callback handlers for each recovery option
5. Read `cwd` from `window_states[window_id]` in state.json

## Acceptance Criteria

- Dead window detected when user sends message
- Recovery keyboard shown with 3 options
- Pending message stored for later forwarding
- If window_states has no cwd, fall back to directory browser
