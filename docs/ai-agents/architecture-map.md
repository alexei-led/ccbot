# Architecture Map

## Runtime Layers

1. CLI and bootstrap

- `src/ccgram/main.py` starts logging and launches the PTB application.
- `src/ccgram/cli.py` maps CLI flags to env vars before config loads.

2. Bot orchestration

- `src/ccgram/bot.py` wires handlers and owns callback dispatch.
- Topic routing and authorization checks live here.

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
- `src/ccgram/handlers/live_view.py` manages auto-refreshing terminal screenshots via editMessageMedia.
- `src/ccgram/screenshot.py` renders terminal text to PNG (PIL, ANSI color, font fallback).

4a. LLM command generation layer

- `src/ccgram/llm/base.py` defines the `CommandGenerator` protocol and `CommandResult` datatype used by all LLM backends.
- `src/ccgram/llm/httpx_completer.py` implements completers for OpenAI-compatible APIs and the Anthropic API via httpx. Temperature is configurable via `CCGRAM_LLM_TEMPERATURE`.
- `src/ccgram/llm/__init__.py` owns the `_PROVIDERS` registry and resolves the active backend from config (provider, model, temperature).
- `src/ccgram/handlers/shell_commands.py` consumes `CommandGenerator` to drive the NL→command→approval-keyboard flow; also handles raw `!` command execution.
- `src/ccgram/handlers/shell_capture.py` polls the shell pane after execution and streams output back to Telegram via in-place edits.

4b. Voice transcription layer

- `src/ccgram/whisper/base.py` defines the `WhisperTranscriber` protocol and `TranscriptionResult` datatype.
- `src/ccgram/whisper/httpx_transcriber.py` implements OpenAI-compatible transcription via httpx (OpenAI, Groq).
- `src/ccgram/whisper/__init__.py` resolves the active transcriber from config (provider, API key, model).
- `src/ccgram/handlers/voice_handler.py` downloads voice audio, transcribes via Whisper, and shows confirm/discard keyboard.
- `src/ccgram/handlers/voice_callbacks.py` handles confirm/discard callbacks; shell provider transcriptions route through the LLM for NL→command generation.

4c. Completion summary layer

- `src/ccgram/llm/summarizer.py` reads the session transcript and produces a single-line summary via LLM.
- `src/ccgram/handlers/hook_events.py` triggers the summary on Stop events and edits the Ready message in-place.

5. Integrations

- `src/ccgram/tmux_manager.py` is the tmux IO boundary.
- `src/ccgram/hook.py` writes Claude hook events to both `session_map.json` and `events.jsonl`.

## Request/Response Lifecycles

Inbound user message (Telegram -> tmux):

1. PTB handler entry in `bot.py`.
2. `handlers/text_handler.py` validates context and resolves topic binding.
3. `session.py` maps `(user_id, thread_id)` -> `window_id`.
4. `tmux_manager.py` sends keys to the mapped window/pane.

Shell provider message flow (NL -> command -> shell):

1. `handlers/text_handler.py` detects shell provider window and routes to `shell_commands.py`.
2. `shell_commands.py` calls `llm/` to generate a suggested command from the NL description.
3. Telegram approval keyboard is rendered; user confirms or cancels.
4. On approval, the command is sent to the tmux pane via `tmux_manager.py`.
5. `shell_capture.py` polls pane output and relays it back to Telegram via in-place edits.

Voice message flow (voice -> transcription -> agent):

1. `handlers/voice_handler.py` downloads audio and transcribes via `whisper/`.
2. Confirm/discard keyboard is shown with the transcription.
3. On confirm, `handlers/voice_callbacks.py` checks the window's provider.
4. For shell provider: routes transcribed text through `shell_commands.py` (LLM -> approval keyboard).
5. For other providers: sends transcribed text directly to the tmux window.

Outbound agent output (provider transcript/event -> Telegram):

1. `session_monitor.py` polls tracked transcript/event sources incrementally.
2. Provider parser (`providers/*.py` + `transcript_parser.py`/`terminal_parser.py`) emits normalized updates.
3. `handlers/message_queue.py` enforces ordering, merge rules, and rate limits.
4. Telegram send helpers deliver messages and status updates.

Live view flow (terminal -> auto-refresh screenshots):

1. User taps Live button in `handlers/screenshot_callbacks.py`.
2. `handlers/live_view.py` registers an active view for the topic.
3. `handlers/periodic_tasks.py` calls `live_view.tick()` every `config.live_view_interval` seconds.
4. Each tick captures the pane via `tmux_manager.py`, hashes content, and edits the Telegram photo via `editMessageMedia` only when content changed.
5. Auto-stops after `config.live_view_timeout` seconds of inactivity or when user taps Stop.

Recovery flow (dead/missing session):

1. `handlers/polling_coordinator.py` detects stale/dead bindings.
2. Recovery UI callbacks route through `handlers/recovery_callbacks.py`.
3. Session/window state is updated in `session.py` and persisted to `state.json`.

Commands menu flow (`/commands`):

1. User invokes `/commands` in a topic.
2. `handlers/` routes to command handler in `bot.py`.
3. `command_catalog.py` discovers available commands for the window's provider (filesystem scan with 60s TTL cache).
4. `cc_commands.py` renders the scoped command menu as inline keyboard.
5. User selection sends the command text to the agent via `tmux_manager.py`.

## Data Model and State Files

Config/state directory is `~/.ccgram` unless overridden by `CCGRAM_DIR`.

- `state.json`: topic<->window bindings and window metadata.
- `session_map.json`: hook-generated tmux window -> session map.
- `events.jsonl`: append-only hook events stream.
- `monitor_state.json`: monitor byte offsets (session/event files).

Provider transcript sources (read-only):

- Claude: `~/.claude/projects/`
- Codex: `~/.codex/sessions/`
- Gemini: `~/.gemini/tmp/`
  - Gemini discovery matches by `projectHash` (or configured project alias dir) and does not full-scan unrelated project dirs.
- Pi: `~/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<uuid>.jsonl` (JSONL v3; discovery matches the header `cwd` against the window cwd).
- Shell: no transcript files; output is captured directly from the tmux pane by `handlers/shell_capture.py`.

## Core Flow

Inbound (Telegram -> agent):

- message enters `bot.py` -> `handlers/text_handler.py` -> resolve bound window in `session.py` -> send keys via `tmux_manager.py`.

Outbound (agent -> Telegram):

- `session_monitor.py` reads transcript/event deltas -> provider parser transforms entries -> `handlers/message_queue.py` orders/rate-limits sends -> Telegram API.

## Design Constraints to Preserve

- one topic = one window mapping.
- internal identity keyed by tmux `window_id` (not window names).
- no parse-layer truncation; splitting only at Telegram send layer.
- per-window provider behavior and capability-gated UI.
- tmux operations stay centralized in `tmux_manager.py`; do not spread raw shell tmux calls across handlers.
- state mutations route through `session.py` + persistence helpers, not ad-hoc JSON writes.
