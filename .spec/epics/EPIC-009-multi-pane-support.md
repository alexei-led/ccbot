---
id: EPIC-009
title: Multi-Pane Support for Agent Teams
reqs: [REQ-021]
status: done
---

# EPIC-009: Multi-Pane Support for Agent Teams

Auto-detect and interact with multiple tmux panes within a window. Surfaces blocked teammate panes as inline alerts in the Telegram topic, routes responses to the correct pane, and adds pane management commands.

## Tasks (in order)

1. TASK-042: Pane infrastructure in tmux_manager (list_panes, capture_by_id, send_keys_to_pane)
2. TASK-043: Multi-pane scanning in status_polling (detect blocked panes, track alert state)
3. TASK-044: Pane-aware interactive UI and callbacks (pane_id in callback data, per-pane alerts)
4. TASK-045: /panes command and /screenshot pane picker
5. TASK-046: Team hook events (TeammateIdle, TaskCompleted notifications)
