# Toolbar Subsystem

## Functional Responsibilities

The `/toolbar` command displays a per-provider inline keyboard whose layout is configurable via TOML (`~/.ccgram/toolbar.toml`). Buttons dispatch to one of three action types: tmux key sequences, literal text + Enter, or a small set of built-in operations (screenshot, Ctrl-C, live view, /send, dismiss). Some buttons are "toggles" whose label reflects the agent's current mode — for example, Claude Code's "Edit/Plan/Full" mode indicator — and the label is refreshed by re-reading pane state after a key press.

Internal file split after refactor:

- **`handlers/toolbar_keyboard.py` (NEW, ~200 lines)** — keyboard rendering and per-window label state. `build_toolbar_keyboard(window_id, provider_name)`, `_make_button`, `_set_action_label`, `_get_action_label`, `_clear_window_labels`, `_window_action_labels` dict, `@topic_state.register("window")` cleanup. Pure UI + state.
- **`handlers/toolbar_callbacks.py` (SLIMMED, ~300 lines)** — callback dispatch only. `handle_toolbar_callback()`, `_dispatch`, `_parse_callback_data`, `_dispatch_key`, `_dispatch_text`, `_builtin_*` functions (`_builtin_screenshot`, `_builtin_ctrlc`, `_builtin_live`, `_builtin_send`, `_builtin_dismiss`), `_BUILTIN_DISPATCH` map. No rendering, no scraping.
- **`toolbar_config.py` (unchanged)** — TOML loader + `ToolbarConfig` dataclass. Already a clean boundary.

**Mode scraping moves to the provider layer.** The current `_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`, and the hardcoded Claude sentinel strings (`auto-accept edits`, `Plan mode`, `Full tool access`) are removed from `toolbar_callbacks.py` and reimplemented as `AgentProvider.scrape_current_mode(window_id: str) -> str | None`. See `provider-layer/design.md`.

## Encapsulated Knowledge

- **Toolbar layout resolution.** Only this module knows how to map `provider_name → ToolbarLayout → buttons grid → action names → rendered keyboard`. The resolution algorithm (including the fallback to `claude` layout for unknown providers) lives here and nowhere else.
- **Per-window label overrides.** Only `toolbar_keyboard.py` holds `_window_action_labels`. Every toggle-read path that updates a label goes through `_set_action_label(window_id, action_name, label)`. No other handler reads this dict.
- **Callback data format.** Only `toolbar_callbacks.py` knows the `tb:{window_id}:{action_name}` wire format, the ≤64-byte budget for Telegram callback data, and the parsing/validation in `_parse_callback_data`.
- **Built-in action semantics.** Only `toolbar_callbacks.py` knows what "screenshot" and "live" and "send" mean in terms of other handler entry points. Each built-in is a ~20-line thin wrapper over a public API of another module.

## Subdomain Classification

**Core.** The toolbar is a UX differentiator — users reach for it often, and new buttons are added as agent CLIs expose new affordances. High internal volatility: every new toggle, built-in, or layout change touches this module.

## Integration Contracts

### Inbound

| From                                                                                                                                           | Kind     | Contract                                |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------- |
| `bot.toolbar_command` → `toolbar_keyboard.seed_button_states(window_id)` → `toolbar_keyboard.build_toolbar_keyboard(window_id, provider_name)` | Contract | Returns `InlineKeyboardMarkup`          |
| PTB callback query dispatcher → `toolbar_callbacks._dispatch(update, context)`                                                                 | Contract | Standard PTB callback handler signature |

### Outbound

| To                                                                                   | Kind                                          | Contract                                                                              |
| ------------------------------------------------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------------- |
| `toolbar_config.load_toolbar_config()`                                               | Contract                                      | Returns `ToolbarConfig` (frozen dataclass)                                            |
| `AgentProvider.scrape_current_mode(window_id)` (NEW)                                 | Contract                                      | Returns `str \| None` — short label or None if provider doesn't support reading state |
| `tmux_manager.send_keys(window_id, seq, raw=?, literal=?)`                           | Contract                                      | Standard tmux operation                                                               |
| `session_manager.view_window(window_id) → WindowView`                                | Contract                                      | Read-only projection for provider_name and cwd                                        |
| `send_command.open_file_browser(bot, chat_id, thread_id, user_data, window_id, cwd)` | Contract                                      | Public API — already in place                                                         |
| `live_view.start_live_view(...)`                                                     | Contract                                      | Public API                                                                            |
| `screenshot_callbacks.screenshot_command(...)`                                       | Contract (indirect via `_builtin_screenshot`) | Public API                                                                            |

### Provider capability addition

```python
# providers/base.py — AgentProvider protocol
async def scrape_current_mode(self, window_id: str) -> str | None:
    """Return a short label describing the agent's current mode, or None.

    Called by toolbar_callbacks when a toggle button is pressed and the
    button's action is marked `read_state: true`. Implementations may
    capture the pane and parse provider-specific mode indicators.
    """
    return None  # Default: no readable mode
```

Claude's implementation moves the existing regexes + sentinel strings out of `toolbar_callbacks`.

## Change Vectors

- **New button** — edit `toolbar.toml`, nothing else.
- **New built-in action** — add to `_BUILTIN_DISPATCH` in `toolbar_callbacks.py`.
- **New toggle with readable state** — add to TOML; add a branch to the provider's `scrape_current_mode`. No change to toolbar_keyboard or toolbar_callbacks.
- **Claude mode-line format changes** — touch `providers/claude.py::scrape_current_mode` only. Toolbar code is unaffected.
- **New layout for a new provider** — edit `toolbar.toml` (provider section with a `buttons` grid). Fallback to Claude layout remains automatic.

## Refactor Plan

1. Create `handlers/toolbar_keyboard.py`. Move: `build_toolbar_keyboard`, `_make_button`, `_window_action_labels`, `_set_action_label`, `_get_action_label`, `_clear_window_labels`, `_clear_toolbar_labels` (cleanup decorator), `_get_toolbar_config`, `reload_toolbar_config`, `seed_button_states`. Public API: `build_toolbar_keyboard`, `seed_button_states`, `reload_toolbar_config`, `_set_action_label` (used by `_refresh_button_label` in callbacks).
2. Add `AgentProvider.scrape_current_mode` to `providers/base.py` (default returns `None`).
3. Move `_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`, `_READ_STATE_DELAY_S` from `toolbar_callbacks.py` to `providers/claude.py::scrape_current_mode`.
4. `toolbar_callbacks._refresh_button_label` becomes: `provider = get_provider_for_window(window_id); label = await provider.scrape_current_mode(window_id) or action.default_label; toolbar_keyboard._set_action_label(window_id, action.name, label); rebuild keyboard`.
5. Slim `handlers/toolbar_callbacks.py` — keep only dispatch + built-in handlers + callback parsing. Expected: ~300 lines.

## Testability Goals

- **Unit-test `build_toolbar_keyboard`** with a synthetic `ToolbarConfig` and a window_id — no bot, no session.
- **Unit-test callback parsing** — `_parse_callback_data("tb:@5:mode")` returns `("@5", "mode")`; malformed input returns `None`.
- **Mock-test `_refresh_button_label`** with a fake provider (returns "Plan") and verify the label dict is updated and the keyboard is rebuilt.
- **Unit-test `ClaudeProvider.scrape_current_mode`** with a saved pane text fixture — no tmux, no bot. The parser is a pure function of string → string.
- **Integration-test the `_builtin_send` path** with a fake `WindowView` and a mock `send_command.open_file_browser` — verify correct window_id and cwd are forwarded.
