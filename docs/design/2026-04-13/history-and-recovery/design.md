# History and Recovery

## Functional Responsibilities

Query and recovery operations over Claude Code session history and the active-session dashboard. These features operate on the persisted session state and transcripts, not the live message stream.

Files:

- **`handlers/history.py`** (~340 lines) — `/history` command, paginated message history display with expandable quotes.
- **`handlers/history_callbacks.py`** — prev/next pagination callbacks.
- **`handlers/resume_command.py`** (~447 lines) — `/resume` command, scan past sessions, picker keyboard.
- **`handlers/restore_command.py`** — `/restore` command, recover dead topics via recovery keyboard.
- **`handlers/sessions_dashboard.py`** — `/sessions` command, active-session overview + kill action.
- **`handlers/transcript_discovery.py`** — hookless transcript discovery for Codex/Gemini, auto-detection on provider switch, shell↔agent transitions. Triggers `shell_prompt_orchestrator.ensure_setup(..., "provider_switch")` when a shell transition is detected.
- **`handlers/recovery_callbacks.py`** (~652 lines) — dead-window recovery callback handlers (fresh, continue, resume).
- **`handlers/command_history.py`** — per-user/per-topic command recall (last 20, in-memory).
- **`handlers/sync_command.py`** (~470 lines) — `/sync` command, state↔tmux reconciliation.
- **`handlers/upgrade.py`** — `/upgrade` command, `uv tool upgrade` + process restart.
- **`handlers/file_handler.py`** — photo/document handler (save to `.ccgram-uploads/`, notify agent).

## Encapsulated Knowledge

- **History pagination semantics** — only `history.py` knows how to slice a session's messages into pages that fit Telegram's 4096 char limit with expandable-quote atomicity. Per-user read offsets live in `user_preferences.py`.
- **Resume picker keyboard** — `resume_command.py` owns the pagination and selection UI for past sessions.
- **Recovery decision tree** — `recovery_callbacks.py` owns "given a dead window, what options does the user have": fresh / continue / resume. Provider capabilities gate the keyboard.
- **Transcript discovery for hookless providers** — `transcript_discovery.py` owns the periodic sweep that finds new Codex/Gemini transcripts and registers them via `session_map.register_hookless_session`.
- **Sync command** — `sync_command.py` owns the reconciliation semantics: given live tmux windows + persisted state + session_map, derive the audit report and apply fixes.

## Subdomain Classification

**Supporting.** These are stable recovery and query features. Moderate volatility inside `transcript_discovery.py` (every new provider needs a discovery branch) and `recovery_callbacks.py` (capability-gated UI).

## Integration Contracts

### Inbound

| From                                                                                          | Kind     |
| --------------------------------------------------------------------------------------------- | -------- |
| PTB command handlers for `/history`, `/resume`, `/restore`, `/sessions`, `/sync`, `/upgrade`  | Contract |
| PTB callback dispatcher → pagination / recovery / sessions-dashboard callbacks                | Contract |
| `polling_coordinator` → `transcript_discovery.discover_and_register_transcript(...)` per tick | Contract |

### Outbound

| To                                                                                           | Kind     |
| -------------------------------------------------------------------------------------------- | -------- |
| `session_manager.get_recent_messages(window_id)`                                             | Contract |
| `provider.parse_history_entry(...)` / `provider.discover_transcript(...)`                    | Contract |
| `tmux_manager.kill_window` (sessions dashboard kill action)                                  | Contract |
| `session_manager.resolve_session_for_window`                                                 | Contract |
| `shell_prompt_orchestrator.ensure_setup(window_id, "provider_switch")` (on shell transition) | Contract |
| `subprocess.run(['uv', 'tool', 'upgrade', 'ccgram'])` (`/upgrade`)                           | stdlib   |

## Change Vectors

- **New provider for transcript discovery** — add a branch in `transcript_discovery.py`.
- **New recovery option** — add a button in `recovery_callbacks.build_recovery_keyboard`, gate by a new capability flag if needed.
- **Change history page size** — constant in `history.py`.
- **New sync fixup rule** — add to `sync_command` audit + fix pipeline.

## Testability Goals

- **Unit-test `history.build_page(entries, offset, limit)`** — pure function of entries → formatted text + keyboard.
- **Unit-test `recovery_callbacks.build_recovery_keyboard`** with a fake provider capability matrix — verify which buttons appear.
- **Unit-test `transcript_discovery` session matching** — fixture list of transcript files + live windows → expected register / skip decisions.
- **Integration-test `/sync`** with a synthetic state.json and a synthetic `tmux list-windows` output — verify audit report.
- **Unit-test `command_history`** — add 30 entries, verify only the last 20 are kept.
