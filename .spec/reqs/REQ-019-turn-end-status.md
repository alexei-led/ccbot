---
id: REQ-019
title: Turn-End Status (completed / failed / cancelled)
type: feature
status: open
priority: medium
inspired_by: slopus/happy sessionProtocol.ts
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-019: Turn-End Status (completed / failed / cancelled)

## Motivation

Currently CCBot knows when a Claude turn ends (agent goes idle / hook `Stop`
event fires), but it doesn't distinguish *how* it ended:

- **completed** — agent finished successfully, ready for next task
- **failed** — agent hit an error or crashed mid-turn
- **cancelled** — user sent `Escape` or `/kill` while agent was working

All three look the same in Telegram: session just goes quiet. The topic emoji
might become 💤 (idle) regardless of what actually happened. This is
information loss.

Inspired by Happy Coder's typed session protocol:
```typescript
sessionTurnEndEventSchema = z.object({
  t: z.literal('turn-end'),
  status: z.enum(['completed', 'failed', 'cancelled']),
})
```

## Success Criteria

1. Claude Code Stop hook payload is inspected for exit reason / error signals
2. Provider method `parse_turn_end_status(event) -> Literal["completed", "failed", "cancelled"]`
   added to `AgentProvider` protocol
3. Topic emoji reflects turn-end status:
   - ✅ completed (then back to 💤 idle after a few seconds)
   - ❌ failed (stays until user acknowledges or new session starts)
   - 🚫 cancelled (brief flash, then 💤 idle)
4. Telegram status message updated with status on turn end
5. `notification_mode = "errors_only"` now actually suppresses completed/cancelled
   notifications and only delivers failed turn-end alerts
6. Works for Claude (hook-based) — Codex/Gemini via terminal scraping heuristic
   (exit code detection or process signal)

## Implementation Notes

### Claude (hook-based)
The `Stop` hook payload from Claude Code contains `stop_reason` or similar
field. Inspect `events.jsonl` Stop events for:
- Normal stop → `completed`
- `stop_reason: "error"` or non-zero exit → `failed`
- Stop triggered immediately after Escape/kill keystroke → `cancelled`
  (detect via: Stop event within 1s of a user-sent `\x1b` keystroke)

### Codex / Gemini (heuristic)
Terminal scraping: check if process exited with non-zero code, or if shell
prompt returned unexpectedly fast after a long tool chain → `failed`.
Normal shell return → `completed`.

### Provider protocol change
```python
def parse_turn_end_status(
    self,
    event: dict[str, Any],
    context: dict[str, Any],  # e.g. last_user_keystroke_time
) -> Literal["completed", "failed", "cancelled"]:
    ...
```

### Topic emoji mapping
Add to `topic_emoji.py`:
```python
TURN_END_EMOJI = {
    "completed": "✅",
    "failed":    "❌",
    "cancelled": "🚫",
}
```
Flash for 5s, then revert to idle (💤) for completed/cancelled.
Persist ❌ for failed until next user message.

### Notification filter
Update `notification_mode` handling in `session_monitor.py`:
`errors_only` → only deliver `failed` turn-end events to Telegram.

## Constraints

- No behavior change when `Stop` hook payload lacks exit reason (default to `completed`)
- Must not break existing `test_hook_events.py` and `test_topic_emoji.py`
- Codex/Gemini heuristic is best-effort — accuracy < 100% is acceptable
- Flash emoji logic must not conflict with autoclose timer
