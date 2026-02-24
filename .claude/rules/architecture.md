# System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Telegram Bot (bot.py)                       │
│  - Topic-based routing: 1 topic = 1 window = 1 session             │
│  - /history: Paginated message history (default: latest page)      │
│  - /sessions: Dashboard with per-session Kill buttons              │
│  - Status messages: inline [Esc] and [Screenshot] buttons          │
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
│  terminal_parser.py + screen_buffer.py                              │
│  - ScreenBuffer: pyte VT100 emulator for clean line rendering      │
│  - Detect interactive UIs (AskUserQuestion, ExitPlanMode, etc.)    │
│  - Parse status line (Unicode-resilient spinner + working text)    │
│  - Adaptive separator/chrome detection (no hardcoded line counts)  │
└──────────┬──────────────────────────────────────────────────────────┘
           │                              │
           │ Notify (NewMessage callback) │ Send (tmux keys)
           │                              │
┌──────────┴──────────────┐    ┌──────────┴──────────────────────┐
│  SessionMonitor         │    │  TmuxManager (tmux_manager.py)  │
│  (session_monitor.py)   │    │  - list/find/create/kill windows│
│  - Poll JSONL every 2s  │    │  - send_keys to pane            │
│  - Detect mtime changes │    │  - capture_pane for screenshot  │
│                         │    │  - capture_pane_raw (with ANSI) │
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

Provider modules (providers/):
  base.py             ─ AgentProvider protocol, ProviderCapabilities, event types
  registry.py         ─ ProviderRegistry (name→factory map, singleton cache)
  _jsonl.py           ─ Shared JSONL parsing base class for Codex + Gemini
  claude.py           ─ ClaudeProvider (hook, resume, continue, JSONL transcripts)
  codex.py            ─ CodexProvider (resume, continue, JSONL transcripts, no hook)
  gemini.py           ─ GeminiProvider (resume, continue, whole-file JSON transcripts, no hook)
  __init__.py         ─ get_provider_for_window(), detect_provider_from_command(), get_provider() fallback

Additional modules:
  cli.py              ─ Click-based CLI entry point (run subcommand + all bot-config flags)
  config.py           ─ Application configuration singleton (env vars, .env files, defaults)
  doctor_cmd.py       ─ ccbot doctor [--fix] — validate setup without bot token
  status_cmd.py       ─ ccbot status — show running state without bot token
  screen_buffer.py    ─ pyte VT100 screen buffer (ANSI→clean lines, separator detection)
  cc_commands.py      ─ CC command discovery (skills, custom commands) + menu registration
  screenshot.py       ─ Terminal text → PNG rendering (ANSI color, font fallback)
  main.py             ─ Application entry point (Click dispatcher, run_bot bootstrap)
  utils.py            ─ Shared utilities (ccbot_dir, tmux_session_name, atomic_write_json)

Handler modules (handlers/):
  text_handler.py        ─ Text message routing (UI guards → unbound → dead → forward)
  message_sender.py      ─ safe_reply/safe_edit/safe_send + rate_limit_send
  message_queue.py       ─ Per-user queue + worker (merge, status dedup)
  status_polling.py      ─ Background status line polling (1s interval, auto-close logic)
  response_builder.py    ─ Response pagination and formatting
  interactive_ui.py      ─ AskUserQuestion / ExitPlanMode / Permission UI rendering
  interactive_callbacks.py ─ Callbacks for interactive UI (arrow keys, enter, esc)
  directory_browser.py   ─ Directory selection UI for new topics
  directory_callbacks.py ─ Callbacks for directory browser (navigate, confirm, provider pick)
  window_callbacks.py    ─ Window picker callbacks (bind, new, cancel)
  recovery_callbacks.py  ─ Dead window recovery callbacks (fresh, continue, resume)
  screenshot_callbacks.py ─ Screenshot refresh, Esc, quick-key callbacks
  history.py             ─ Message history display with pagination
  history_callbacks.py   ─ History pagination callbacks (prev/next)
  sessions_dashboard.py  ─ /sessions command: active session overview + kill
  resume_command.py      ─ /resume command: scan past sessions, paginated picker
  upgrade.py             ─ /upgrade command: uv tool upgrade + process restart
  file_handler.py        ─ Photo/document handler (save to .ccbot-uploads/, notify agent)
  command_history.py     ─ Per-user/per-topic in-memory command recall (max 20)
  topic_emoji.py         ─ Topic name emoji updates (active/idle/done/dead), debounced
  cleanup.py             ─ Centralized topic state cleanup on close/delete
  callback_data.py       ─ CB_* callback data constants for inline keyboard routing
  callback_helpers.py    ─ Shared helpers (user_owns_window, get_thread_id)
  user_state.py          ─ context.user_data string key constants

State files (~/.ccbot/ or $CCBOT_DIR/):
  state.json         ─ thread bindings + window states + display names + read offsets
  session_map.json   ─ hook-generated window_id→session mapping
  monitor_state.json ─ poll progress (byte offset) per JSONL file
```

## Key Design Decisions

- **Topic-centric** — Each Telegram topic binds to one tmux window. No centralized session list; topics _are_ the session list.
- **Window ID-centric** — All internal state keyed by tmux window ID (e.g. `@0`, `@12`), not window names. Window IDs are guaranteed unique within a tmux server session. Window names are kept as display names via `window_display_names` map. Same directory can have multiple windows.
- **Hook-based session tracking** — Claude Code `SessionStart` hook writes `session_map.json`; monitor reads it each poll cycle to auto-detect session changes.
- **Tool use ↔ tool result pairing** — `tool_use_id` tracked across poll cycles; tool result edits the original tool_use Telegram message in-place.
- **MarkdownV2 with fallback** — All messages go through `safe_reply`/`safe_edit`/`safe_send` which convert via `telegramify-markdown` and fall back to plain text on parse failure.
- **No truncation at parse layer** — Full content preserved; splitting at send layer respects Telegram's 4096 char limit with expandable quote atomicity.
- Only sessions registered in `session_map.json` (via hook) are monitored.
- Notifications delivered to users via thread bindings (topic → window_id → session).
- **Startup re-resolution** — Window IDs reset on tmux server restart. On startup, `resolve_stale_ids()` matches persisted display names against live windows to re-map IDs. Old state.json files keyed by window name are auto-migrated.
- **Per-window provider** — All CLI-specific behavior (launch args, transcript parsing, terminal status, command discovery) is delegated to an `AgentProvider` protocol. Providers declare capabilities (`ProviderCapabilities`) that gate UX features per-window: hook checks, resume/continue buttons, and command registration. Each window stores its `provider_name` in `WindowState`; `get_provider_for_window(window_id)` resolves the correct provider instance, falling back to the config default. Externally created windows are auto-detected via `detect_provider_from_command(pane_current_command)`. The global `get_provider()` singleton remains for CLI commands (`doctor`, `status`) that lack window context.
