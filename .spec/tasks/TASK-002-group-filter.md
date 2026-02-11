---
id: TASK-002
title: Add group filter to all handlers
status: todo
req: REQ-001
epic: EPIC-001
depends: [TASK-001]
---

# TASK-002: Add group filter to all handlers

Add `_is_my_group()` check as earliest filter in every handler.

## Implementation Steps

1. Add helper function in `bot.py` (or a small utility):
   ```python
   def _is_my_group(update: Update) -> bool:
       if not config.group_id:
           return True
       chat_id = update.effective_chat.id if update.effective_chat else None
       return chat_id == config.group_id
   ```
2. Add `if not _is_my_group(update): return` as first line in:
   - `text_handler`
   - `start_command` (will become `new_command`)
   - `history_command`
   - `screenshot_command`
   - `esc_command`
   - `kill_command`
   - `forward_command_handler`
   - `callback_handler`
   - `topic_closed_handler`
   - `unsupported_content_handler`
3. Alternative: use `python-telegram-bot` filter in handler registration (cleaner)

## Acceptance Criteria

- With `CCBOT_GROUP_ID` set: only updates from that group are processed
- With `CCBOT_GROUP_ID` unset: all updates processed (backward compat)
- Updates from other groups silently ignored (no error, no log spam)
- Tests verify both filtering and pass-through modes
