# CCBot Ticket Review — Agent Instructions

You are reviewing open tickets for the **CCBot** project.

CCBot is a Telegram→tmux bridge for controlling AI coding agents (Claude Code,
Codex, Gemini) from a phone. Tech stack: Python 3.14, python-telegram-bot,
asyncio, uv.

## Your Task

1. Read all files matching `~/workspace/ccbot/.spec/reqs/REQ-*.md`
2. For each ticket with `status: open`, analyze it and decide:
   - **IMPLEMENT** — do it, pick the tool (claude-code / codex / ralphex)
   - **DEFER** — good idea, but not now (explain why)
   - **REJECT** — not worth doing (explain why)
3. For IMPLEMENT decisions, also estimate: effort (small/medium/large) and
   which agent is best suited:
   - `claude-code`: small focused tasks (unit tests, simple fixes, single file)
   - `codex`: architecture planning, complex refactors, multi-file reasoning
   - `ralphex`: large autonomous multi-step work (multi-file, multiple tasks)

## Decision Criteria

- **Bugs**: Implement unless the bug is theoretical/edge-case with no user impact
- **Features**: Consider user value, implementation complexity, and fit with
  CCBot's philosophy (thin tmux layer, mobile-first, no SDK dependencies)
- **Priority**: `high` > `medium` > `low` (but not absolute)
- **Effort vs value**: a low-effort high-value feature beats high-priority
  low-value work

## After Analysis

Post your review summary to the CCBot Telegram topic.

Format:
```
📋 CCBot Ticket Review — {date}

🐛 Bugs:
• REQ-XXX [title]: IMPLEMENT (claude-code, small) / DEFER / REJECT — reason

✨ Features:
• REQ-XXX [title]: IMPLEMENT (ralphex, large) / DEFER / REJECT — reason

🎯 Recommended Next Action:
[Single most valuable ticket to work on next, with specific reason]
```

Keep it concise. This is a status update, not a novel.

## Tool Usage

Use `read` tool to read ticket files from `~/workspace/ccbot/.spec/reqs/`.
Do not modify any files — read-only analysis only.
