# ccgram Architecture

Generated from code state 2026-04-16 (post modularity round 3).

## System Overview

ccgram maps each Telegram Forum topic to one tmux window running one agent CLI (Claude Code, Codex, Gemini, or Shell). All internal routing is keyed by tmux window ID (`@0`, `@12`).

```mermaid
graph TB
    Telegram["Telegram<br>(Forum topics)"]
    Bot["bot.py<br>PTB application"]
    Handlers["handlers/<br>50+ modules"]
    TmuxMgr["tmux_manager.py <br> libtmux + subprocess"]
    Windows["tmux windows <br> (Claude, Codex, Gemini, Shell)"]
    Hook["hook.py<br>Claude Code hooks"]
    Monitor["session_monitor.py<br>poll loop"]
    State["State files<br>~/.ccgram/"]

    Telegram -- "updates" --> Bot
    Bot -- "dispatch" --> Handlers
    Handlers -- "send_keys / capture_pane" --> TmuxMgr
    TmuxMgr --> Windows
    Windows -- "hook events" --> Hook
    Hook -- "session_map.json<br>events.jsonl" --> State
    Monitor -- "reads" --> State
    Monitor -- "NewMessage / NewWindowEvent" --> Handlers
```

## Module Layers

```mermaid
graph TD
    subgraph entry["Entry Points"]
        CLI["cli.py / main.py"]
        BotPy["bot.py"]
        HookPy["hook.py"]
    end

    subgraph handlers["Handler Layer (handlers/)"]
        TextH["text_handler"]
        CmdOrch["command_orchestration"]
        PollCoord["polling_coordinator"]
        WindowTick["window_tick"]
        MsgQueue["message_queue"]
        MsgRouting["message_routing"]
        ShellH["shell_commands<br>shell_capture<br>shell_context<br>shell_prompt_orchestrator"]
        DirH["directory_browser<br>directory_callbacks"]
        MsgBroker["msg_broker<br>msg_delivery<br>msg_telegram<br>msg_spawn"]
    end

    subgraph query["Read-Only Query Layer"]
        WQ["window_query.py<br>read window state"]
        SQ["session_query.py<br>read session data"]
    end

    subgraph state["State Management"]
        SM["session.py<br>SessionManager<br>(write + startup)"]
        TR["thread_router.py"]
        WS["window_state_store.py"]
        UP["user_preferences.py"]
        SMS["session_map.py<br>session_map_sync"]
        SR["session_resolver.py"]
    end

    subgraph infra["Infrastructure"]
        TmuxMgr2["tmux_manager.py"]
        WR["window_resolver.py"]
        SP["state_persistence.py"]
    end

    subgraph providers["Provider Abstraction"]
        Base["providers/base.py<br>AgentProvider protocol<br>ProviderCapabilities"]
        Claude["providers/claude.py"]
        Jsonl["providers/_jsonl.py<br>(Codex + Gemini base)"]
        Shell["providers/shell.py"]
    end

    subgraph monitor["Session Monitoring"]
        SesMon["session_monitor.py"]
        TReader["transcript_reader.py"]
        EvReader["event_reader.py"]
        SLifecycle["session_lifecycle.py"]
        IdleT["idle_tracker.py"]
    end

    BotPy --> handlers
    handlers --> query
    query --> WS
    query --> SR
    handlers --> SM
    SM --> TR & WS & UP & SMS
    SM --> SP
    SesMon --> TReader & EvReader & SLifecycle & IdleT
    SesMon --> SMS
    providers --> handlers
```

## State Flow: Topic → Window → Session

```mermaid
graph LR
    Topic["Telegram Topic<br>(thread_id)"]
    Window["tmux Window<br>(@id)"]
    Session["Claude Session<br>(uuid)"]

    Topic -- "thread_bindings<br>(thread_router.py)" --> Window
    Window -- "session_map.json<br>(written by hook)" --> Session

    WQ["window_query.py<br>read-only state"]
    SQ["session_query.py<br>read-only resolution"]
    SM["SessionManager<br>writes + startup"]

    Window -- "read" --> WQ
    Window -- "write" --> SM
    Session -- "read" --> SQ
```

## SessionManager Responsibilities (post round 3)

```mermaid
graph TB
    SM["SessionManager<br>26 public methods<br>(down from 39)"]

    SM --> Startup["Startup orchestration<br>__post_init__, _wire_singletons<br>resolve_stale_ids"]
    SM --> Writes["Write coordination<br>set_window_provider<br>set_window_cwd<br>set_*_mode<br>set_display_name"]
    SM --> Audit["Cross-cutting audit<br>audit_state<br>prune_stale_state<br>prune_stale_window_states"]

    WQ["window_query.py<br>get_window_provider()<br>get_approval_mode()<br>get_notification_mode()<br>view_window()"]
    SQ["session_query.py<br>resolve_session_for_window()<br>find_users_for_session()<br>get_recent_messages()"]
    SMS["session_map_sync<br>direct imports<br>load/prune/register"]
    TR2["thread_router<br>direct imports<br>get_display_name()"]

    SM -. "replaced by" .-> WQ
    SM -. "replaced by" .-> SQ
    SM -. "replaced by" .-> SMS
    SM -. "replaced by" .-> TR2
```

## Provider Protocol

```mermaid
classDiagram
    class ProviderCapabilities {
        +name: str
        +supports_hook: bool
        +supports_resume: bool
        +supports_task_tracking: bool
        +chat_first_command_path: bool
        +has_yolo_confirmation: bool
        ...15 more flags
    }

    class AgentProvider {
        <<Protocol>>
        +capabilities: ProviderCapabilities
        +make_launch_args() str
        +parse_transcript_line(line) dict
        +parse_transcript_entries(entries) list
        +parse_terminal_status(text) StatusUpdate
        +seed_task_state(wid, sid, path) ← NEW
        +apply_task_entries(wid, sid, entries) ← NEW
        +scrape_current_mode(wid) str
        ...8 more methods
    }

    class ClaudeProvider {
        +supports_task_tracking = True
        +seed_task_state() reads transcript
        +apply_task_entries() → claude_task_state
        +scrape_current_mode() parses mode-line
    }

    class JsonlProvider {
        +supports_task_tracking = False
        +seed_task_state() no-op
        +apply_task_entries() no-op
    }

    class CodexProvider
    class GeminiProvider
    class ShellProvider

    AgentProvider <|.. ClaudeProvider
    AgentProvider <|.. JsonlProvider
    JsonlProvider <|-- CodexProvider
    JsonlProvider <|-- GeminiProvider
    JsonlProvider <|-- ShellProvider
```

## Message Routing Flow

```mermaid
sequenceDiagram
    participant SessionMonitor
    participant MsgRouting as message_routing.py
    participant SQ as session_query.py
    participant WQ as window_query.py
    participant MsgQueue as message_queue.py
    participant Telegram

    SessionMonitor->>MsgRouting: NewMessage(session_id, text)
    MsgRouting->>SQ: find_users_for_session(session_id)
    SQ-->>MsgRouting: [(user_id, window_id, thread_id)]
    loop for each user
        MsgRouting->>WQ: get_notification_mode(window_id)
        WQ-->>MsgRouting: "all" | "errors_only" | "muted"
        alt not filtered
            MsgRouting->>MsgQueue: enqueue_content_message(...)
            MsgQueue->>Telegram: rate_limit_send → Bot API
        end
    end
```

## Hook Event Flow

```mermaid
sequenceDiagram
    participant Claude as Claude Code
    participant Hook as hook.py
    participant EventFiles as events.jsonl<br>session_map.json
    participant EventReader as event_reader.py
    participant SessionMonitor as session_monitor.py
    participant HookEvents as hook_events.py
    participant Telegram

    Claude->>Hook: hook event (stdin JSON)
    Hook->>EventFiles: append event + update map
    SessionMonitor->>EventReader: read_new_events(path, offset)
    EventReader-->>SessionMonitor: [HookEvent, ...]
    SessionMonitor->>HookEvents: dispatch_hook_event(event)
    HookEvents->>Telegram: status update / notification
```

## Shell Provider Architecture

```mermaid
graph TD
    ShellH["handlers/<br>shell_commands.py<br>shell_capture.py<br>shell_context.py<br>shell_prompt_orchestrator.py"]
    ShellProv["providers/<br>shell.py (thin)<br>shell_infra.py (utilities)"]
    JsonlBase["providers/_jsonl.py<br>(JsonlProvider base)"]

    ShellH -- "imports match_prompt,<br>KNOWN_SHELLS,<br>has_prompt_marker<br>(accepted leak: low volatility)" --> ShellProv
    ShellProv --> JsonlBase

    PS1["Terminal PS1<br>wrap mode: append ⌘N⌘<br>replace mode: {prefix}:N❯"]
    ShellH -- "setup_shell_prompt()" --> PS1

    LLM["llm/ (optional)<br>NL→command generation"]
    ShellH -- "get_completer()" --> LLM
```

## Session Monitoring Architecture

```mermaid
graph TB
    SM2["session_monitor.py<br>(coordinator)"]

    SM2 --> ER["event_reader.py<br>read_new_events(path, offset)<br>stateless pure I/O"]
    SM2 --> TR2["transcript_reader.py<br>per-session JSONL parsing<br>file mtime cache"]
    SM2 --> SL["session_lifecycle.py<br>reconcile() session map changes<br>handle_session_end()"]
    SM2 --> IT["idle_tracker.py<br>per-session activity timestamps"]

    TR2 -- "seed_task_state()<br>apply_task_entries()<br>(via provider protocol)" --> Claude2["ClaudeProvider<br>clause_task_state"]

    SM2 -- "load_session_map()<br>prune_session_map()" --> SMS2["session_map_sync"]
```

## Inter-Agent Messaging

```mermaid
graph LR
    AgentA["Agent A<br>(ccgram:@1)"]
    Mailbox["~/.ccgram/mailbox/<br>per-window inbox dirs"]
    AgentB["Agent B<br>(ccgram:@3)"]
    MsgBroker2["msg_broker.py<br>broker delivery cycle<br>idle detection"]
    TelegramNotif["Telegram<br>silent notifications"]
    SpawnRequest["spawn_request.py<br>user approval flow"]

    AgentA -- "ccgram msg send" --> Mailbox
    MsgBroker2 -- "poll + inject<br>send_keys" --> AgentB
    MsgBroker2 -- "notify" --> TelegramNotif
    AgentA -- "ccgram msg spawn" --> SpawnRequest
    SpawnRequest -- "inline keyboard" --> TelegramNotif

    Mailbox --> MsgBroker2
```

## Key Design Decisions

| Decision                                | Rationale                                                                                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Window ID-centric routing (`@0`, `@12`) | Unique within tmux server; window names are display-only                                                                                   |
| Hook-based event system                 | Instant stop/done detection without terminal polling                                                                                       |
| `window_query.py` decoupling layer      | Handlers read window state without importing `SessionManager`                                                                              |
| `session_query.py` decoupling layer     | Handlers resolve sessions without importing `SessionManager`                                                                               |
| Provider protocol with capability flags | Gate UX features without `if provider == "claude"` checks                                                                                  |
| `supports_task_tracking` capability     | `transcript_reader` is provider-agnostic; Claude implements task state                                                                     |
| Session map direct imports              | Lifecycle handlers use `session_map_sync` directly; no facade needed                                                                       |
| File-based mailbox                      | Agents exchange messages via `~/.ccgram/mailbox/`; broker injects via `send_keys`                                                          |
| Shell leak accepted                     | `match_prompt`, `KNOWN_SHELLS` imports in shell handlers are low-volatility supporting domain — balance rule satisfied by `NOT VOLATILITY` |
