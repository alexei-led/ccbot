# Directory Browser

## Functional Responsibilities

Interactive UI for choosing a working directory when creating a new Telegram topic, plus provider selection and approval-mode selection. Also handles external window binding (pre-existing tmux windows outside ccgram's control).

Files:

- **`handlers/directory_browser.py`** (~366 lines) — directory listing UI, favorites (starred / MRU), project markers (`.git`, `pyproject.toml`, etc.), pagination, home button.
- **`handlers/directory_callbacks.py`** (~738 lines) — callback handlers for every button in the browser flow: `_handle_fav`, `_handle_star`, `_handle_select`, `_handle_up`, `_handle_home`, `_handle_page`, `_handle_confirm`, `_handle_provider_select`, `_handle_mode_select`, `_handle_cancel`, `_create_window_and_bind`, `_accept_yolo_confirmation`, `_try_install_messaging_skill`.
- **`handlers/window_callbacks.py`** — external tmux window binding (the "pick an existing window" flow for foreign windows).

## Encapsulated Knowledge

- **Directory filtering** — excludes `node_modules`, `.git`, `__pycache__`, `.venv`, `dist`, `build`, etc. Owned by `directory_browser.py`.
- **Project detection** — marker files (`.git`, `pyproject.toml`, `package.json`, `Cargo.toml`) used to identify project roots in the listing. Owned by `directory_browser._PROJECT_MARKERS`.
- **Provider metadata** — per-provider labels and emoji. Owned by `directory_browser._PROVIDER_META`.
- **Window creation flow** — sequence of: create window → set provider → set approval mode → install messaging skill (Claude only) → optionally accept YOLO confirmation → sync display name → bind topic → forward pending message. Owned by `directory_callbacks._create_window_and_bind`.
- **YOLO confirmation handling** — Claude-specific. Currently `directory_callbacks.py:593` hardcodes `provider_name == "claude"`; the refactor replaces this with a `ProviderCapabilities.has_yolo_confirmation` flag.

## Subdomain Classification

**Supporting.** Browser UI is shipped and stable. The `_create_window_and_bind` orchestration is more volatile because it intersects provider setup, messaging-skill installation, and the shell prompt-marker decision.

## Integration Contracts

### Inbound

| From                                                                                                                                         | Kind     |
| -------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `text_handler` (first message in unbound topic) → `topic_orchestration.orchestrate_new_topic` → `directory_browser.build_root_keyboard(...)` | Contract |
| PTB callback dispatcher → `directory_callbacks._dispatch`                                                                                    | Contract |

### Outbound

| To                                                                                                      | Kind     |
| ------------------------------------------------------------------------------------------------------- | -------- |
| `session_manager.view_window` / `set_display_name` / `set_window_provider` / `set_window_approval_mode` | Contract |
| `user_preferences.get_favorites` / `toggle_starred` / `add_recent`                                      | Contract |
| `tmux_manager.create_window(cwd, command)`                                                              | Contract |
| `provider_registry.get_provider(name)` → for capability checks                                          | Contract |
| `shell_prompt_orchestrator.ensure_setup(window_id, "auto")` (after refactor)                            | Contract |
| `msg_skill.install(cwd)` (for Claude windows)                                                           | Contract |

## Change Vectors

- **New project marker** — `_PROJECT_MARKERS` dict.
- **New provider option** — `_PROVIDER_META` + `registry` registration.
- **New approval mode** — add to provider's capability set, update mode-pick keyboard.
- **Change favorites persistence** — `user_preferences.py`.
- **YOLO handling for another provider** — set `has_yolo_confirmation = True` on that provider (after capability flag refactor).

## Refactor Actions (for this design cycle)

1. Replace `if approval_mode == "yolo" and provider_name == "claude":` (L593) with `if approval_mode == "yolo" and provider.capabilities.has_yolo_confirmation:`.
2. Migrate `_handle_confirm` and other read-side calls to `session_manager.view_window(wid)` where possible.

## Testability Goals

- **Unit-test `_PROJECT_MARKERS` detection** — given a synthetic filesystem layout, verify the listing highlights project roots.
- **Unit-test keyboard builders** (`build_root_keyboard`, `build_provider_keyboard`, `build_mode_keyboard`) — pure functions.
- **Integration-test `_create_window_and_bind`** with mocked `tmux_manager.create_window`, mocked `shell_prompt_orchestrator.ensure_setup`, mocked `msg_skill.install`. Verify the ordering of side effects.
- **Unit-test `_accept_yolo_confirmation`** — feed a synthetic pane text showing the bypass-permissions prompt, verify the correct key press is sent.
- **Unit-test favorites flow** with a fresh `UserPreferences` — star, list, delete, verify state.
