# ccgram Architecture

Generated from code state 2026-04-16 (post modularity round 3).

## System Overview

ccgram maps each Telegram Forum topic to one tmux window running one agent CLI (Claude Code, Codex, Gemini, or Shell). All internal routing is keyed by tmux window ID (`@0`, `@12`).

```mermaid
graph TB
    Telegram["Telegram\n(Forum topics)"]
    Bot["bot.py\nPTB application"]
    Handlers["handlers/\n50+ modules"]
    TmuxMgr["tmux_manager.py\nlibtmux + subprocess"]
    Windows["tmux windows\n(Claude, Codex, Gemini, Shell)"]
    Hook["hook.py\nClaude Code hooks"]
    Monitor["session_monitor.py\npoll loop"]
    State["State files\n~/.ccgram/"]

    Telegram -- "updates" --> Bot
    Bot -- "dispatch" --> Handlers
    Handlers -- "send_keys / capture_pane" --> TmuxMgr
    TmuxMgr --> Windows
    Windows -- "hook events" --> Hook
    Hook -- "session_map.json\nevents.jsonl" --> State
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
        ShellH["shell_commands\nshell_capture\nshell_context\nshell_prompt_orchestrator"]
        DirH["directory_browser\ndirectory_callbacks"]
        MsgBroker["msg_broker\nmsg_delivery\nmsg_telegram\nmsg_spawn"]
    end

    subgraph query["Read-Only Query Layer"]
        WQ["window_query.py\nread window state"]
        SQ["session_query.py\nread session data"]
    end

    subgraph state["State Management"]
        SM["session.py\nSessionManager\n(write + startup)"]
        TR["thread_router.py"]
        WS["window_state_store.py"]
        UP["user_preferences.py"]
        SMS["session_map.py\nsession_map_sync"]
        SR["session_resolver.py"]
    end

    subgraph infra["Infrastructure"]
        TmuxMgr2["tmux_manager.py"]
        WR["window_resolver.py"]
        SP["state_persistence.py"]
    end

    subgraph providers["Provider Abstraction"]
        Base["providers/base.py\nAgentProvider protocol\nProviderCapabilities"]
        Claude["providers/claude.py"]
        Jsonl["providers/_jsonl.py\n(Codex + Gemini base)"]
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
    Topic["Telegram Topic\n(thread_id)"]
    Window["tmux Window\n(@id)"]
    Session["Claude Session\n(uuid)"]

    Topic -- "thread_bindings\n(thread_router.py)" --> Window
    Window -- "session_map.json\n(written by hook)" --> Session

    WQ["window_query.py\nread-only state"]
    SQ["session_query.py\nread-only resolution"]
    SM["SessionManager\nwrites + startup"]

    Window -- "read" --> WQ
    Window -- "write" --> SM
    Session -- "read" --> SQ
```

## SessionManager Responsibilities (post round 3)

```mermaid
graph TB
    SM["SessionManager\n26 public methods\n(down from 39)"]

    SM --> Startup["Startup orchestration\n__post_init__, _wire_singletons\nresolve_stale_ids"]
    SM --> Writes["Write coordination\nset_window_provider\nset_window_cwd\nset_*_mode\nset_display_name"]
    SM --> Audit["Cross-cutting audit\naudit_state\nprune_stale_state\nprune_stale_window_states"]

    WQ["window_query.py\nget_window_provider()\nget_approval_mode()\nget_notification_mode()\nview_window()"]
    SQ["session_query.py\nresolve_session_for_window()\nfind_users_for_session()\nget_recent_messages()"]
    SMS["session_map_sync\ndirect imports\nload/prune/register"]
    TR2["thread_router\ndirect imports\nget_display_name()"]

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
    participant EventFiles as events.jsonl\nsession_map.json
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
    ShellH["handlers/\nshell_commands.py\nshell_capture.py\nshell_context.py\nshell_prompt_orchestrator.py"]
    ShellProv["providers/\nshell.py (thin)\nshell_infra.py (utilities)"]
    JsonlBase["providers/_jsonl.py\n(JsonlProvider base)"]

    ShellH -- "imports match_prompt,\nKNOWN_SHELLS,\nhas_prompt_marker\n(accepted leak: low volatility)" --> ShellProv
    ShellProv --> JsonlBase

    PS1["Terminal PS1\nwrap mode: append ⌘N⌘\nreplace mode: {prefix}:N❯"]
    ShellH -- "setup_shell_prompt()" --> PS1

    LLM["llm/ (optional)\nNL→command generation"]
    ShellH -- "get_completer()" --> LLM
```

## Session Monitoring Architecture

```mermaid
graph TB
    SM2["session_monitor.py\n(coordinator)"]

    SM2 --> ER["event_reader.py\nread_new_events(path, offset)\nstateless pure I/O"]
    SM2 --> TR2["transcript_reader.py\nper-session JSONL parsing\nfile mtime cache"]
    SM2 --> SL["session_lifecycle.py\nreconcile() session map changes\nhandle_session_end()"]
    SM2 --> IT["idle_tracker.py\nper-session activity timestamps"]

    TR2 -- "seed_task_state()\napply_task_entries()\n(via provider protocol)" --> Claude2["ClaudeProvider\nclause_task_state"]

    SM2 -- "load_session_map()\nprune_session_map()" --> SMS2["session_map_sync"]
```

## Inter-Agent Messaging

```mermaid
graph LR
    AgentA["Agent A\n(ccgram:@1)"]
    Mailbox["~/.ccgram/mailbox/\nper-window inbox dirs"]
    AgentB["Agent B\n(ccgram:@3)"]
    MsgBroker2["msg_broker.py\nbroker delivery cycle\nidle detection"]
    TelegramNotif["Telegram\nsilent notifications"]
    SpawnRequest["spawn_request.py\nuser approval flow"]

    AgentA -- "ccgram msg send" --> Mailbox
    MsgBroker2 -- "poll + inject\nsend_keys" --> AgentB
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
