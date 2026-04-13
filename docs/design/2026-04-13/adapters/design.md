# Adapters (tmux + Terminal Parsing)

## Functional Responsibilities

Thin wrappers over external libraries that handle: (1) tmux command execution, and (2) terminal text parsing (pyte VT100 emulator, JSONL transcript parsing).

Files:

- **`tmux_manager.py`** (~1135 lines) — `TmuxManager` + `send_to_window` helper. Owns `list_windows`, `find_window_by_id`, `create_window`, `kill_window`, `send_keys`, `capture_pane`, `list_panes`, `send_keys_to_pane`. Dual-strategy: `libtmux` for normal ops, `subprocess` fallback for foreign windows (emdash) and operations libtmux doesn't support.
- **`terminal_parser.py`** (~750 lines) — interactive UI detection, spinner parsing, separator detection, high-level `parse_terminal_status` used by provider status detection.
- **`screen_buffer.py`** (~200 lines) — `ScreenBuffer` pyte wrapper. Converts raw ANSI pane text to clean lines.
- **`transcript_parser.py`** (~765 lines) — `TranscriptParser` for Claude JSONL: parses entries, pairs `tool_use` ↔ `tool_result`, builds `build_response_parts` output for the message queue.

## Encapsulated Knowledge

- **Tmux CLI quirks** — only `tmux_manager.py` knows about `send-keys -t`, `-H` for literal bytes, `respawn-window`, `pipe-pane`, the `@{id}` vs. `name` addressing rules, and the subprocess fallback for foreign sessions.
- **pyte configuration** — `screen_buffer.py` owns the screen dimensions, how to feed bytes, how to extract the rendered grid.
- **Interactive UI detection heuristics** — `terminal_parser.py` owns the regex patterns and visual cues that indicate "the agent is waiting on an AskUserQuestion / ExitPlanMode / Permission prompt".
- **Tool use/result pairing** — `transcript_parser.py` owns the algorithm that walks a window of parsed entries and pairs tool_use_id references across messages.

## Subdomain Classification

**Supporting** (tmux_manager, screen_buffer) — stable wrapper patterns.
**Generic + wrapper** (terminal_parser, transcript_parser) — thin logic over pyte and JSONL, mostly stable except when a new Claude tool format lands.

## Integration Contracts

### Inbound

| From                                                                          | Kind     |
| ----------------------------------------------------------------------------- | -------- |
| All handler modules → `tmux_manager.send_keys / capture_pane / list_*`        | Contract |
| `polling_strategies.parse_with_pyte` → `screen_buffer.ScreenBuffer.feed(...)` | Contract |
| `providers/claude.py` → `transcript_parser.TranscriptParser(...)`             | Contract |
| `providers/claude.py` → `terminal_parser.parse_terminal_status(...)`          | Contract |
| `shell_capture.py` → `terminal_parser.detect_separator(...)`                  | Contract |

### Outbound

- `libtmux.Server / Session / Window` (library)
- `subprocess.run` (stdlib)
- `pyte.Screen`, `pyte.ByteStream` (library)
- `json.loads` / `json.JSONDecodeError` (stdlib)

## Change Vectors

- **New tmux operation** — add a method to `TmuxManager`; callers stay unchanged.
- **New interactive UI pattern** — add to `terminal_parser` detection heuristics.
- **New Claude tool output type** — update `TranscriptParser.build_response_parts` (where provider-layer parsing hands off to display-layer formatting).
- **New pyte version** — localised to `screen_buffer.py`.

## Testability Goals

- **Unit-test `TranscriptParser`** with fixture JSONL (one entry per scenario).
- **Unit-test `terminal_parser.parse_terminal_status`** with fixture pane strings (idle, active, interactive-UI, spinner-present).
- **Unit-test `ScreenBuffer.feed + render`** with fixture ANSI bytes.
- **Integration-test `TmuxManager` against a real tmux server** — covered by `tests/integration/`.
- **Mock `libtmux` at the `TmuxManager` boundary** — tests for handlers don't need a real tmux server.
