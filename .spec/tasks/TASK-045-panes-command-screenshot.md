---
id: TASK-045
title: /panes command and /screenshot pane picker
status: done
priority: medium
req: REQ-021
epic: EPIC-009
depends: [TASK-042]
---

# TASK-045: /panes command and /screenshot pane picker

Add a `/panes` command to list all panes in the current window with status indicators, and extend `/screenshot` with a pane picker when multiple panes exist.

## Implementation Steps

1. Add callback data constants in `callback_data.py`:

   ```python
   # Pane management
   CB_PANE_SCREENSHOT = "pn:ss:"  # pn:ss:<window_id>:<pane_id>
   CB_PANE_FOCUS = "pn:foc:"     # pn:foc:<window_id>:<pane_id> (future: v2)
   ```

2. Create `/panes` command handler (add to `bot.py` command registration):
   - Resolve window_id from thread binding (same as other topic commands)
   - Call `tmux_manager.list_panes(window_id)`
   - If 1 pane: "Single pane — no multi-pane layout detected."
   - If multiple panes, format:

     ```
     📐 3 panes in window

     📍 Pane 0 (claude) — active, lead
        Pane 1 (claude) — running
     ⚠️ Pane 2 (claude) — blocked

     [📷 0] [📷 1] [📷 2]
     ```

   - "blocked" status: check `_pane_alerts` from status_polling for this pane_id
   - Each screenshot button: `CB_PANE_SCREENSHOT + window_id + ":" + pane_id`

3. Add pane screenshot callback handler (new file or in `screenshot_callbacks.py`):
   - Parse `window_id` and `pane_id` from callback data
   - Call `tmux_manager.capture_pane_by_id(pane_id, with_ansi=True)`
   - Render screenshot using existing `screenshot.py` module
   - Send as photo with caption: "Pane {index} ({command})"

4. Extend `/screenshot` command in `bot.py`:
   - After resolving window_id, call `tmux_manager.list_panes(window_id)`
   - If 1 pane: current behavior unchanged (capture active pane)
   - If multiple panes: show pane picker inline keyboard first
     ```
     Select pane to screenshot:
     [📍 Pane 0 (lead)] [Pane 1] [Pane 2]
     ```
   - Each button triggers the pane screenshot callback from step 3

5. Register the `/panes` command:
   - Add to `bot.py` command handlers
   - Add to BotFather command list in README/docs

## Acceptance Criteria

- [ ] `/panes` lists all panes with correct status indicators
- [ ] Screenshot buttons capture the correct pane (not active pane)
- [ ] Single-pane windows show simple message for `/panes`
- [ ] `/screenshot` shows pane picker when multiple panes exist
- [ ] `/screenshot` works unchanged for single-pane windows
- [ ] Tests cover: multi-pane listing, screenshot routing
- [ ] `make check` passes
