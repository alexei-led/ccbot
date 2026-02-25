---
id: REQ-018
title: Session Transcript Export
type: feature
status: open
priority: low
discovered_by: marvin
discovered_date: 2026-07-10
agent_recommendation: ""
---

# REQ-018: Session Transcript Export

## Motivation

After a productive session with an agent, users often want to share the
conversation, archive it, or review it in a better format than paginated
Telegram messages. Currently there's no way to export a session.

## Success Criteria

1. `/export` command in a bound topic
2. Renders the full session as a Markdown document:
   - Header: project path, session date, provider
   - Each message: role (👤 User / 🤖 Assistant), timestamp, content
   - Tool calls shown as collapsible code blocks
   - Thinking sections marked as `> *Thinking...*` blockquotes
3. Sends the Markdown file as a Telegram document attachment
4. File named: `ccbot-export-<project>-<date>.md`
5. File size limit: if > 10 MB, truncate to last N messages and note truncation
6. Works for all providers (Claude JSONL, Codex JSONL, Gemini JSON)

## Optional / Stretch

- `/export html` variant: styled HTML with syntax highlighting
- `/export pdf` via pandoc (if available on host)

## Implementation Notes

- Reuse `session_manager.get_recent_messages()` for data fetch
- Markdown rendering: simple f-string template (no external renderer)
- Send via `bot.send_document(chat_id, InputFile(BytesIO(content), filename=...))`
- `python-telegram-bot` InputFile accepts in-memory bytes (no temp file needed)
- New handler in `bot.py`: `CommandHandler("export", export_handler)`

## Constraints

- Telegram document size limit: 50 MB (well within any realistic session)
- Must not stream or block the event loop on large files (read async, build sync)
- Export is read-only — no state changes
