---
id: REQ-021
title: Multi-Pane Support for Agent Teams
status: todo
priority: high
type: feature
---

# REQ-021: Multi-Pane Support for Agent Teams

Claude Code's agent teams feature (`--teammate-mode tmux`) spawns multiple tmux panes within a single window. Each teammate runs in its own pane. ccbot currently only sees/interacts with the active pane, causing blocked teammate panes (permission prompts, y/n questions) to stall the entire team silently.

## Problem

- ccbot's `tmux_manager.py` targets `window.active_pane` for all operations (capture, send_keys, get_pane_title)
- `status_polling.py` only scans the active pane for interactive UI
- Permission prompts in teammate panes are invisible to the Telegram user
- Users resort to running a separate Claude Code instance to manually manage teammate panes
- `hook_events.py` doesn't handle `TeammateIdle` or `TaskCompleted` events
- Teammate `SessionStart` hooks overwrite the lead's `session_map.json` entry (all panes in a window resolve to the same key)

## Success Criteria

- [ ] ccbot detects when a window has multiple panes
- [ ] Interactive prompts (permissions, y/n) in ANY pane are auto-surfaced in the Telegram topic
- [ ] User can approve/deny prompts for specific panes via inline keyboard buttons
- [ ] Responses route to the correct pane via stable pane ID (`%N` format)
- [ ] `/panes` command lists all panes in the current window with status
- [ ] User can screenshot any specific pane
- [ ] `TeammateIdle` and `TaskCompleted` hook events are surfaced as notifications
- [ ] Single-pane windows (99% of the time) have zero overhead — no behavior change
- [ ] Stale pane alerts auto-dismiss when the prompt resolves or the pane closes

## Constraints

- Use stable pane IDs (`%N`), never pane indices (shift when panes close)
- No session_map schema changes in v1 — use pure terminal scanning
- No topic-per-pane in v1 — inline alerts only (topic-per-pane deferred to v2)
- Text input from user always goes to the active pane (lead) by default
- Callback data must stay under 64 bytes (Telegram limit)
- Pane scanning overhead must be negligible (<50ms per poll cycle for 5 panes)
- All existing single-pane behavior must be preserved unchanged

## Out of Scope (v2)

- Topic-per-pane (`/split` command creating temporary sub-topics)
- Session_map pane-level keying (tracking per-pane sessions)
- Pane focus / message routing to non-active panes
- Team dashboard parsing `~/.claude/teams/*/config.json`
- Teammate transcript monitoring
