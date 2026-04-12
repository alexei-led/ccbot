# /send Command + Provider-Specific Toolbar

## Overview

Two related features:

**1. `/send` command** — deliver files from agent workspace to Telegram topic. Three modes:

- Exact path: `/send docs/arch.png` → immediate upload
- Search/glob: `/send *.png` or `/send arch` → find matches, pick if multiple
- Browse: `/send` (no args) → inline keyboard file browser at CWD

**2. Provider-specific toolbar** — redesign `/toolbar` with universal row 1 + provider-specific row 2:

```
Claude:  📷 Screenshot │ ⏹ Ctrl-C │ 📺 Live  │ 📤 Send
         🔀 Mode       │ 💭 Think  │ ⎋ Esc    │ ✖ Close

Codex:   📷 Screenshot │ ⏹ Ctrl-C │ 📺 Live  │ 📤 Send
         ⎋ Esc         │ ⏎ Enter  │ ⇥ Tab    │ ✖ Close

Gemini:  📷 Screenshot │ ⏹ Ctrl-C │ 📺 Live  │ 📤 Send
         🔀 Mode       │ 🅨 YOLO   │ ⎋ Esc    │ ✖ Close

Shell:   📷 Screenshot │ ⏹ Ctrl-C │ 📺 Live  │ 📤 Send
         ⏎ Enter       │ ^D EOF    │ ^Z Susp  │ ✖ Close
```

Row 1 is universal. Row 2 is the most useful shortcuts per provider.

## Context

**Existing infrastructure (no changes needed):**

- `send_document` / `send_photo` — already used for screenshots (`bot.py:412`, `screenshot_callbacks.py:294,517`)
- CWD resolution — `session_manager.get_window_state(window_id).cwd`
- Thread→window — `thread_router.resolve_window_for_thread(user_id, thread_id)`
- Command registration — one import + one `add_handler(CommandHandler(...))` in `bot.py`
- Inline keyboard patterns — integer-indexed callbacks + `user_data` cache (`directory_browser.py`)
- Path validation — `resolve().relative_to(cwd.resolve())` pattern from `file_handler.py:78-84`
- Toolbar — `build_toolbar_keyboard(window_id)` in `screenshot_callbacks.py:223-259`
- Quick keys — `KEYS_SEND_MAP` in `screenshot_callbacks.py:64-74`, sends tmux key names via `tmux_manager.send_keys()`
- Provider resolution — `get_provider_for_window(window_id)` in `providers/__init__.py`
- Error handling — `safe_reply` + `try/except TelegramError`

**New dependency:** `pathspec` — pure Python gitignore parser (~10KB), fallback when `git check-ignore` unavailable.

**Stdlib only for the rest:**

- Path traversal: `Path.resolve()` + `is_relative_to()` (pathlib)
- Gitleaks: `tomllib` (stdlib 3.11+) + `re` to parse `.gitleaks.toml`
- Secret patterns: `fnmatch` against hardcoded pattern list

**Key constraints:**

- Telegram bot upload limit: 50 MB
- Callback data limit: 64 bytes (integer indices for file browser, short prefixes for toolbar)
- `Shift+Tab` has no standard tmux key name — send `\e[Z` escape sequence
- `Ctrl+Y` for Gemini YOLO — send `C-y` via tmux

## Security Model

All file access is **project-scoped and deny-by-default**:

### Path containment

- `Path.resolve()` + `is_relative_to(cwd.resolve())` — rejects `../`, symlinks escaping CWD, absolute paths outside CWD
- File browser bounded to CWD — parent navigation stops at project root
- Only regular files sendable (no dirs, devices, sockets, FIFOs)

### Denied files

- **Hidden files/dirs**: any path component starting with `.`
- **Secret patterns** (fnmatch, case-insensitive): `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*credential*`, `*secret*`, `*.token`
- **Gitleaks**: if `.gitleaks.toml` exists, parse `[[rules]]` path regexes via `tomllib` + `re`
- **Gitignored**: `git check-ignore -q` primary, `pathspec` fallback for non-git repos
- **State files**: reuse `assert_sendable()` from `utils.py:316-327`

### Excluded directories (never listed, never searched)

All hidden dirs + `node_modules`, `__pycache__`, `.venv`, `venv`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `dist`, `build`, `.eggs`, `*.egg-info`, `.cache`, `.npm`, `.yarn`, `target`, `.gradle`

### Error messages (specific)

- "File is outside project directory" (traversal)
- "Hidden files cannot be sent" (dotfiles)
- "File appears to contain credentials — denied" (secret match)
- "File is gitignored" (gitignore)
- "File too large: 127 MB (limit: 50 MB)" (with actual size)
- "Not a regular file" (dir, device, etc.)
- "File not found: docs/missing.png" (with path)

## Configuration

| Setting      | Env Var                    | Default |
| ------------ | -------------------------- | ------- |
| Search depth | `CCGRAM_SEND_SEARCH_DEPTH` | `5`     |
| Max results  | `CCGRAM_SEND_MAX_RESULTS`  | `50`    |

## Development Approach

- **Testing approach**: Regular (implement then test)
- Complete each task fully before moving to the next
- Every task includes tests for code changes
- All tests must pass before starting next task (`make test`)
- Update this plan when scope changes

## Testing Strategy

- **Unit tests**: path validation, search logic, browser construction, security denials, toolbar construction per provider, key sending
- **Integration tests**: PTB Application + `_do_post` patch for dispatch routing
- Test files: `tests/ccgram/handlers/test_send_security.py`, `tests/ccgram/handlers/test_send_command.py`, `tests/ccgram/handlers/test_send_callbacks.py`

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- ➕ prefix for discovered tasks
- ⚠️ prefix for blockers

## Solution Overview

### /send dispatch

```
no args          → file browser at CWD
contains * or ?  → glob search in CWD
otherwise        → try exact path; if not found, substring search
```

### Security pipeline (every file, every mode)

```
resolve → containment → hidden → secret → gitleaks → gitignore → assert_sendable → size → is_file → send
```

### Toolbar — provider resolution

`build_toolbar_keyboard(window_id)` calls `get_provider_for_window(window_id)` to get provider name, then builds row 2 from a provider-specific button list. Row 1 is shared. Callback handlers for new keys (`Mode`, `Think`, `YOLO`, `EOF`, `Suspend`) added to screenshot_callbacks dispatch.

### Key sending for new toolbar buttons

| Button           | tmux key               | Notes                                                                                                       |
| ---------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------- |
| Mode (Shift+Tab) | `\e[Z` escape sequence | `send_keys(literal=False)` won't work; need raw escape via `send_keys("\x1b[Z", literal=True, enter=False)` |
| Think (Tab)      | `Tab`                  | Already in KEYS_SEND_MAP                                                                                    |
| YOLO (Ctrl+Y)    | `C-y`                  | Standard tmux Ctrl key                                                                                      |
| EOF (Ctrl+D)     | `C-d`                  | Standard tmux Ctrl key                                                                                      |
| Suspend (Ctrl+Z) | `C-z`                  | Standard tmux Ctrl key                                                                                      |

## Implementation Steps

### Task 1: Add pathspec dependency

**Files:**

- Modify: `pyproject.toml`

- [x] Add `pathspec>=0.12.0` to `[project] dependencies`
- [x] Run `uv sync` to install
- [x] Verify import works: `python -c "import pathspec"`

### Task 2: Security validation module

**Files:**

- Modify: `src/ccgram/config.py`
- Create: `src/ccgram/handlers/send_security.py`
- Create: `tests/ccgram/handlers/test_send_security.py`

- [x] Add `send_search_depth` and `send_max_results` to config with env var loading (`CCGRAM_SEND_SEARCH_DEPTH` default 5, `CCGRAM_SEND_MAX_RESULTS` default 50)
- [x] Create `send_security.py` with constants: `_SECRET_PATTERNS` (fnmatch list), `_EXCLUDED_DIRS` (frozenset), `_TELEGRAM_FILE_LIMIT` (50 MB)
- [x] Implement `is_path_contained(path: Path, root: Path) -> bool` — resolve both, use `is_relative_to`
- [x] Implement `is_hidden(path: Path, root: Path) -> bool` — check any component relative to root starts with `.`
- [x] Implement `matches_secret_pattern(path: Path) -> str | None` — fnmatch case-insensitive, return matching pattern or None
- [x] Implement `is_gitignored(path: Path, cwd: Path) -> bool` — try `git check-ignore -q` subprocess first; on failure (not a git repo, git not found), fall back to `pathspec`: walk parent dirs collecting `.gitignore` files, build `PathSpec`, match. Return False if both fail
- [x] Implement `check_gitleaks_rules(path: Path, cwd: Path) -> str | None` — if `.gitleaks.toml` exists, `tomllib.load()`, iterate `rules`, match `path` regexes. Return rule id/description or None
- [x] Implement `validate_sendable(path: Path, cwd: Path) -> str | None` — full pipeline returning specific error message or None
- [x] Implement `is_excluded_dir(name: str) -> bool` — check `_EXCLUDED_DIRS` + starts with `.`
- [x] Write tests for `is_path_contained` (inside, outside, `..` traversal, symlink escape, boundary at root)
- [x] Write tests for `is_hidden` (dotfile, nested dotdir, non-hidden, root itself)
- [x] Write tests for `matches_secret_pattern` (`.env`, `*.pem`, `*.key`, `credential.json`, normal file)
- [x] Write tests for `is_gitignored` — mock subprocess for git path (ignored, not ignored, git error triggering pathspec fallback, non-git with .gitignore file)
- [x] Write tests for `check_gitleaks_rules` (toml with rules, no toml, matching rule, non-matching, malformed toml)
- [x] Write tests for `validate_sendable` (each denial reason, clean file passes, correct error strings)
- [x] Write tests for `is_excluded_dir` (node_modules, **pycache**, .git, .venv, normal dir)
- [x] Run `make test` — must pass before Task 3

### Task 3: File search and listing utilities

**Files:**

- Create: `src/ccgram/handlers/send_command.py` (utilities only)

- [x] Create `send_command.py` with module docstring, imports, logger, `_IMAGE_EXTENSIONS` frozenset, `_ITEMS_PER_PAGE = 8`
- [x] Implement `_is_image(path: Path) -> bool` — check suffix against `_IMAGE_EXTENSIONS`
- [x] Implement `_find_files(cwd: Path, pattern: str) -> list[Path]` — if `*` or `?` in pattern: `Path.rglob` with depth check; else try exact relative path, then substring rglob `*{pattern}*`. Skip `is_excluded_dir` during traversal, `validate_sendable` on results. Cap at `config.send_max_results`, sort by mtime descending
- [x] Implement `_list_directory(path: Path, cwd: Path) -> tuple[list[Path], list[Path]]` — iterdir, split dirs/files, filter excluded dirs and denied files, sort alphabetically
- [x] Implement `_format_file_label(path: Path, cwd: Path) -> str` — relative path + human-readable size (B/KB/MB), truncate path portion to fit button label
- [x] Add tests for `_is_image` to `test_send_command.py`
- [x] Add tests for `_find_files` (exact, glob, substring, depth limit, excluded dirs, denied files filtered, max cap, empty, sort order)
- [x] Add tests for `_list_directory` (mixed content, noise dirs excluded, hidden excluded, denied files excluded, alphabetical sort)
- [x] Add tests for `_format_file_label` (short path, long path truncation, B/KB/MB sizes)
- [x] Run `make test` — must pass before Task 4

### Task 4: File browser and search result keyboards

**Files:**

- Modify: `src/ccgram/handlers/send_command.py` (add builders)
- Modify: `src/ccgram/handlers/callback_data.py`
- Modify: `src/ccgram/handlers/user_state.py`

- [x] Add callback constants: `CB_SEND_FILE = "sf:f:"`, `CB_SEND_DIR = "sf:d:"`, `CB_SEND_PAGE = "sf:pg:"`, `CB_SEND_UP = "sf:up"`, `CB_SEND_CANCEL = "sf:x"`
- [x] Add user_state keys: `SEND_PATH_KEY`, `SEND_PAGE_KEY`, `SEND_ITEMS_KEY`, `SEND_WINDOW_ID_KEY`, `SEND_CWD_KEY`
- [x] Implement `build_file_browser(current_path: Path, cwd: Path, page: int) -> tuple[str, InlineKeyboardMarkup, list[Path]]` — 2-per-row layout with `📁` dirs and `📄`/`🖼️` files, `_ITEMS_PER_PAGE` pagination, `◀ N/M ▶` row, parent row (disabled text at CWD root), cancel button. Return items list for caching
- [x] Implement `build_search_results(matches: list[Path], cwd: Path) -> tuple[str, InlineKeyboardMarkup, list[Path]]` — same layout, mtime-sorted, file labels with size
- [x] Add tests for `build_file_browser` (pagination math, empty dir, mixed dirs+files, parent disabled at root, parent enabled below, button labels, callback data format)
- [x] Add tests for `build_search_results` (single page, multi-page, empty list)
- [x] Run `make test` — must pass before Task 5

### Task 5: /send command handler and file upload

**Files:**

- Modify: `src/ccgram/handlers/send_command.py` (add handler + upload)

- [x] Implement `_upload_file(bot, chat_id: int, thread_id: int, path: Path) -> None` — `send_photo` for `_is_image`, `send_document` for rest, `filename=path.name`, catch `TelegramError` and re-raise with user message
- [x] Implement `send_command(update, context)` — guards: `update.message` → `is_user_allowed` → `get_thread_id` → `resolve_window_for_thread` → `get_window_state.cwd` exists as dir
- [x] No args dispatch: `build_file_browser(cwd, cwd, 0)`, cache items + state keys in `user_data`, reply with keyboard
- [x] Glob dispatch (pattern has `*` or `?`): `_find_files(cwd, pattern)` → single match: `validate_sendable` + upload → multiple: `build_search_results` + keyboard → zero: error with pattern
- [x] Text dispatch: resolve `cwd / text` → if exists and `validate_sendable` OK: upload → else `_find_files(cwd, text)` → same single/multiple/zero handling → if still zero: "File not found: {text}"
- [x] Add tests for `_upload_file` (image → send_photo called, non-image → send_document, TelegramError handling)
- [x] Add tests for `send_command` — no args → browser reply, glob → search, exact path → upload, unbound topic error, auth error, CWD gone error, traversal error, secret file error, too-large error, not-found error
- [x] Run `make test` — must pass before Task 6

### Task 6: File browser callbacks

**Files:**

- Create: `src/ccgram/handlers/send_callbacks.py`
- Create: `tests/ccgram/handlers/test_send_callbacks.py`

- [x] Create `send_callbacks.py` with module docstring, imports, logger
- [x] Implement `_clear_send_state(context)` — pop all `SEND_*` keys from `user_data`
- [x] Handle `CB_SEND_FILE`: index from callback data → look up in cached `SEND_ITEMS_KEY` → `validate_sendable` → `_upload_file` → `_clear_send_state` → `query.answer("Sent")` → delete browser message
- [x] Handle `CB_SEND_DIR`: index → look up dir → verify `is_path_contained(dir, cwd)` → `build_file_browser(dir, cwd, 0)` → update cache → `edit_message_text` with new keyboard
- [x] Handle `CB_SEND_PAGE`: parse page number → `build_file_browser(current_path, cwd, page)` → update cache → edit message
- [x] Handle `CB_SEND_UP`: if `current_path == cwd` → `query.answer("Already at project root")` → return. Else `current_path.parent` → rebuild browser
- [x] Handle `CB_SEND_CANCEL`: `_clear_send_state` → delete message or edit to "Cancelled"
- [x] Stale guard: check `SEND_WINDOW_ID_KEY` matches `thread_router.resolve_window_for_thread` for current topic
- [x] Register via `@register(CB_SEND_FILE, CB_SEND_DIR, CB_SEND_PAGE, CB_SEND_UP, CB_SEND_CANCEL)`
- [x] Write tests: file select → validate + upload + cleanup, dir navigate → rebuild, page → rebuild, parent clamped at CWD, cancel → cleanup, stale guard rejects, denied file → error answer not upload, index out of bounds → error
- [x] Run `make test` — must pass before Task 7

### Task 7: Provider-specific toolbar

**Files:**

- Modify: `src/ccgram/handlers/callback_data.py` (add new CB*TOOLBAR*\* constants)
- Modify: `src/ccgram/handlers/screenshot_callbacks.py` (rebuild `build_toolbar_keyboard`, add handlers)

- [x] Add callback constants: `CB_TOOLBAR_SEND = "tb:send:"`, `CB_TOOLBAR_MODE = "tb:mode:"`, `CB_TOOLBAR_THINK = "tb:think:"`, `CB_TOOLBAR_YOLO = "tb:yolo:"`, `CB_TOOLBAR_EOF = "tb:eof:"`, `CB_TOOLBAR_SUSPEND = "tb:susp:"`
- [x] Refactor `build_toolbar_keyboard(window_id)` to accept provider name (resolve via `get_provider_for_window`). Build universal row 1: `📷 Screenshot | ⏹ Ctrl-C | 📺 Live | 📤 Send`. Build provider-specific row 2 from a config dict keyed by provider name
- [x] Claude row 2: `🔀 Mode | 💭 Think | ⎋ Esc | ✖ Close`
- [x] Codex row 2: `⎋ Esc | ⏎ Enter | ⇥ Tab | ✖ Close`
- [x] Gemini row 2: `🔀 Mode | 🅨 YOLO | ⎋ Esc | ✖ Close`
- [x] Shell row 2: `⏎ Enter | ^D EOF | ^Z Susp | ✖ Close`
- [x] Implement `_handle_toolbar_send`: resolve window*id → get CWD → `build_file_browser(cwd, cwd, 0)` → cache state in `user_data` → reply with new message containing browser. Reuses same `SEND*\*`state keys and`send_callbacks` handlers
- [x] Implement `_handle_toolbar_mode`: send `Shift+Tab` as `"\x1b[Z"` via `tmux_manager.send_keys(window_id, "\x1b[Z", literal=True, enter=False)`. Toast: "🔀 Mode cycled"
- [x] Implement `_handle_toolbar_think`: send `Tab` key. Toast: "💭 Think toggled"
- [x] Implement `_handle_toolbar_yolo`: send `C-y` key. Toast: "🅨 YOLO toggled"
- [x] Implement `_handle_toolbar_eof`: send `C-d` key. Toast: "^D Sent"
- [x] Implement `_handle_toolbar_suspend`: send `C-z` key. Toast: "^Z Sent"
- [x] Register all new `CB_TOOLBAR_*` constants in the dispatch table / `@register` decorator
- [x] Update `toolbar_command` in `bot.py` to pass provider context to `build_toolbar_keyboard`
- [x] Write tests for `build_toolbar_keyboard` — verify correct row 2 per provider (claude, codex, gemini, shell), verify row 1 universal across all, verify callback data format
- [x] Write tests for each new handler: mode sends correct escape sequence, think sends Tab, yolo sends C-y, eof sends C-d, suspend sends C-z, send opens file browser
- [x] Run `make test` — must pass before Task 8

### Task 8: Wire into bot and integration test

**Files:**

- Modify: `src/ccgram/bot.py` (import + add_handler for /send)
- Modify: `src/ccgram/handlers/callback_registry.py` (ensure send_callbacks loaded)

- [x] Add import of `send_command` in `bot.py`
- [x] Add `application.add_handler(CommandHandler("send", send_command, filters=_group_filter))`
- [x] Ensure `send_callbacks` is imported in `callback_registry.py`'s `load_handlers()` list
- [x] Write integration test: dispatch `/send` Update through real PTB Application with `_do_post` patch, verify handler reached
- [x] Write integration test: dispatch `/toolbar` Update, verify provider-specific keyboard returned
- [x] Run `make check` (fmt + lint + typecheck + test)

### Task 9: Verify acceptance criteria

**`/send` command:**

- [x] (verified by unit tests) `/send docs/arch.png` uploads file to topic
- [x] (verified by unit tests) `/send *.png` finds and presents matches as keyboard
- [x] (verified by unit tests) `/send arch` finds files by substring
- [x] (verified by unit tests) `/send` (no args) opens file browser bounded to CWD
- [x] (verified by unit tests) Browser navigation: enter dir, parent, pagination, cancel all work
- [x] (verified by unit tests) Browser cannot navigate above CWD (parent disabled/blocked)
- [x] (verified by unit tests) Single search match → immediate upload (no picker)
- [x] (verified by unit tests) Hidden files/dirs not shown in browser or search
- [x] (verified by unit tests) Secret-pattern files denied with specific message
- [x] (verified by unit tests) Gitignored files denied (git check-ignore path)
- [x] (verified by unit tests) Gitignored files denied (pathspec fallback in non-git dir)
- [x] (verified by unit tests) Gitleaks rules respected when `.gitleaks.toml` exists
- [x] (verified by unit tests) Path traversal (`/send ../../etc/passwd`) denied
- [x] (verified by unit tests) File >50MB denied with actual size in message
- [x] (verified by unit tests) Excluded dirs (node_modules, **pycache**) never appear
- [x] (verified by unit tests) Config env vars (`CCGRAM_SEND_SEARCH_DEPTH`, `CCGRAM_SEND_MAX_RESULTS`) work

**Toolbar:**

- [x] (verified by unit tests) `/toolbar` in Claude topic shows Claude-specific row 2 (Mode, Think, Esc, Close)
- [x] (verified by unit tests) `/toolbar` in Codex topic shows Codex-specific row 2 (Esc, Enter, Tab, Close)
- [x] (verified by unit tests) `/toolbar` in Gemini topic shows Gemini-specific row 2 (Mode, YOLO, Esc, Close)
- [x] (verified by unit tests) `/toolbar` in Shell topic shows Shell-specific row 2 (Enter, EOF, Suspend, Close)
- [x] (verified by unit tests) 📤 Send button opens file browser (same as `/send` no args)
- [x] (verified by unit tests) 🔀 Mode sends Shift+Tab escape sequence to tmux
- [x] (verified by unit tests) 💭 Think sends Tab to tmux
- [x] (verified by unit tests) 🅨 YOLO sends Ctrl+Y to tmux
- [x] (verified by unit tests) ^D EOF sends Ctrl+D to tmux
- [x] (verified by unit tests) ^Z Susp sends Ctrl+Z to tmux
- [x] (verified by unit tests) Row 1 identical across all providers
- [x] (verified by unit tests) Run `make check`

### Task 10: [Final] Update documentation

- [x] Add `/send` command to README.md (usage, modes, configuration)
- [x] Add `/send` to CLAUDE.md command reference
- [x] Add `CCGRAM_SEND_SEARCH_DEPTH` and `CCGRAM_SEND_MAX_RESULTS` to CLAUDE.md configuration table
- [x] Update toolbar description in CLAUDE.md (provider-specific, new buttons)
- [x] Add `pathspec` to dependency notes if applicable
- [x] Move this plan to `docs/plans/completed/`

## Post-Completion

**Follow-up features (separate plans):**

- `ccgram msg send self --file` — agent-initiated push to own topic (issue #55)
- Skill update to teach agents about file delivery
- Status keyboard update (currently 4 buttons: Esc, Screenshot, Notify, RC — consider aligning with toolbar redesign)

**Manual verification:**

- Test `/send` with real Telegram bot: all three modes + toolbar button
- Test toolbar per provider: spawn Claude/Codex/Gemini/Shell topics, verify correct buttons
- Test Shift+Tab actually cycles Claude Code permission mode
- Test Ctrl+Y actually toggles Gemini YOLO
- Test security: dotfiles, `.env`, `*.pem`, path traversal, symlinks
- Test `.gitleaks.toml` with path rules
- Test in non-git directory (pathspec fallback)
- Test large file (>50MB) error
- Test various file types (PNG, PDF, ZIP, CSV)
