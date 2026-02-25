---
id: REQ-013
title: History Search Command
type: feature
status: open
priority: medium
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-013: History Search Command

## Motivation

`/history` currently lists messages in paginated form (newest first). On long
sessions, finding a specific exchange requires many button taps. A `/search`
command would let users find relevant content instantly.

## Success Criteria

1. `/search <query>` command available in bound topics
2. Performs case-insensitive substring search across the current session's
   JSONL transcript (user + assistant messages)
3. Returns up to 5 matching excerpts, each showing:
   - Role emoji (👤/🤖)
   - Timestamp
   - ±50 chars context around the match (highlighted with `**bold**`)
   - Match index out of total (e.g. `[2/7]`)
4. Inline navigation buttons if more than 5 matches: `[◀ Prev]` `[▶ Next]`
5. `/search` with no query shows the last 3 user messages (quick recap)
6. Works for all providers

## Implementation Notes

- Reuse `session_manager.get_recent_messages()` for data access
- Highlighting: wrap matched text in MarkdownV2 bold; escape surrounding chars
- Callback data: `hs:next:<query_hash>:<page>` and `hs:prev:...`
- Query hash: first 6 chars of SHA1(query) to keep callback under 64 bytes
- Store (query, results) in `context.user_data` keyed by query_hash for paging
- TTL: clear stale search state after 5 minutes or on new message

## Constraints

- Search is in-memory over already-read messages (no grep of file directly)
- Results capped at 20 total matches to limit memory usage
- Must not block event loop (read is already async)
