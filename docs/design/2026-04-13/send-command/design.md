# Send Command

## Functional Responsibilities

The `/send` command delivers workspace files from the tmux window's CWD to the user's Telegram topic. Four input modes in one command: exact path, glob pattern, substring search, and interactive file browser. A deny-by-default security pipeline enforces containment, hidden-file exclusion, secret patterns, gitleaks rules, gitignore, and size limits.

Files:

- **`handlers/send_command.py`** (~470 lines) — `send_command` entry, `open_file_browser` (public), `_upload_file` (private → should be renamed `upload_file` after refactor), `build_file_browser`, `build_search_results`, `_find_files`, `_walk_filtered`, `_list_directory`, `_format_file_label`, `_pack_into_rows`, `_dispatch_search`, `_cache_browser_state`, `_upload_with_feedback`.
- **`handlers/send_callbacks.py`** (~290 lines) — callbacks for browser navigation: `_handle_file`, `_handle_dir`, `_handle_page`, `_handle_up`, `_handle_cancel`, plus `_clear_send_state`.
- **`handlers/send_security.py`** (~256 lines) — `validate_sendable`, `is_path_contained`, `is_hidden`, `matches_secret_pattern`, `_gitignored_by_pathspec`, `is_gitignored`, `check_gitleaks_rules`, `_check_size_and_type`, `is_excluded_dir`.

## Encapsulated Knowledge

- **Security pipeline order** — only `send_security.py` knows the order: containment → hidden → secret patterns → gitignore → gitleaks → size/type. Each check returns an error string or `None`.
- **Excluded directories** — `send_security.EXCLUDED_DIRS` constant; used by `send_command._walk_filtered` for in-place pruning during directory walk.
- **Secret patterns** — `send_security.SECRET_PATTERNS` glob list (`*.pem`, `*.key`, `*credential*`, etc.).
- **File label formatting** — size suffix, icon selection, truncation to ≤24 chars for callback_data budget — owned by `send_command._format_file_label`.
- **Browser state** — stored in `context.user_data` via `_cache_browser_state` using the `SEND_*` user-state keys defined in `handlers/user_state.py`.

## Subdomain Classification

**Supporting.** Feature just shipped; stabilisation phase. Low volatility except for security pipeline extensions (new secret patterns, new gitleaks rule mappings).

## Integration Contracts

### Inbound

| From                                                                      | Kind                  |
| ------------------------------------------------------------------------- | --------------------- |
| PTB command handler → `send_command(update, context)`                     | Contract              |
| PTB callback dispatcher → `send_callbacks._dispatch`                      | Contract              |
| `toolbar_callbacks._builtin_send` → `send_command.open_file_browser(...)` | Contract (public API) |

### Outbound

| To                                                      | Kind     |
| ------------------------------------------------------- | -------- |
| `send_security.validate_sendable(path, cwd)`            | Contract |
| `session_manager.view_window(wid) → cwd`                | Contract |
| `message_sender.safe_send_photo` / `safe_send_document` | Contract |
| `pathspec` library (for gitignore fallback)             | Library  |
| `subprocess` for `git check-ignore`                     | stdlib   |
| `tomllib` for gitleaks rule parsing                     | stdlib   |

## Change Vectors

- **New secret pattern** — `send_security.SECRET_PATTERNS` list.
- **New excluded directory** — `send_security.EXCLUDED_DIRS`.
- **Change search depth** — `config.send_search_depth`.
- **New file type support (e.g., audio)** — `send_command._upload_file` plus `_is_image` predicate.

## Refactor Actions

1. Promote `_upload_file` → `upload_file` in `send_command.py`. Update the import in `send_callbacks.py`. Remove the private-name leak.
2. Migrate `session_manager.get_window_state(wid).cwd` reads to `session_manager.view_window(wid).cwd`.

## Testability Goals

- **Unit-test `validate_sendable`** with fixture paths — cover every branch (contained, hidden, secret, gitignored, gitleaks, oversized, binary).
- **Unit-test `is_path_contained`** — cover `..` traversal and symlink escape.
- **Unit-test `_format_file_label`** — cover size formatting and truncation edge cases (just under, at, just over the 24-char budget).
- **Unit-test `_find_files`** against a tmpfs fixture.
- **Unit-test `check_gitleaks_rules`** against a fixture `.gitleaks.toml`.
- **Integration-test `send_command`** with a mocked bot, a fake cwd, and a synthetic file — verify the upload path.
- **Integration-test the browser flow** via callback dispatch: navigate into a subdir, page, select a file, verify the upload call.
