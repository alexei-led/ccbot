# System Architecture

```mermaid
graph TB
    subgraph bot["Telegram Bot — bot.py + handlers/"]
        direction TB
        BotCore["Command handlers · handler registration\ncallback_registry · topic_orchestration\ncommand_orchestration · polling_coordinator"]
        BotSub1["entity_formatting.py\nMD → plain text + MessageEntity offsets"]
        BotSub2["telegram_sender.py\nsplit_message — 4096 limit"]
        BotSub3["message_queue.py · message_sender.py\nPer-user queue + worker · rate limiting"]
        Terminal["terminal_parser.py + screen_buffer.py\npyte VT100 · interactive UI detection\nspinner parsing · separator detection"]
    end

    subgraph monitor["SessionMonitor — session_monitor.py"]
        Mon["Poll JSONL every 2s · mtime cache\nParse new lines · track pending tools\nRead events.jsonl incrementally"]
    end

    subgraph tmux["TmuxManager — tmux_manager.py"]
        Tmux["list/find/create/kill windows\nsend_keys · capture_pane\nlist_panes · send_keys_to_pane"]
    end

    subgraph parsing["TranscriptParser — transcript_parser.py"]
        TP["Parse JSONL · pair tool_use ↔ tool_result\nExpandable quotes for thinking · history"]
    end

    subgraph windows["Tmux Windows"]
        Win["One window per topic/session\nClaude Code · Codex · Gemini · Pi"]
    end

    subgraph hook["Hook — hook.py"]
        Hook["Receive hook stdin\nWrite session_map.json\nWrite events.jsonl"]
    end

    subgraph session["SessionManager + ThreadRouter"]
        SM["Window ↔ Session resolution\nThread bindings · message history"]
    end

    subgraph state["State Files — ~/.ccgram/"]
        MonState["MonitorState\nbyte offsets per session"]
        Sessions["Claude Sessions\n~/.claude/projects/\nsessions-index + *.jsonl"]
    end

    bot -- "Notify\n(NewMessage callback)" --> monitor
    bot -- "Send\n(tmux keys)" --> tmux
    monitor --> parsing
    tmux --> windows
    windows -- "Claude Code hooks\n(hook events)" --> hook
    hook -- "session_map.json\n+ events.jsonl" --> session
    session -- "reads JSONL" --> Sessions
    monitor -- "reads" --> MonState

    style bot fill:#e8f4fd,stroke:#0088cc,stroke-width:2px,color:#333
    style monitor fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#333
    style tmux fill:#f0faf0,stroke:#2ea44f,stroke-width:2px,color:#333
    style parsing fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#333
    style windows fill:#f0faf0,stroke:#2ea44f,stroke-width:2px,color:#333
    style hook fill:#fce4ec,stroke:#c62828,stroke-width:2px,color:#333
    style session fill:#e8eaf6,stroke:#283593,stroke-width:2px,color:#333
    style state fill:#f5f5f5,stroke:#616161,stroke-width:2px,color:#333
```

## Module Inventory

### Provider modules (`providers/`)

| Module                 | Description                                                                                                    |
| ---------------------- | -------------------------------------------------------------------------------------------------------------- |
| `base.py`              | AgentProvider protocol, ProviderCapabilities, event types                                                      |
| `registry.py`          | ProviderRegistry (name→factory map, singleton cache)                                                           |
| `_jsonl.py`            | Shared JSONL parsing base class for Codex + Gemini + Pi                                                        |
| `claude.py`            | ClaudeProvider (hook, resume, continue, JSONL transcripts)                                                     |
| `codex.py`             | CodexProvider (resume, continue, JSONL transcripts, no hook)                                                   |
| `gemini.py`            | GeminiProvider (resume, continue, whole-file JSON transcripts, no hook)                                        |
| `pi.py`                | PiProvider (resume via `--session`, continue, JSONL v3 transcripts, no hook)                                   |
| `pi_format.py`         | Pi transcript parsers (user/assistant/toolResult/bashExecution, session header, pending-tool tracking)         |
| `pi_discovery.py`      | Pi command discovery (Telegram-safe builtins + skills + prompts + extension `pi.registerCommand` scans)        |
| `codex_status.py`      | Codex status snapshot builder (transcript parsing, activity detection)                                         |
| `codex_format.py`      | Codex interactive prompt formatter (permission/tool prompts)                                                   |
| `shell.py`             | Slim ShellProvider class (re-exports infrastructure from shell_infra for backward compat)                      |
| `shell_infra.py`       | Shell prompt-marker detection, KNOWN_SHELLS, PromptMatch, setup_shell_prompt — extracted from shell.py         |
| `process_detection.py` | Foreground process detection via `ps -t <tty>` with PGID caching for reliable provider identification          |
| `__init__.py`          | `get_provider_for_window()`, `detect_provider_from_pane()`, `detect_provider_from_command()`, `get_provider()` |

### LLM modules (`llm/`)

| Module               | Description                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| `base.py`            | CommandGenerator + TextCompleter Protocols, CommandResult dataclass                               |
| `httpx_completer.py` | OpenAI-compatible + Anthropic completions via httpx (command gen + generic `complete()`)          |
| `summarizer.py`      | LLM-powered completion summary — reads transcript, produces single-line summary for Ready message |
| `__init__.py`        | LLM provider registry + `get_completer()` / `get_text_completer()` factories                      |

### Whisper modules (`whisper/`)

| Module                 | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `base.py`              | WhisperTranscriber Protocol + TranscriptionResult dataclass   |
| `httpx_transcriber.py` | OpenAI-compatible transcription via httpx (OpenAI, Groq, etc) |
| `__init__.py`          | Provider factory (`get_transcriber()` from config)            |

### Core modules (`src/ccgram/`)

| Module                    | Description                                                                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `cc_commands.py`          | CC command discovery (skills, custom commands) + menu registration                                                                               |
| `command_catalog.py`      | Provider-agnostic command discovery and caching — separates command-source from menu registration                                                |
| `claude_task_state.py`    | Claude task tracking from transcripts — per-window task snapshots for live status bubble                                                         |
| `cli.py`                  | Click-based CLI entry point (run subcommand + all bot-config flags)                                                                              |
| `config.py`               | Application configuration singleton (env vars, .env files, defaults)                                                                             |
| `doctor_cmd.py`           | `ccgram doctor [--fix]` — validate setup without bot token                                                                                       |
| `mailbox.py`              | File-based mailbox: message CRUD, TTL expiration, sweep, ID migration, broadcast                                                                 |
| `monitor_state.py`        | Monitor state persistence — tracks byte offsets for each session                                                                                 |
| `main.py`                 | Application entry point (Click dispatcher, run_bot bootstrap)                                                                                    |
| `msg_cmd.py`              | `ccgram msg` CLI group: send, inbox, read, reply, broadcast, register, spawn                                                                     |
| `msg_discovery.py`        | Peer discovery: view over SessionManager + self-declared overlay (task, team)                                                                    |
| `msg_skill.py`            | Messaging skill auto-installation for Claude Code agents                                                                                         |
| `screen_buffer.py`        | pyte VT100 screen buffer (ANSI→clean lines, separator detection)                                                                                 |
| `screenshot.py`           | Terminal text → PNG rendering (ANSI color, font fallback)                                                                                        |
| `session_map.py`          | Session map I/O — reads/writes session_map.json, synchronises window states against hook data                                                    |
| `session_query.py`        | Read-only session resolution free functions — wraps `session_resolver` so handlers don't import `SessionManager`                                 |
| `session_resolver.py`     | JSONL session resolution — window-to-session lookup and message history extraction                                                               |
| `spawn_request.py`        | Spawn request data types, file-based CRUD, public accessor API (get/pop/iter/register_pending)                                                   |
| `state_persistence.py`    | Atomic/debounced JSON persistence for state.json                                                                                                 |
| `status_cmd.py`           | `ccgram status` — show running state without bot token                                                                                           |
| `telegram_request.py`     | Telegram request helpers for resilient long polling (custom HTTPX transport)                                                                     |
| `thread_router.py`        | ThreadRouter — thread bindings, display names, reverse index, chat ID resolution                                                                 |
| `toolbar_config.py`       | Toolbar layout configuration — per-provider button grids loaded from TOML                                                                        |
| `topic_state_registry.py` | Centralized registry for per-topic and per-window cleanup functions with self-registration decorator and `register_bound()` for instance methods |
| `user_preferences.py`     | User directory favorites (starred/MRU) and per-user read offsets (extracted from SessionManager)                                                 |
| `utils.py`                | Shared utilities (ccgram_dir, tmux_session_name, atomic_write_json)                                                                              |
| `window_query.py`         | Read-only window state free functions — lets handlers read window state without importing `SessionManager`                                       |
| `window_resolver.py`      | Window ID resolution, format helpers, and startup migration                                                                                      |
| `window_state_store.py`   | Window state storage — WindowState dataclass, per-window mode settings (approval, batch, notification)                                           |
| `window_view.py`          | Read-only WindowView projection — frozen snapshot used by handlers that only need to read window state                                           |
| `expandable_quote.py`     | Sentinel constants and `format_expandable_quote()` — markup contract between transcript parsers and presentation                                 |

### Handler modules (`handlers/`)

| Module                         | Description                                                                                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `callback_data.py`             | CB\_\* callback data constants for inline keyboard routing                                                                                                                          |
| `callback_helpers.py`          | Shared helpers (user_owns_window, get_thread_id)                                                                                                                                    |
| `callback_registry.py`         | Prefix-based callback dispatch registry with self-registration decorator                                                                                                            |
| `cleanup.py`                   | Topic teardown orchestration via TopicStateRegistry + async bot cleanup                                                                                                             |
| `command_history.py`           | Per-user/per-topic in-memory command recall (max 20)                                                                                                                                |
| `command_orchestration.py`     | Forward command handler, provider menu cache, status snapshot delegation                                                                                                            |
| `directory_browser.py`         | Directory selection UI for new topics                                                                                                                                               |
| `directory_callbacks.py`       | Callbacks for directory browser (navigate, confirm, provider pick)                                                                                                                  |
| `file_handler.py`              | Photo/document handler (save to .ccgram-uploads/, notify agent)                                                                                                                     |
| `history.py`                   | Message history display with pagination                                                                                                                                             |
| `history_callbacks.py`         | History pagination callbacks (prev/next)                                                                                                                                            |
| `hook_events.py`               | Hook event dispatcher (Stop, StopFailure, SessionEnd, Notification, Subagent*, Team*)                                                                                               |
| `interactive_callbacks.py`     | Callbacks for interactive UI (arrow keys, enter, esc)                                                                                                                               |
| `interactive_ui.py`            | AskUserQuestion / ExitPlanMode / Permission UI rendering                                                                                                                            |
| `live_view.py`                 | Live terminal view — auto-refreshing screenshot via editMessageMedia, content-hash gating, auto-stop                                                                                |
| `message_queue.py`             | Per-user FIFO queue + worker — merge, status dedup, tool-use batching delegation                                                                                                    |
| `message_routing.py`           | Inbound message routing — routes new assistant messages from SessionMonitor to Telegram topics                                                                                      |
| `message_sender.py`            | safe_reply/safe_edit/safe_send + rate_limit_send                                                                                                                                    |
| `message_task.py`              | Message task sum type — frozen dataclasses (ContentTask, StatusTask, ToolResultTask) shared by queue, tool_batch, and status_bubble without circular imports                        |
| `msg_broker.py`                | Broker delivery: idle detection, send_keys injection, rate limiting, loop detection                                                                                                 |
| `msg_delivery.py`              | Message delivery state: per-window tracking, rate limiting, loop detection (extracted from msg_broker)                                                                              |
| `msg_spawn.py`                 | Agent spawn requests with Telegram approval flow and auto-topic creation                                                                                                            |
| `msg_telegram.py`              | Telegram notifications for inter-agent messages (silent, grouped, edit-in-place)                                                                                                    |
| `periodic_tasks.py`            | Periodic task orchestration: broker delivery, mailbox sweep, spawn processing, lifecycle, live view                                                                                 |
| `polling_coordinator.py`       | Polling coordinator — iterates thread bindings, delegates per-window work to window_tick, runs periodic/lifecycle tasks                                                             |
| `polling_strategies.py`        | Polling strategy classes: TerminalScreenBuffer, TerminalPollState, InteractiveUIStrategy, TopicLifecycleStrategy — decomposed from monolithic polling                               |
| `window_tick.py`               | Per-window poll cycle — dead-window detection, transcript discovery, interactive UI, status updates, multi-pane scanning, passive shell relay                                       |
| `recovery_callbacks.py`        | Dead window recovery callbacks (fresh, continue, resume)                                                                                                                            |
| `response_builder.py`          | Response pagination and formatting                                                                                                                                                  |
| `restore_command.py`           | /restore command: recover dead topics via recovery keyboard                                                                                                                         |
| `resume_command.py`            | /resume command: scan past sessions, paginated picker                                                                                                                               |
| `screenshot_callbacks.py`      | Screenshot callback handlers — screenshot capture, quick-key, live view toggle                                                                                                      |
| `send_callbacks.py`            | Callback handlers for /send file browser navigation                                                                                                                                 |
| `send_command.py`              | File search, listing and upload utilities for the /send command                                                                                                                     |
| `send_security.py`             | Security validation for the /send command — multi-layer access control                                                                                                              |
| `sessions_dashboard.py`        | /sessions command: active session overview + kill                                                                                                                                   |
| `shell_capture.py`             | Prompt-marker output isolation, exit code detection, baseline-diff fallback, glyph stripping                                                                                        |
| `shell_commands.py`            | NL→command approval, dangerous command detection via LLM                                                                                                                            |
| `shell_context.py`             | Shared shell helpers — `gather_llm_context`, `redact_for_llm`, `_detect_shell_tools` (extracted to break shell_commands ↔ shell_capture coupling)                                   |
| `shell_prompt_orchestrator.py` | Shell prompt marker setup orchestrator — centralizes five trigger sites into one ensure_setup entry point                                                                           |
| `status_bubble.py`             | Status-bubble keyboard + status message lifecycle (send, edit, clear, format, dedup) — owns `_status_msg_info`, `send_status_text`, `clear_status_message`, `build_status_keyboard` |
| `status_bar_actions.py`        | Status-bubble button callbacks (notify toggle, recall, remote control, esc, keys) — extracted from screenshot_callbacks                                                             |
| `sync_command.py`              | /sync command: sync window state with tmux                                                                                                                                          |
| `text_handler.py`              | Text message routing (UI guards → unbound → dead → forward)                                                                                                                         |
| `tool_batch.py`                | Claude tool-use batching — state machine, formatting, edit-in-place delivery                                                                                                        |
| `toolbar_callbacks.py`         | Toolbar callback handlers — dispatch for /toolbar inline button clicks                                                                                                              |
| `toolbar_keyboard.py`          | Toolbar keyboard builder — constructs the /toolbar inline keyboard from TOML config with per-window label overrides                                                                 |
| `topic_emoji.py`               | Topic name emoji updates (active/idle/done/dead + RC/YOLO badges), debounced                                                                                                        |
| `topic_lifecycle.py`           | Topic lifecycle management — autoclose timers for done/dead topics, unbound window TTL                                                                                              |
| `topic_orchestration.py`       | New window/topic creation, unbound window adoption, rate limiting                                                                                                                   |
| `transcript_discovery.py`      | Hookless transcript discovery for Codex/Gemini, provider auto-detection, shell↔agent transitions                                                                                    |
| `upgrade.py`                   | /upgrade command: uv tool upgrade + process restart                                                                                                                                 |
| `user_state.py`                | context.user_data string key constants                                                                                                                                              |
| `voice_callbacks.py`           | Voice callback routing (vc:send/vc:drop); shell provider transcriptions route through LLM                                                                                           |
| `voice_handler.py`             | Voice message download, transcription, confirm keyboard                                                                                                                             |
| `window_callbacks.py`          | Window picker callbacks (bind, new, cancel)                                                                                                                                         |

### State files (`~/.ccgram/` or `$CCBOT_DIR/`)

| File                 | Description                                                      |
| -------------------- | ---------------------------------------------------------------- |
| `state.json`         | Thread bindings + window states + display names + read offsets   |
| `session_map.json`   | Hook-generated window_id→session mapping                         |
| `events.jsonl`       | Append-only hook event log (all hook events)                     |
| `monitor_state.json` | Poll progress (byte offset) per JSONL file                       |
| `mailbox/`           | Inter-agent message inboxes (per-window dirs with JSON messages) |

## Key Design Decisions

- **Topic-centric** — Each Telegram topic binds to one tmux window. No centralized session list; topics _are_ the session list.
- **Window ID-centric** — All internal state keyed by tmux window ID (e.g. `@0`, `@12`), not window names. Window IDs are guaranteed unique within a tmux server session. Window names are kept as display names via `window_display_names` map. Same directory can have multiple windows.
- **Hook-based event system** — Claude Code hooks (SessionStart, Notification, Stop, StopFailure, SessionEnd, SubagentStart, SubagentStop, TeammateIdle, TaskCompleted) write to `session_map.json` and `events.jsonl`. SessionMonitor reads both: session_map for session tracking, events.jsonl for instant event dispatch (interactive UI, done detection, API error alerting, session lifecycle, subagent status, team notifications). Terminal scraping remains as fallback. Missing hooks are detected at startup with an actionable warning.
- **Multi-pane awareness** — Windows with multiple panes (e.g. Claude Code agent teams) are scanned for interactive prompts in non-active panes. Blocked panes are auto-surfaced as inline keyboard alerts. `/panes` command lists all panes with status and per-pane screenshot buttons. Callback data format extended to include pane_id: `"aq:enter:@12:%5"`.
- **Tool use ↔ tool result pairing** — `tool_use_id` tracked across poll cycles; tool result edits the original tool_use Telegram message in-place.
- **Entity-based formatting** — All messages go through `safe_reply`/`safe_edit`/`safe_send` which convert markdown to plain text + `MessageEntity` offsets via `telegramify-markdown`, falling back to plain text on failure. No parse errors possible.
- **No truncation at parse layer** — Full content preserved; splitting at send layer respects Telegram's 4096 char limit with expandable quote atomicity.
- Only sessions registered in `session_map.json` (via hook) are monitored.
- Notifications delivered to users via thread bindings (topic → window_id → session).
- **Startup re-resolution** — Window IDs reset on tmux server restart. On startup, `resolve_stale_ids()` matches persisted display names against live windows to re-map IDs. Old state.json files keyed by window name are auto-migrated.
- **Per-window provider** — All CLI-specific behavior (launch args, transcript parsing, terminal status, command discovery) is delegated to an `AgentProvider` protocol. Providers declare capabilities (`ProviderCapabilities`) that gate UX features per-window: hook checks, resume/continue buttons, and command registration. Each window stores its `provider_name` in `WindowState`; `get_provider_for_window(window_id)` resolves the correct provider instance, falling back to the config default. Externally created windows are auto-detected via `detect_provider_from_command(pane_current_command)`. The global `get_provider()` singleton remains for CLI commands (`doctor`, `status`) that lack window context.
- **Inter-agent messaging** — File-based mailbox system (`~/.ccgram/mailbox/`) with per-window inbox directories. Qualified IDs (`session:@N`) match session_map convention. Broker delivery injects messages into idle windows via send_keys; shell windows are inbox-only. Telegram notifications are silent and grouped. Spawn approval requires Telegram keyboard confirmation. `CCGRAM_WINDOW_ID` env var set on window creation for agent self-identification.
- **Foreign window support (emdash)** — Windows owned by external tools (emdash) use qualified IDs like `emdash-claude-main-abc123:@0` which are valid tmux `-t` targets. Foreign windows are marked `WindowState.external=True` and are never killed by ccgram. Discovery via `tmux list-sessions` filtered by `emdash-` prefix. The `window_resolver` preserves foreign entries during startup re-resolution. All tmux operations (send_keys, capture_pane) route foreign IDs through subprocess instead of libtmux.
- **Live terminal view** — Auto-refreshing screenshots via `editMessageMedia` at configurable intervals (default 5s). Content-hash gating skips API calls when the terminal hasn't changed. One active view per topic, auto-stops after timeout (default 300s). Managed by `handlers/live_view.py`, ticked from `handlers/periodic_tasks.py`.
- **Completion summaries** — On agent Stop events, `llm/summarizer.py` reads the session transcript and produces a single-line summary that edits the Ready message in-place. Non-blocking — the static enriched Ready message appears immediately, LLM enhancement arrives ~1-2s later.
