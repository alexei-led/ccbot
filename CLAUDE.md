# CLAUDE.md

## Development Principles

### No Message Truncation

Historical messages (tool_use summaries, tool_result text, user/assistant messages) are always kept in full — no character-level truncation at the parsing layer. Long text is handled exclusively at the send layer: `split_message` splits by Telegram's 4096-character limit; real-time messages get `[1/N]` text suffixes, history pages get inline keyboard navigation.

### History Pagination Shows Latest First

`/history` defaults to the last page (newest messages). Users browse older content via the "◀ Older" button.

### Follow Telegram Bot Best Practices

Interaction design follows Telegram Bot platform best practices: prefer inline keyboards over reply keyboards; use `edit_message_text` for in-place updates instead of sending new messages; keep callback data compact (64-byte limit); use `answer_callback_query` for instant feedback.

### File Header Docstring Convention

Every Python source file must start with a module-level docstring (`"""..."""`) describing its core purpose. Requirements:

- **Purpose clear within 10 lines**: An AI or developer reading only the first 10 lines can determine the file's role, responsibilities, and key classes/functions.
- **Structure**: First line is a one-sentence summary; subsequent lines describe core responsibilities, key components (class/function names), and relationships with other modules.
- **Keep updated**: When a file undergoes major changes (adding/removing core features, changing module responsibilities, renaming key classes/functions), update the header docstring. Minor bug fixes or internal refactors do not require updates.

### Code Quality Checks

After every code change, run `pyright src/ccbot/` to check for type errors. Ensure 0 errors before committing.

### Unified MarkdownV2 Formatting

All messages sent to Telegram use `parse_mode="MarkdownV2"`. The `telegramify-markdown` library converts standard Markdown to Telegram MarkdownV2 format. Handler code should use `safe_reply`/`safe_edit`/`safe_send` helper functions, which handle MarkdownV2 conversion automatically and fall back to plain text on parse failure. Internal queue/UI code (`message_queue.py`, `interactive_ui.py`) calls `bot.send_message`/`bot.edit_message_text` directly with its own MarkdownV2 fallback for fine-grained control over send sequencing.

### Window as the Core Unit

All logic (message sending, history viewing, notifications) operates on tmux windows as the core unit, not project directories (cwd). Window names default to the directory name (e.g., `project`). The same directory can have multiple windows (auto-suffixed, e.g., `project-2`), each independently associated with its own Claude session.

### Topic-Only Architecture (No Backward Compatibility)

The bot operates exclusively in Telegram Forum (topics) mode. There is **no** `active_sessions` mapping, **no** `/list` command, **no** General topic routing, and **no** backward-compatibility logic for older non-topic modes. Every code path assumes named topics.

**1 Topic = 1 Window = 1 Session.** Each Telegram topic maps to exactly one tmux window.

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  Topic ID   │ ───▶ │ Window Name │ ───▶ │ Session ID  │
│  (Telegram) │      │   (tmux)    │      │  (Claude)   │
└─────────────┘      └─────────────┘      └─────────────┘
     thread_bindings      session_map.json
     (state.json)         (written by hook)
```

**Mapping 1: Topic → Window (thread_bindings)**

```python
# session.py: SessionManager
thread_bindings: dict[int, dict[int, str]]  # user_id → {thread_id → window_name}
```

- Storage: memory + `~/.ccbot/state.json`
- Written when: user creates a new session via the directory browser in a topic
- Purpose: route user messages to the correct tmux window

**Mapping 2: Window → Session (session_map.json)**

```python
# session_map.json (key format: "tmux_session:window_name")
{
  "ccbot:project": {"session_id": "uuid-xxx", "cwd": "/path/to/project"},
  "ccbot:project-2": {"session_id": "uuid-yyy", "cwd": "/path/to/project"}
}
```

- Storage: `~/.ccbot/session_map.json`
- Written when: Claude Code's `SessionStart` hook fires
- Property: one window maps to one session; session_id changes after `/clear`
- Purpose: SessionMonitor uses this mapping to decide which sessions to watch

**Outbound message flow**

```
User sends "hello" in topic (thread_id=42)
    │
    ▼
thread_bindings[user_id][42] → "project"  (get bound window)
    │
    ▼
send_to_window("project", "hello")        (send to tmux)
```

**Inbound message flow**

```
SessionMonitor reads new message (session_id = "uuid-xxx")
    │
    ▼
Iterate thread_bindings, find (user, thread) whose window maps to this session
    │
    ▼
Deliver message to user in the correct topic (thread_id)
```

**New topic flow**: First message in an unbound topic → directory browser → select directory → create window → bind topic → forward pending message.

**Topic lifecycle**: Closing (or deleting) a topic auto-kills the associated tmux window and unbinds the thread. Stale bindings (window deleted externally) are cleaned up by the status polling loop.

### Telegram Flood Control Protection

The bot implements send rate limiting to avoid triggering Telegram's flood control:
- Minimum 1.1-second interval between messages per user
- Status polling interval is 1 second (send layer has rate limiting protection)
- Automated outbound messages (queue worker, status updates) go through `rate_limit_send()` which checks and waits

### Message Queue Architecture

The bot uses per-user message queues + worker pattern for all send tasks, ensuring:
- Messages are sent in receive order (FIFO)
- Status messages always follow content messages
- Multi-user concurrent processing without interference

**Message merging**: The worker automatically merges consecutive mergeable content messages on dequeue, reducing API calls:
- Content messages for the same window can be merged (including text, thinking)
- tool_use breaks the merge chain and is sent separately (message ID recorded for later editing)
- tool_result breaks the merge chain and is edited into the tool_use message (preventing order confusion)
- Merging stops when combined length exceeds 3800 characters (to avoid pagination)

### Status Message Handling

Status messages (Claude status line) use special handling to optimize user experience:

**Conversion**: The status message is edited into the first content message, reducing message count:
- When a status message exists, the first content message updates it via edit
- Subsequent content messages are sent as new messages

**Polling**: A background task polls terminal status for all active windows at 1-second intervals. Send-layer rate limiting ensures flood control is not triggered.

### Session Lifecycle Management

Session monitor tracks window → session_id mappings via `session_map.json` (written by hook):

**Startup cleanup**: On bot startup, all tracked sessions not present in session_map are cleaned up, preventing monitoring of closed sessions.

**Runtime change detection**: Each polling cycle checks for session_map changes:
- Window's session_id changed (e.g., after `/clear`) → clean up old session
- Window deleted → clean up corresponding session

### Performance Optimizations

**mtime cache**: The monitoring loop maintains an in-memory file mtime cache, skipping reads for unchanged files.

**Byte offset incremental reads**: Each tracked session records `last_byte_offset`, reading only new content. File truncation (offset > file_size) is detected and offset is auto-reset.

**Status deduplication**: The worker compares `last_text` when processing status updates; identical content skips the edit, reducing API calls.

### Service Restart

To restart the ccbot service after code changes, run `./scripts/restart.sh`. The script detects whether a running `uv run ccbot` process exists in the `__main__` window of tmux session `ccbot`, sends Ctrl-C to stop it, restarts, and outputs startup logs for confirmation.

### Hook Configuration

Auto-install: `ccbot hook --install`

Or manually configure in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [{ "type": "command", "command": "ccbot hook", "timeout": 5 }]
      }
    ]
  }
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Telegram Bot (bot.py)                       │
│  - Topic-based routing: 1 topic = 1 window = 1 session             │
│  - /history: Paginated message history (default: latest page)      │
│  - /screenshot: Capture tmux pane as PNG                           │
│  - /esc: Send Escape to interrupt Claude                           │
│  - Send text → Claude Code via tmux keystrokes                     │
│  - Forward /commands to Claude Code                                │
│  - Create sessions via directory browser in unbound topics         │
│  - Tool use → tool result: edit message in-place                   │
│  - Interactive UI: AskUserQuestion / ExitPlanMode / Permission     │
│  - Per-user message queue + worker (merge, rate limit)             │
│  - MarkdownV2 output with auto fallback to plain text              │
├──────────────────────┬──────────────────────────────────────────────┤
│  markdown_v2.py      │  telegram_sender.py                         │
│  MD → MarkdownV2     │  split_message (4096 limit)                 │
│  + expandable quotes │                                             │
├──────────────────────┴──────────────────────────────────────────────┤
│  terminal_parser.py                                                 │
│  - Detect interactive UIs (AskUserQuestion, ExitPlanMode, etc.)    │
│  - Parse status line (spinner + working text)                      │
└──────────┬──────────────────────────────┬───────────────────────────┘
           │                              │
           │ Notify (NewMessage callback) │ Send (tmux keys)
           │                              │
┌──────────┴──────────────┐    ┌──────────┴──────────────────────┐
│  SessionMonitor         │    │  TmuxManager (tmux_manager.py)  │
│  (session_monitor.py)   │    │  - list/find/create/kill windows│
│  - Poll JSONL every 2s  │    │  - send_keys to pane            │
│  - Detect mtime changes │    │  - capture_pane for screenshot  │
│  - Parse new lines      │    └──────────────┬─────────────────┘
│  - Track pending tools  │                   │
│    across poll cycles   │                   │
└──────────┬──────────────┘                   │
           │                                  │
           ▼                                  ▼
┌────────────────────────┐         ┌─────────────────────────┐
│  TranscriptParser      │         │  Tmux Windows           │
│  (transcript_parser.py)│         │  - Claude Code process  │
│  - Parse JSONL entries │         │  - One window per       │
│  - Pair tool_use ↔     │         │    topic/session        │
│    tool_result         │         └────────────┬────────────┘
│  - Format expandable   │                      │
│    quotes for thinking │              SessionStart hook
│  - Extract history     │                      │
└────────────────────────┘                      ▼
                                    ┌────────────────────────┐
┌────────────────────────┐         │  Hook (hook.py)        │
│  SessionManager        │◄────────│  - Receive hook stdin  │
│  (session.py)          │  reads  │  - Write session_map   │
│  - Window ↔ Session    │  map    │    .json               │
│    resolution          │         └────────────────────────┘
│  - Thread bindings     │
│    (topic → window)    │         ┌────────────────────────┐
│  - Message history     │────────►│  Claude Sessions       │
│    retrieval           │  reads  │  ~/.claude/projects/   │
└────────────────────────┘  JSONL  │  - sessions-index      │
                                   │  - *.jsonl files       │
┌────────────────────────┐         └────────────────────────┘
│  MonitorState          │
│  (monitor_state.py)    │
│  - Track byte offset   │
│  - Prevent duplicates  │
│    after restart       │
└────────────────────────┘

State files (~/.ccbot/):
  state.json         ─ thread bindings + window states + read offsets
  session_map.json   ─ hook-generated window→session mapping
  monitor_state.json ─ poll progress (byte offset) per JSONL file
```

**Key design decisions:**
- **Topic-centric** — Each Telegram topic binds to one tmux window. No centralized session list; topics *are* the session list.
- **Window-centric** — All state anchored to tmux window names (e.g. `myproject`), not directories. Same directory can have multiple windows (auto-suffixed: `myproject-2`).
- **Hook-based session tracking** — Claude Code `SessionStart` hook writes `session_map.json`; monitor reads it each poll cycle to auto-detect session changes.
- **Tool use ↔ tool result pairing** — `tool_use_id` tracked across poll cycles; tool result edits the original tool_use Telegram message in-place.
- **MarkdownV2 with fallback** — All messages go through `safe_reply`/`safe_edit`/`safe_send` which convert via `telegramify-markdown` and fall back to plain text on parse failure.
- **No truncation at parse layer** — Full content preserved; splitting at send layer respects Telegram's 4096 char limit with expandable quote atomicity.
- Only sessions registered in `session_map.json` (via hook) are monitored
- Notifications delivered to users via thread bindings (topic → window → session)
