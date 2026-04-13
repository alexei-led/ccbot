# CLI Commands (no-bot)

## Functional Responsibilities

Command-line entry points that run without starting the Telegram bot. Used for diagnostics, setup, and inter-agent messaging outside the bot loop.

Files:

- **`doctor_cmd.py`** (~334 lines) — `ccgram doctor [--fix]`. Validates setup: hooks installed, session_map.json readable, state.json readable, tmux session exists, provider CLIs on PATH. Auto-fix mode installs hooks, kills orphaned processes.
- **`status_cmd.py`** — `ccgram status`. Shows running state (tmux session, bound topics, session count) without needing a Telegram bot token.
- **`msg_cmd.py`** (~545 lines) — `ccgram msg` group (covered in `inter-agent-messaging/design.md`).
- **`hook.py`** (~652 lines) — `ccgram hook --install / --uninstall / --status`, and the actual hook entry invoked by Claude Code. Reads stdin JSON, writes to `session_map.json` and `events.jsonl`, shells out to the right provider-specific parser.

## Encapsulated Knowledge

- **Doctor diagnostic checks** — `doctor_cmd.py` owns the list of validations and their `--fix` counterparts.
- **Hook install surface** — `hook.py` knows where `~/.claude/settings.json` lives, how to merge the ccgram hook entries without clobbering user entries, how to roll back on error.
- **Hook wire format** — `hook.py` parses stdin JSON, dispatches to `ClaudeProvider.parse_hook_payload`, writes the append-only `events.jsonl` line.

## Subdomain Classification

**Supporting.** Stable CLI surface. Hook install surface gets the most churn as new Claude Code event types are added.

## Integration Contracts

### Inbound

| From                                                                    | Kind                      |
| ----------------------------------------------------------------------- | ------------------------- |
| User → `ccgram doctor` / `status` / `msg` / `hook`                      | CLI                       |
| Claude Code → `ccgram hook` via `~/.claude/settings.json` configuration | Process pipe (stdin JSON) |

### Outbound

| To                                                           | Kind     |
| ------------------------------------------------------------ | -------- |
| `session_manager` (minimal — no bot running)                 | Contract |
| `tmux_manager.list_windows` / session check                  | Contract |
| `session_map_sync.write_entry(...)`                          | Contract |
| `events.jsonl` append-only file                              | File I/O |
| `~/.claude/settings.json` (hook install/uninstall)           | File I/O |
| `providers.registry.get_provider` (for hook payload parsing) | Contract |

## Change Vectors

- **New doctor check** — `doctor_cmd.py`.
- **New hook event type** — add parser branch in `hook.py`, append matching `events.jsonl` schema.
- **New hook install target** (e.g., a non-standard Claude config dir) — `hook.py` respects `CLAUDE_CONFIG_DIR`.
- **New CLI subcommand** — `cli.py` (bot composition root).

## Testability Goals

- **Unit-test `doctor_cmd.check_hooks_installed`** with fixture settings.json.
- **Unit-test `hook.handle_stdin_payload`** with fixture hook JSON — verify correct `session_map.json` entry is written.
- **Unit-test `hook.install` / `uninstall`** with a tmpfs fixture settings.json — verify merge-in-place, verify uninstall preserves user entries.
- **Integration-test `ccgram doctor`** — real process, real filesystem, no bot token.
- **Unit-test `status_cmd`** with mocked `session_manager` — verify output formatting.
