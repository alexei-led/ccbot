# Plan: /send Command — Send Files from Agent Filesystem to Telegram

## Overview

Implement a `/send` Telegram command that allows users to send files from the agent's
working directory (on the machine running ccgram) to the Telegram chat. The complement
to file_handler.py which handles uploading FROM Telegram TO the agent.

Key capabilities:

- Browse the agent session's cwd via an inline keyboard file browser
- Search files by glob pattern (pathspec-powered)
- Security validation: files must stay within the session cwd (no path traversal)
- Upload matching files as Telegram documents with progress feedback
- Provider-specific toolbar integration

## Context

This is the reverse of the existing `file_handler.py` upload flow. Instead of the user
sending files to Claude, this lets Claude/agent output files be retrieved back via Telegram.

## Success Criteria

- [ ] `/send` command shows a file browser rooted at the session's cwd
- [ ] User can navigate directories and select files to send
- [ ] User can type a glob pattern (e.g. `*.py`, `**/*.log`) to search
- [ ] Security: only files within session cwd can be sent (path traversal blocked)
- [ ] Files are sent as Telegram documents, up to 50 MB limit
- [ ] `make check` passes (fmt + lint + typecheck + test)

---

### Task 1: Add pathspec dependency

- [x] Add `pathspec>=0.12` to `[project.dependencies]` in `pyproject.toml`
- [x] Run `uv lock` to update `uv.lock`
- [x] Verify `import pathspec` works in the project environment
- [x] Write a minimal smoke test confirming `pathspec.PathSpec.from_lines("gitignore", ["*.py"])` matches `foo.py`

### Task 2: Security validation module

- [x] Create `src/ccgram/send_security.py` with `validate_send_path(path, cwd) -> bool`
- [x] Must resolve symlinks and verify the resolved path is within `cwd.resolve()`
- [x] Reject `.ccgram-uploads/` directory entries (reserved for inbound uploads)
- [x] Reject hidden files whose names start with `.` if configured (optional, default allow)
- [x] Write unit tests in `tests/ccgram/test_send_security.py`

### Task 3: File search and listing utilities

- [ ] Create `src/ccgram/send_files.py` with:
  - `list_dir(path, cwd) -> list[FileEntry]` — list files/dirs within cwd, sorted (dirs first)
  - `search_glob(pattern, cwd) -> list[FileEntry]` — pathspec glob search within cwd
  - `FileEntry` dataclass: `name`, `path`, `is_dir`, `size`
- [ ] Max results: 50 files for listing, 20 for glob search
- [ ] Write unit tests in `tests/ccgram/test_send_files.py`

### Task 4: File browser and search result keyboards

- [ ] Add `CB_SEND_*` constants to `handlers/callback_data.py`
- [ ] Create `src/ccgram/handlers/send_browser.py` with keyboard builders:
  - `build_send_browser(path, cwd, page) -> InlineKeyboardMarkup`
  - `build_send_results(entries, query) -> InlineKeyboardMarkup`
- [ ] Items per page: 8 files, with Previous/Next pagination
- [ ] Each file button: `📄 filename (size)` or `📁 dirname/`
- [ ] Write unit tests in `tests/ccgram/test_send_browser.py`

### Task 5: /send command handler and file upload

- [ ] Create `src/ccgram/handlers/send_command.py` with:
  - `send_command(update, context)` — `/send [pattern]` handler
  - If no pattern: show directory browser
  - If pattern provided: run glob search, show results keyboard
  - `_do_send_file(window_id, path, message)` — download and send file as document
- [ ] Validate file against security module before sending
- [ ] Reply with progress (ChatAction.UPLOAD_DOCUMENT), then send file
- [ ] Write unit tests in `tests/ccgram/test_send_command.py`

### Task 6: File browser callbacks

- [ ] Create `src/ccgram/handlers/send_callbacks.py` with `@register` handlers:
  - `CB_SEND_NAV` — navigate to subdirectory
  - `CB_SEND_UP` — go to parent directory
  - `CB_SEND_PAGE` — pagination
  - `CB_SEND_FILE` — select and send file
  - `CB_SEND_CANCEL` — cancel browser
- [ ] Write unit tests in `tests/ccgram/test_send_callbacks.py`

### Task 7: Provider-specific toolbar

- [ ] Add "📤 Send file" button to provider toolbar (screenshot_callbacks.py or polling_strategies.py)
- [ ] Only show for Claude/Codex/Gemini providers (not Shell)
- [ ] Callback opens the send browser for current window's cwd
- [ ] Write unit tests for toolbar button presence per provider

### Task 8: Wire into bot and integration test

- [ ] Register `/send` handler in `bot.py` (CommandHandler)
- [ ] Register send_callbacks in `bot.py` via callback_registry
- [ ] Add integration test in `tests/integration/test_send_dispatch.py`
- [ ] Test: dispatch `/send` update, verify browser keyboard appears

### Task 9: Verify acceptance criteria

- [ ] Run `make check` — must be green
- [ ] Manual test: `/send` shows file browser in a real topic [x] manual test (skipped - not automatable)
- [ ] Manual test: typing a glob pattern returns results [x] manual test (skipped - not automatable)
- [ ] Manual test: selecting a file sends it as a Telegram document [x] manual test (skipped - not automatable)

### Task 10: Update documentation

- [ ] Update CLAUDE.md: add `/send` to handler inventory table
- [ ] Update CLAUDE.md: add `send_security.py` and `send_files.py` to core modules table
- [ ] Update CLAUDE.md: add `send_command.py`, `send_browser.py`, `send_callbacks.py` to handlers table
