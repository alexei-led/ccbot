---
id: REQ-017
title: Automatic Topic Naming from Agent Context
type: feature
status: open
priority: low
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-017: Automatic Topic Naming from Agent Context

## Motivation

New topics are named manually by the user (Telegram requires a name when
creating the topic). After the agent starts working, the topic name often
becomes stale or generic (e.g., "New Topic 3"). It would be more useful if the
topic title reflected what the agent is actually working on.

## Success Criteria

1. Within 30 seconds of a session starting (first assistant message received),
   CCBot generates a short topic title (≤ 30 chars) from the first user message
   or first assistant response summary
2. Topic is renamed automatically if the bot has "Manage Topics" permission
3. If permission is missing, skip silently (same graceful degradation as emoji)
4. User can always rename the topic manually afterward (no re-override)
5. Auto-naming only fires once per session (not on every new message)
6. Config flag: `CCBOT_AUTO_NAME_TOPICS=1` (opt-in, default off)

## Implementation Notes

- Title generation: extract first ~30 chars of first user message, strip
  punctuation, title-case. No LLM call needed (keep it simple and fast).
  Example: "Refactor auth module to use JWT" → "Refactor auth module"
- Hook into session monitor: fire after first `AssistantMessage` event
- Use Telegram's `edit_forum_topic()` API (same infrastructure as emoji rename)
- Track `_auto_named: set[str]` (window_ids) to prevent repeated renames
- Alternative: use session summary from JSONL `type: "summary"` entries
  once Claude generates one (usually after a few messages)

## Constraints

- Requires bot admin with "Manage Topics" permission
- Title ≤ 255 chars (Telegram limit), target ≤ 30 for readability
- Opt-in only — some users prefer manual naming
- Must not conflict with manual renames (no polling/overriding after first set)
