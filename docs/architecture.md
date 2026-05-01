# ccgram Architecture

Generated from code state 2026-05-02 (post Round 5 modularity decouple).

## System Overview

ccgram maps each Telegram Forum topic to one tmux window running one agent CLI (Claude Code, Codex, Gemini, Pi, or Shell). All internal routing is keyed by tmux window ID (`@0`, `@12`).

```mermaid
graph TB
    Telegram["Telegram<br>(Forum topics)"]
    Bot["bot.py<br>(172 lines: factory + lifecycle)"]
    Bootstrap["bootstrap.py<br>post_init + post_shutdown"]
    Registry["handlers/registry.py<br>PTB handler wiring"]
    TC["telegram_client.py<br>TelegramClient Protocol<br>+ PTBTelegramClient adapter"]
    Handlers["handlers/<br>14 feature subpackages"]
    TmuxMgr["tmux_manager.py <br> libtmux + subprocess"]
    Windows["tmux windows <br> (Claude, Codex, Gemini, Pi, Shell)"]
    Hook["hook.py<br>Claude Code hooks"]
    Monitor["session_monitor.py<br>poll loop"]
    State["State files<br>~/.ccgram/"]

    Telegram -- "updates" --> Bot
    Bot -- "post_init" --> Bootstrap
    Bot -- "register_all" --> Registry
    Registry -- "dispatch" --> Handlers
    Handlers -- "depend on Protocol" --> TC
    TC -- "PTBTelegramClient" --> Bot
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
    subgraph entry["Entry Points + Bootstrap"]
        CLI["cli.py / main.py"]
        BotPy["bot.py<br>(factory + lifecycle, 172 lines)"]
        BootstrapPy["bootstrap.py<br>post_init + post_shutdown"]
        RegistryPy["handlers/registry.py<br>PTB handler wiring"]
        HookPy["hook.py"]
    end

    subgraph protocol["Telegram Seam"]
        TCProto["telegram_client.py<br>TelegramClient Protocol<br>+ PTBTelegramClient adapter<br>+ FakeTelegramClient (tests)"]
    end

    subgraph handlers["Handler Layer — handlers/"]
        TopLevel["Top-level: callback_*, cleanup,<br>command_*, file_handler, hook_events,<br>inline, reactions, registry, response_builder,<br>sessions_dashboard, sync_command, upgrade, user_state"]
        TopicsPkg["topics/<br>topic_orchestration, topic_lifecycle,<br>directory_browser, directory_callbacks,<br>window_callbacks, new_command"]
        TextPkg["text/<br>text_handler"]
        InteractivePkg["interactive/<br>interactive_ui, interactive_callbacks"]
        StatusPkg["status/<br>status_bubble, status_bar_actions, topic_emoji"]
        LivePkg["live/<br>live_view, screenshot_callbacks, pane_callbacks"]
        SendPkg["send/<br>send_command, send_callbacks, send_security"]
        ToolbarPkg["toolbar/<br>toolbar_keyboard, toolbar_callbacks"]
        VoicePkg["voice/<br>voice_handler, voice_callbacks"]
        ShellPkg["shell/<br>shell_commands, shell_capture,<br>shell_context, shell_prompt_orchestrator"]
        MsgPipePkg["messaging_pipeline/<br>message_queue, message_routing,<br>message_sender, message_task,<br>tool_batch, topic_commands"]
        MessagingPkg["messaging/<br>msg_broker, msg_delivery,<br>msg_telegram, msg_spawn"]
        RecoveryPkg["recovery/<br>recovery_callbacks (dispatcher),<br>recovery_banner, resume_picker,<br>restore_command, resume_command,<br>transcript_discovery,<br>history, history_callbacks"]
        CommandsPkg["commands/<br>forward, menu_sync,<br>failure_probe, status_snapshot"]
        PollingPkg["polling/<br>polling_coordinator,<br>polling_types (pure), polling_state (stateful),<br>periodic_tasks,<br>window_tick/{decide, observe, apply}"]
    end

    subgraph query["Read-Only Query Layer"]
        WQ["window_query.py<br>read window state"]
        SQ["session_query.py<br>read session data"]
    end

    subgraph state["State Management (constructor DI — F2)"]
        SM["session.py<br>SessionManager<br>(constructs + owns stores)"]
        TR["thread_router.py<br>(callbacks via __init__)"]
        WS["window_state_store.py<br>(callbacks via __init__)"]
        UP["user_preferences.py<br>(callback via __init__)"]
        SMS["session_map.py<br>SessionMapSync<br>(callback via __init__)"]
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
        Jsonl["providers/_jsonl.py<br>(Codex + Gemini + Pi base)"]
        Shell["providers/shell.py"]
    end

    subgraph monitor["Session Monitoring"]
        SesMon["session_monitor.py"]
        TReader["transcript_reader.py"]
        EvReader["event_reader.py"]
        SLifecycle["session_lifecycle.py"]
        IdleT["idle_tracker.py"]
    end

    BotPy --> BootstrapPy
    BotPy --> RegistryPy
    RegistryPy --> handlers
    handlers --> protocol
    protocol --> BotPy
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

    SM --> Startup["Startup orchestration<br>__post_init__ (constructs+installs stores)<br>resolve_stale_ids"]
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
    class PiProvider
    class ShellProvider

    AgentProvider <|.. ClaudeProvider
    AgentProvider <|.. JsonlProvider
    JsonlProvider <|-- CodexProvider
    JsonlProvider <|-- GeminiProvider
    JsonlProvider <|-- PiProvider
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

| Decision                                | Rationale                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Window ID-centric routing (`@0`, `@12`) | Unique within tmux server; window names are display-only                                                                                                                                                                                                                                                                                     |
| Hook-based event system                 | Instant stop/done detection without terminal polling                                                                                                                                                                                                                                                                                         |
| `window_query.py` decoupling layer      | Handlers read window state without importing `SessionManager`                                                                                                                                                                                                                                                                                |
| `session_query.py` decoupling layer     | Handlers resolve sessions without importing `SessionManager`                                                                                                                                                                                                                                                                                 |
| Provider protocol with capability flags | Gate UX features without `if provider == "claude"` checks                                                                                                                                                                                                                                                                                    |
| `supports_task_tracking` capability     | `transcript_reader` is provider-agnostic; Claude implements task state                                                                                                                                                                                                                                                                       |
| Session map direct imports              | Lifecycle handlers use `session_map_sync` directly; no facade needed                                                                                                                                                                                                                                                                         |
| File-based mailbox                      | Agents exchange messages via `~/.ccgram/mailbox/`; broker injects via `send_keys`                                                                                                                                                                                                                                                            |
| Shell leak accepted                     | `match_prompt`, `KNOWN_SHELLS` imports in shell handlers are low-volatility supporting domain — balance rule satisfied by `NOT VOLATILITY`                                                                                                                                                                                                   |
| Tool-call visibility on `WindowState`   | Per-window `tool_call_visibility` (`default`/`shown`/`hidden`) gates `_handle_content_task` before batch eligibility; hook events bypass                                                                                                                                                                                                     |
| Status-mode color schemes               | `CCGRAM_STATUS_MODE` selects `system` (green=working) or `user` (green=ready) — affects only emoji rendering, not internal state names                                                                                                                                                                                                       |
| Gemini JSONL incremental reads          | Gemini CLI v0.40+ uses append-only JSONL; provider inherits `JsonlProvider` byte-offset reader, dedups by message id and pending tool_use                                                                                                                                                                                                    |
| `handlers/` feature subpackages (F1)    | 14 subpackages + documented top-level files instead of 50+ flat peers; each subpackage `__init__.py` re-exports the public surface                                                                                                                                                                                                           |
| Constructor DI for stores (F2)          | `SessionManager` constructs `WindowStateStore`/`ThreadRouter`/`UserPreferences`/`SessionMapSync` with explicit callbacks; no `_wire_singletons` monkey-patch, no `unwired_save` silent default; `register_*_callback` fails loud                                                                                                             |
| `bot.py` factory + lifecycle only (F3)  | 172-line `bot.py`; `handlers/registry.py` owns command/message handler wiring; `bootstrap.py` owns `post_init`/`post_shutdown`                                                                                                                                                                                                               |
| `window_tick/decide,observe,apply` (F4) | Pure decision kernel + pure observer + side-effect applier; `decide_tick` unit-testable without mocks                                                                                                                                                                                                                                        |
| `TelegramClient` Protocol (F5)          | Handlers depend on `TelegramClient` not `telegram.Bot`; `PTBTelegramClient` adapts in production, `FakeTelegramClient` records in tests; only `bot.py`, `bootstrap.py`, `handlers/registry.py`, `telegram_client.py`, `telegram_request.py`, `telegram_sender.py` import from `telegram.ext` at runtime                                      |
| Lazy-import audit (F6)                  | 251 in-function imports → 201; remaining sites carry `# Lazy: <reason>` documenting the cycle path or wiring contract; cycle regressions caught by `tests/integration/test_import_no_cycles.py`                                                                                                                                              |
| Pure types vs stateful polling (R5 F1)  | `polling_strategies.py` deleted; `polling_types.py` (~150 LOC, stdlib + `providers.base.StatusUpdate` only) holds contracts; `polling_state.py` holds strategies + 5 module-level singletons; `decide.py` imports only from `polling_types`. Codified by `test_polling_types_purity.py` (subprocess + AST)                                   |
| Single read path enforcement (R5 F2)    | Handler reads of window/session state go through `window_query` / `session_query`; direct `session_manager.<attr>` in `handlers/**` restricted to write/admin allow-list. AST walk over 86 handler files asserts the rule (`test_query_layer_only_for_handlers.py`)                                                                          |
| Recovery split (R5 F3)                  | `recovery_callbacks.py` shrunk to ~170-LOC dispatcher (routing + shared validators); `recovery_banner.py` (~450 LOC dead-window UX) + `resume_picker.py` (~400 LOC resume UX + transcript scan) are siblings. `recovery/__init__.py` re-exports unchanged; pinned by `test_recovery_subpackage_surface.py`                                   |
| Commands subpackage (R5 F4)             | `command_orchestration.py` deleted; `handlers/commands/` follows `shell/` pattern: `forward.py`, `menu_sync.py`, `failure_probe.py`, `status_snapshot.py`. `commands/__init__.py` hosts `commands_command` + `toolbar_command`; pinned by `test_commands_subpackage_surface.py`                                                              |
| Lazy-import lint enforcement (R5 F5)    | `scripts/lint_lazy_imports.py` AST-walks `src/ccgram/**/*.py` and fails any in-function import without `# Lazy:` (or inside `if TYPE_CHECKING:` / `_reset_*_for_testing`). Walker recurses through compound statements (incl. `except*`) and nested `def`/`class` bodies. All 250 sites annotated. Cycle test expanded from 29 → 162 modules |
