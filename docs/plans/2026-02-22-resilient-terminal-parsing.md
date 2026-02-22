# Resilient Terminal Parsing with pyte

## Overview

Replace fragile regex-based terminal screen scraping with pyte (VT100 terminal emulator) for status detection and interactive UI parsing. Fix broken Gemini transcript parsing. Make spinner detection version-resilient via Unicode category matching instead of hardcoded character sets.

## Context

- Files involved: `src/ccbot/terminal_parser.py`, `src/ccbot/providers/base.py`, `src/ccbot/providers/claude.py`, `src/ccbot/providers/gemini.py`, `src/ccbot/providers/_jsonl.py`, `src/ccbot/handlers/status_polling.py`, `src/ccbot/tmux_manager.py`, `src/ccbot/session_monitor.py`
- Related patterns: Provider protocol already delegates `parse_terminal_status()` per-provider; `tmux_manager.py` already uses libtmux; `terminal_parser.py` is the central parsing module
- Dependencies: Add `pyte>=0.8.2` (pure-Python VT100 emulator, no C dependencies)

## Current Problems

1. **Hardcoded spinner chars** (`STATUS_SPINNERS` frozenset) — silently breaks when Claude Code changes spinner set
2. **Fixed scan windows** (bottom 15 lines for status, last 10 for chrome) — breaks on large terminals or layout changes
3. **Two-separator assumption** — version-coupled to Claude Code chrome layout
4. **Gemini transcript fundamentally broken** — single JSON file read line-by-line, `json.loads` per line always fails (returns None)
5. **Regex patterns coupled to exact UI text** — checkbox chars, exact wording, arrow chars
6. **No screen dimensions awareness** — regex patterns don't know the actual terminal dimensions

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Add pyte dependency and create ScreenBuffer abstraction

**Files:**

- Modify: `pyproject.toml` (add `pyte>=0.8.2`)
- Create: `src/ccbot/screen_buffer.py`

- [x] Add `pyte>=0.8.2` to `pyproject.toml` dependencies
- [x] Run `uv sync` to install
- [x] Create `src/ccbot/screen_buffer.py` with a `ScreenBuffer` class that wraps pyte:
  - `__init__(columns: int, rows: int)` — create pyte Screen + Stream
  - `feed(raw_text: str)` — feed captured pane text into pyte stream
  - `display` property — returns list of rendered lines (from `screen.display`)
  - `cursor_row` / `cursor_col` properties — expose cursor position
  - `get_line(row: int)` — get a specific line by index
  - `bottom_lines(n: int)` — get last N lines efficiently
  - `find_separator_rows()` — scan for rows that are all `─` chars (separator detection)
  - `reset()` — clear screen state for reuse
- [x] Write tests for ScreenBuffer: feed ANSI text, verify clean rendered output, separator detection, cursor position
- [x] Run `make check` - must pass

### Task 2: Version-resilient spinner detection via Unicode categories

**Files:**

- Modify: `src/ccbot/terminal_parser.py`

- [x] Add `is_likely_spinner(char: str) -> bool` function using `unicodedata.category()`: match Symbol Other (So), Symbol Math (Sm), Punctuation Other (Po), and Braille Patterns — but exclude known non-spinner chars (`─`, `│`, box-drawing range U+2500-U+257F, common text chars)
- [x] Keep `STATUS_SPINNERS` frozenset as a fast-path (check frozenset first, fall back to Unicode category)
- [x] Update `parse_status_line()` to use `is_likely_spinner()` instead of `candidate[0] in STATUS_SPINNERS`
- [x] Write tests: existing spinners still detected, new braille spinners (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) detected, non-spinners (`─`, `>`, letters) rejected
- [x] Run `make check` - must pass

### Task 3: Adaptive separator/chrome detection (no hardcoded line counts)

**Files:**

- Modify: `src/ccbot/terminal_parser.py`
- Modify: `src/ccbot/screen_buffer.py`

- [x] Add `find_chrome_boundary(lines: list[str]) -> int | None` to `terminal_parser.py` that finds the topmost separator by scanning from the bottom upward (no fixed 10 or 15 line limit — scan all lines, stop at first non-chrome content above a separator)
- [x] Update `parse_status_line()` to use `find_chrome_boundary()` instead of the hardcoded `max(len(lines) - 16, -1)` range
- [x] Update `strip_pane_chrome()` to use `find_chrome_boundary()` instead of scanning only last 10 lines
- [x] Add an optional `pane_rows: int | None = None` parameter to `parse_status_line()` — when provided, use it to limit the separator scan to the bottom 40% of the screen (optimization, not correctness)
- [x] Write tests: status detection works with 24-row terminal, 50-row terminal, 100-row terminal; chrome stripping handles extra padding below separators
- [x] Run `make check` - must pass

### Task 4: pyte-based screen parsing for interactive UI detection

**Files:**

- Modify: `src/ccbot/terminal_parser.py`
- Modify: `src/ccbot/screen_buffer.py`

- [x] Add `parse_from_screen(screen: ScreenBuffer) -> InteractiveUIContent | None` to `terminal_parser.py` that uses the ScreenBuffer to extract interactive UI content:
  - Uses rendered lines from `screen.display` (ANSI-stripped by pyte)
  - Uses cursor position to identify the input/prompt area
  - Falls back to existing `extract_interactive_content()` regex patterns on the rendered lines
- [x] Add `parse_status_from_screen(screen: ScreenBuffer) -> str | None` that uses rendered lines + cursor position for more robust status line detection
- [x] Update `extract_interactive_content()` to accept `list[str]` (lines) as an alternative to raw `pane_text` string — allows callers to pass pyte-rendered lines directly
- [x] Write tests: feed real Claude Code pane captures (with ANSI escapes) through pyte, verify UI detection matches regex-only results
- [x] Run `make check` - must pass

### Task 5: Integrate pyte into status polling pipeline

**Files:**

- Modify: `src/ccbot/handlers/status_polling.py`
- Modify: `src/ccbot/tmux_manager.py`

- [ ] Add `capture_pane_raw(window_id: str) -> tuple[str, int, int]` to TmuxManager that returns `(raw_text_with_escapes, columns, rows)` using libtmux's `capture_pane` with escape sequences enabled and pane dimension query
- [ ] In `status_polling.py`, maintain a `dict[str, ScreenBuffer]` keyed by window_id — one ScreenBuffer per tracked window
- [ ] When polling, use `capture_pane_raw()` to get raw text, feed it into the per-window ScreenBuffer, then call `parse_status_from_screen()` and `parse_from_screen()`
- [ ] Fall back to current regex-based parsing if pyte parsing returns None (defense in depth)
- [ ] Write tests: mock TmuxManager to return raw capture with ANSI, verify ScreenBuffer correctly feeds to status/UI parsing
- [ ] Run `make check` - must pass

### Task 6: Fix Gemini single-JSON transcript parsing

**Files:**

- Modify: `src/ccbot/providers/gemini.py`
- Modify: `src/ccbot/session_monitor.py`

- [ ] In `GeminiProvider`, override a new method `read_transcript_file(file_path: Path, last_offset: int) -> tuple[list[dict], int]` that reads the entire JSON file (not line-by-line), parses the top-level object, extracts the `messages` array, and returns only messages newer than what was seen last (tracked by message count, not byte offset)
- [ ] Add `supports_incremental_read` to `ProviderCapabilities` (default True, set False for Gemini) — the monitor uses this to choose between line-by-line JSONL reading and whole-file JSON reading
- [ ] In `session_monitor._read_new_lines()`: check `provider.capabilities.supports_incremental_read`; if False, delegate to `provider.read_transcript_file()` instead of the line-by-line loop
- [ ] Remove the broken `parse_transcript_line()` override in GeminiProvider (the base class version is unused when whole-file reading is active)
- [ ] Write tests: create a sample Gemini JSON transcript, verify messages are correctly extracted and incremental tracking works (new messages detected after file update)
- [ ] Run `make check` - must pass

### Task 7: Verify acceptance criteria

- [ ] Manual test: verify Claude Code spinner detection works with current CC version
- [ ] Manual test: verify interactive UI detection (AskUserQuestion, ExitPlanMode) works via pyte path
- [ ] Manual test: if Gemini CLI available, verify transcript monitoring detects new messages
- [ ] Run `make check` (fmt + lint + typecheck + test)
- [ ] Verify test coverage meets 80%+

### Task 8: Update documentation

- [ ] Update CLAUDE.md if any internal patterns changed (screen_buffer module, provider capabilities)
- [ ] Update `.claude/rules/architecture.md` to add ScreenBuffer to the system diagram
- [ ] Move this plan to `docs/plans/completed/`
