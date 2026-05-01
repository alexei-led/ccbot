# Architecture Map

## Runtime Layers

1. CLI and bootstrap

- `src/ccgram/main.py` starts logging and launches the PTB application.
- `src/ccgram/cli.py` maps CLI flags to env vars before config loads.

2. Bot orchestration

- `src/ccgram/bot.py` is a 172-line factory + lifecycle delegate (post Round 4 F3).
- `src/ccgram/handlers/registry.py` owns PTB command/message/callback/inline handler registration (`register_all`).
- `src/ccgram/bootstrap.py` owns `post_init` (`bootstrap_application` → `register_provider_commands`, `verify_hooks_installed`, `wire_runtime_callbacks`, `start_session_monitor`, `start_status_polling`, `start_miniapp_if_enabled`) and `post_shutdown` (`shutdown_runtime`). Ordering invariant: `wire_runtime_callbacks` must run before `start_session_monitor`.
- `src/ccgram/telegram_client.py` defines the `TelegramClient` Protocol that all handlers depend on; `PTBTelegramClient` adapts the real PTB `Bot`; `FakeTelegramClient` records calls in tests.
- Topic routing and authorization checks live in `bot.py` + `handlers/registry.py`.

3. Session and monitor core

- `src/ccgram/session.py` is the state hub (thread bindings, window states, offsets).
- `src/ccgram/session_monitor.py` tails transcripts/events and emits parsed messages.
- `src/ccgram/monitor_state.py` persists byte offsets for incremental reads.

4. Provider abstraction

- `src/ccgram/providers/base.py` defines the provider contract.
  - `discover_transcript(cwd, window_key, *, max_age=None)` is the hookless discovery contract (used by Codex/Gemini; `max_age=0` disables staleness checks for alive panes).
- `src/ccgram/providers/__init__.py` resolves per-window provider selection.
- `src/ccgram/providers/{claude,codex,gemini,pi,shell}.py` implement provider-specific behavior.
- `src/ccgram/providers/pi_format.py` + `pi_discovery.py` handle Pi transcript parsing and command discovery.
- `src/ccgram/command_catalog.py` discovers provider commands from filesystem (skills, custom commands) with 60s TTL caching.
- `src/ccgram/cc_commands.py` registers discovered commands as Telegram bot menu entries.
- `src/ccgram/providers/codex_format.py` normalizes provider interactive prompt text for Telegram readability (currently Codex edit approvals).
- `src/ccgram/providers/codex_status.py` extracts Codex status snapshots from JSONL transcripts.
- `src/ccgram/handlers/live/live_view.py` manages auto-refreshing terminal screenshots via editMessageMedia.
- `src/ccgram/screenshot.py` renders terminal text to PNG (PIL, ANSI color, font fallback).

4a. LLM command generation layer

- `src/ccgram/llm/base.py` defines the `CommandGenerator` protocol and `CommandResult` datatype used by all LLM backends.
- `src/ccgram/llm/httpx_completer.py` implements completers for OpenAI-compatible APIs and the Anthropic API via httpx. Temperature is configurable via `CCGRAM_LLM_TEMPERATURE`.
- `src/ccgram/llm/__init__.py` owns the `_PROVIDERS` registry and resolves the active backend from config (provider, model, temperature).
- `src/ccgram/handlers/shell/shell_commands.py` consumes `CommandGenerator` to drive the NL→command→approval-keyboard flow; also handles raw `!` command execution.
- `src/ccgram/handlers/shell/shell_capture.py` polls the shell pane after execution and streams output back to Telegram via in-place edits.

4b. Voice transcription layer

- `src/ccgram/whisper/base.py` defines the `WhisperTranscriber` protocol and `TranscriptionResult` datatype.
- `src/ccgram/whisper/httpx_transcriber.py` implements OpenAI-compatible transcription via httpx (OpenAI, Groq).
- `src/ccgram/whisper/__init__.py` resolves the active transcriber from config (provider, API key, model).
- `src/ccgram/handlers/voice/voice_handler.py` downloads voice audio, transcribes via Whisper, and shows confirm/discard keyboard.
- `src/ccgram/handlers/voice/voice_callbacks.py` handles confirm/discard callbacks; shell provider transcriptions route through the LLM for NL→command generation.

4c. Completion summary layer

- `src/ccgram/llm/summarizer.py` reads the session transcript and produces a single-line summary via LLM.
- `src/ccgram/handlers/hook_events.py` triggers the summary on Stop events and edits the Ready message in-place.

5. Integrations

- `src/ccgram/tmux_manager.py` is the tmux IO boundary.
- `src/ccgram/hook.py` writes Claude hook events to both `session_map.json` and `events.jsonl`.

## Request/Response Lifecycles

Inbound user message (Telegram -> tmux):

1. PTB dispatcher routes through handlers wired in `handlers/registry.py`.
2. `handlers/text/text_handler.py` validates context and resolves topic binding.
3. `session.py` maps `(user_id, thread_id)` -> `window_id`.
4. `tmux_manager.py` sends keys to the mapped window/pane.

Shell provider message flow (NL -> command -> shell):

1. `handlers/text/text_handler.py` detects shell provider window and routes to `handlers/shell/shell_commands.py`.
2. `shell_commands.py` calls `llm/` to generate a suggested command from the NL description.
3. Telegram approval keyboard is rendered; user confirms or cancels.
4. On approval, the command is sent to the tmux pane via `tmux_manager.py`.
5. `handlers/shell/shell_capture.py` polls pane output and relays it back to Telegram via in-place edits.

Voice message flow (voice -> transcription -> agent):

1. `handlers/voice/voice_handler.py` downloads audio and transcribes via `whisper/`.
2. Confirm/discard keyboard is shown with the transcription.
3. On confirm, `handlers/voice/voice_callbacks.py` checks the window's provider.
4. For shell provider: routes transcribed text through `handlers/shell/shell_commands.py` (LLM -> approval keyboard).
5. For other providers: sends transcribed text directly to the tmux window.

Outbound agent output (provider transcript/event -> Telegram):

1. `session_monitor.py` polls tracked transcript/event sources incrementally.
2. Provider parser (`providers/*.py` + `transcript_parser.py`/`terminal_parser.py`) emits normalized updates.
3. `handlers/messaging_pipeline/message_queue.py` enforces ordering, merge rules, and rate limits — worker takes a `TelegramClient`.
4. Telegram send helpers in `handlers/messaging_pipeline/message_sender.py` deliver messages and status updates via the `TelegramClient` Protocol.

Live view flow (terminal -> auto-refresh screenshots):

1. User taps Live button in `handlers/live/screenshot_callbacks.py`.
2. `handlers/live/live_view.py` registers an active view for the topic.
3. `handlers/polling/periodic_tasks.py` calls `live_view.tick_live_views()` every `config.live_view_interval` seconds.
4. Each tick captures the pane via `tmux_manager.py`, hashes content, and edits the Telegram photo via `editMessageMedia` only when content changed.
5. Auto-stops after `config.live_view_timeout` seconds of inactivity or when user taps Stop.

Recovery flow (dead/missing session):

1. `handlers/polling/polling_coordinator.py` detects stale/dead bindings via `handlers/polling/window_tick/`.
2. Recovery UI callbacks route through `handlers/recovery/recovery_callbacks.py` (thin dispatcher, Round 5 F3) which dispatches to `recovery_banner.py` (dead-window banner UX) or `resume_picker.py` (resume picker UX + transcript scan).
3. Session/window state is updated in `session.py` and persisted to `state.json`.

Commands menu flow (`/commands`):

1. User invokes `/commands` in a topic.
2. `handlers/registry.py` dispatches to `handlers/commands/__init__.py:commands_command` (Round 5 F4 subpackage).
3. `command_catalog.py` discovers available commands for the window's provider (filesystem scan with 60s TTL cache).
4. `cc_commands.py` renders the scoped command menu as inline keyboard.
5. User selection sends the command text to the agent via `tmux_manager.py`; failure-probe path lives in `handlers/commands/failure_probe.py`, status-snapshot delegation in `handlers/commands/status_snapshot.py`, menu sync/cache in `handlers/commands/menu_sync.py`.

## Data Model and State Files

Config/state directory is `~/.ccgram` unless overridden by `CCGRAM_DIR`.

- `state.json`: topic<->window bindings and window metadata.
- `session_map.json`: hook-generated tmux window -> session map.
- `events.jsonl`: append-only hook events stream.
- `monitor_state.json`: monitor byte offsets (session/event files).

Provider transcript sources (read-only):

- Claude: `~/.claude/projects/`
- Codex: `~/.codex/sessions/`
- Gemini: `~/.gemini/tmp/<project-hash>/chats/*.jsonl` (Gemini CLI v0.40+; append-only JSONL, byte-offset incremental reads via `JsonlProvider`).
  - Gemini discovery matches by `projectHash` (or configured project alias dir) and does not full-scan unrelated project dirs.
- Pi: `~/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<uuid>.jsonl` (JSONL v3; discovery matches the header `cwd` against the window cwd).
- Shell: no transcript files; output is captured directly from the tmux pane by `handlers/shell/shell_capture.py`.

## Core Flow

Inbound (Telegram -> agent):

- message enters `bot.py` -> dispatched via `handlers/registry.py` -> `handlers/text/text_handler.py` -> resolve bound window in `session.py` -> send keys via `tmux_manager.py`.

Outbound (agent -> Telegram):

- `session_monitor.py` reads transcript/event deltas -> provider parser transforms entries -> `handlers/messaging_pipeline/message_queue.py` orders/rate-limits sends -> `TelegramClient` Protocol -> Telegram API via `PTBTelegramClient` adapter.

## Design Constraints to Preserve

- one topic = one window mapping.
- internal identity keyed by tmux `window_id` (not window names).
- no parse-layer truncation; splitting only at Telegram send layer.
- per-window provider behavior and capability-gated UI.
- tmux operations stay centralized in `tmux_manager.py`; do not spread raw shell tmux calls across handlers.
- state mutations route through `session.py` + persistence helpers, not ad-hoc JSON writes.
- handlers depend on the `TelegramClient` Protocol (`src/ccgram/telegram_client.py`), not `telegram.Bot`. Only `bot.py`, `bootstrap.py`, `handlers/registry.py`, `telegram_client.py`, `telegram_request.py`, and `telegram_sender.py` import from `telegram.ext` at runtime; everything else uses `if TYPE_CHECKING:` for types.
- `SessionManager` constructs and owns `WindowStateStore`, `ThreadRouter`, `UserPreferences`, and `SessionMapSync` via constructor DI — do not reintroduce `_wire_singletons` or `unwired_save`.
- handler reads of window/session state go through `window_query` / `session_query` (Round 5 F2). Direct `session_manager.<attr>` access in `handlers/**` is restricted to the documented write/admin allow-list (`set_window_provider`, `set_window_origin`, `set_window_approval_mode`, `cycle_*`, `audit_state`, `prune_*`, `sync_display_names`); `tests/ccgram/test_query_layer_only_for_handlers.py` enforces the rule via AST walk.
- `handlers/polling/polling_types.py` is pure (stdlib + `providers.base.StatusUpdate` only) — do not reintroduce stateful imports there. `polling_state.py` owns the strategies and module-level singletons. `decide.py` imports only from `polling_types`. Pinned by `tests/ccgram/handlers/polling/test_polling_types_purity.py` (subprocess load + AST static check).
- in-function imports must carry `# Lazy: <reason>` (or live inside `if TYPE_CHECKING:` / `_reset_*_for_testing`) — `make lint` runs `lint-lazy` (Round 5 F5) which fails on undocumented late imports.
