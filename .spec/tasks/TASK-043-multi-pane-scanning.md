---
id: TASK-043
title: Multi-pane scanning in status_polling
status: done
priority: high
req: REQ-021
epic: EPIC-009
depends: [TASK-042]
---

# TASK-043: Multi-pane scanning in status_polling

Extend the status polling loop to detect and scan multiple panes. When a window has >1 pane, scan non-active panes for interactive prompts and trigger alerts.

## Implementation Steps

1. Add pane alert state tracking to `status_polling.py`:

   ```python
   @dataclass
   class PaneAlertState:
       pane_id: str
       window_id: str
       prompt_hash: str        # hash of detected prompt text
       message_id: int | None  # Telegram message ID for the alert
       last_seen: float        # monotonic time

   # Module-level: pane_id -> alert state
   _pane_alerts: dict[str, PaneAlertState] = {}
   ```

2. Add `_scan_window_panes(window_id, bot, user_id, thread_id)` async function:
   - Call `tmux_manager.list_panes(window_id)`
   - If only 1 pane: return immediately (fast path, no overhead)
   - For each non-active pane:
     a. `tmux_manager.capture_pane_by_id(pane_id)`
     b. `terminal_parser.extract_interactive_content(pane_text)`
     c. If interactive content found:
     - Compute prompt hash (hash of content lines)
     - If pane_id not in `_pane_alerts` or hash changed → trigger alert
     - If hash unchanged → skip (already notified)
       d. If no interactive content but pane_id in `_pane_alerts` → dismiss (prompt resolved)
   - Clean up alerts for panes that no longer exist

3. Integrate into the existing poll loop:
   - In `_poll_all_windows` or equivalent, after processing the active pane's status, call `_scan_window_panes`
   - Only scan panes for windows that have an active thread binding (bound to a topic)

4. Add alert triggering — call into `interactive_ui.handle_interactive_ui` with `pane_id` parameter (TASK-044 adds the parameter; for now, use a pane-specific notification path):
   - Format message: "🔀 Pane {index} ({command}):" + prompt content
   - Include pane_id in callback data for routing
   - Track the sent message_id in `PaneAlertState`

5. Add alert dismissal:
   - When prompt resolves (no interactive content in pane): edit the alert message to "✓ Resolved"
   - When pane closes (not in pane list): edit alert to "Pane closed" and remove from tracking
   - Use `bot.edit_message_text` with error handling (message may already be deleted)

6. Add `clear_pane_alerts(window_id)` function:
   - Called when window is killed/unbound
   - Removes all pane alert state for that window

7. Performance guard:
   - Only call `list_panes` if we haven't checked in the last 2 poll cycles (2s), to avoid hammering tmux for single-pane windows
   - Cache pane count per window: `_window_pane_counts: dict[str, int]`
   - Refresh cache every 5s or on window list change

## Acceptance Criteria

- [ ] Single-pane windows have zero scanning overhead
- [ ] Non-active panes with interactive prompts trigger alerts in the topic
- [ ] Alerts are deduplicated (same prompt → no repeat notification)
- [ ] Resolved prompts auto-dismiss the alert message
- [ ] Closed panes auto-dismiss their alerts
- [ ] Window unbind/kill clears all pane alert state
- [ ] Tests cover: multi-pane detection, alert trigger, dedup, dismissal
- [ ] `make check` passes
