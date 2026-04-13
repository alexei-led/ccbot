# Screenshot and Live View

## Functional Responsibilities

Three related features that deliver visual representations of the tmux pane state to Telegram:

1. **Screenshot** — on-demand PNG render of a pane via the `/screenshot` command or inline keyboard button. Uses Pillow to draw ANSI-coloured terminal text.
2. **Live View** — auto-refreshing screenshot via `editMessageMedia` at a configurable interval (default 5s), with content-hash gating (skip edit if unchanged) and auto-stop after a timeout. One active view per topic.
3. **Pane screenshots** — multi-pane windows (agent teams) get per-pane screenshot buttons via `/panes`.

Files after refactor:

- **`handlers/screenshot_callbacks.py`** (SLIMMED to ~350 lines) — screenshot capture and refresh only. `screenshot_command`, `panes_command`, `_handle_refresh`, `_handle_pane_screenshot`, `_handle_status_screenshot`, `build_screenshot_keyboard`, `_parse_target`, `_pending_key_refreshes` (cleanup).
- **`handlers/live_view.py`** (unchanged, ~200 lines) — auto-refresh state, `_active_views`, `LiveViewState`, start/stop, tick loop integration with `periodic_tasks`.
- **`handlers/status_bar_actions.py`** (NEW, ~200 lines) — extracted from screenshot_callbacks. Status-bubble button callbacks: `_handle_notify_toggle`, `_handle_status_recall`, `_handle_remote_control`, `_handle_status_esc`, `_handle_keys`, `_schedule_key_refresh`. These handle the buttons that appear on the pinned status message but are not screenshot operations.
- **`screenshot.py`** (core module, unchanged) — `text_to_image(text, ...)` pure rendering.

## Encapsulated Knowledge

- **Screenshot rendering** — `screenshot.py` owns font fallback, ANSI colour mapping, line wrapping. No other module touches Pillow directly.
- **Live view lifecycle** — `live_view.py` owns the one-active-view-per-topic invariant, the content-hash comparison, and the auto-stop timer. Other handlers (`toolbar_callbacks._builtin_live`, `screenshot_callbacks._handle_live_start`) call `start_live_view()` but do not see the internal state.
- **Keyboard layout for screenshots** — `screenshot_callbacks.build_screenshot_keyboard` owns the control-key grid attached to every screenshot. No other module duplicates this layout.
- **Status bar actions** — `status_bar_actions.py` owns the set of buttons that appear on the pinned status message (notify toggle, recall history, RC activate, esc, keys). Adding a new status-bar button touches only this file.
- **Pending key refreshes** — after a quick-key press from a screenshot keyboard, the screenshot refreshes after a short delay to reflect the result. `_pending_key_refreshes` state lives in `screenshot_callbacks.py`.

## Subdomain Classification

**Core** for screenshot and live view (active features, UX-visible). **Core** for status bar actions (where every new status-bubble capability lives).

## Integration Contracts

### Inbound

| From                                                                  | Kind     | Contract                      |
| --------------------------------------------------------------------- | -------- | ----------------------------- |
| `/screenshot` command handler → `screenshot_command(update, context)` | Contract | PTB command handler           |
| `/panes` command handler → `panes_command(update, context)`           | Contract | PTB command handler           |
| Callback query dispatcher → `screenshot_callbacks._dispatch`          | Contract | Screenshot-prefixed callbacks |
| Callback query dispatcher → `status_bar_actions._dispatch`            | Contract | Status-bar-prefixed callbacks |
| `toolbar_callbacks._builtin_screenshot` → `screenshot_command(...)`   | Contract | Public API                    |
| `toolbar_callbacks._builtin_live` → `live_view.start_live_view(...)`  | Contract | Public API                    |
| `periodic_tasks.run_periodic_tasks` → `live_view.tick_all_views(bot)` | Contract | Per-tick driver               |

### Outbound

| To                                                    | Kind     | Contract                                                |
| ----------------------------------------------------- | -------- | ------------------------------------------------------- |
| `tmux_manager.capture_pane(window_id)`                | Contract | Pane text                                               |
| `screenshot.text_to_image(text, ...)`                 | Contract | PNG bytes                                               |
| `message_sender.safe_send_photo(...)`                 | Contract | Telegram API                                            |
| `message_sender.edit_message_media(...)`              | Contract | Live-view edits                                         |
| `session_manager.view_window(window_id) → WindowView` | Contract | Notification mode, cwd                                  |
| `message_queue.enqueue_status_update(...)`            | Contract | Status bubble updates from `_handle_notify_toggle` etc. |
| `command_history.recent(user_id, thread_id)`          | Contract | Recall menu in `_handle_status_recall`                  |

## Change Vectors

- **New rendering feature (e.g., highlight last N lines)** — touches `screenshot.py` only.
- **Change live-view interval default** — touches config, not this module.
- **New status-bar button (e.g., "pause notifications for 10min")** — add to `status_bar_actions.py`, register in callback_data.
- **New screenshot keyboard layout** — touches `screenshot_callbacks.build_screenshot_keyboard` only.
- **Multi-pane window handling change** — touches `panes_command` and `_handle_pane_screenshot` in `screenshot_callbacks.py`.

## Refactor Plan

1. Create `handlers/status_bar_actions.py`. Move from `screenshot_callbacks.py`:
   - Functions: `_handle_notify_toggle`, `_handle_status_recall`, `_handle_remote_control`, `_handle_status_esc`, `_handle_keys`, `_schedule_key_refresh` (and its inner `_do_refresh`).
   - State: `_pending_key_refreshes` (moves with `_handle_keys` since it is the only reader/writer).
   - Callback registrations: add `@register(CB_STATUS_NOTIFY, CB_STATUS_RECALL, CB_STATUS_REMOTE, CB_STATUS_ESC, CB_STATUS_KEY)` on a new `_dispatch` function.
2. Slim `handlers/screenshot_callbacks.py`. Keep: `screenshot_command`, `panes_command`, `_handle_refresh`, `_handle_pane_screenshot`, `_handle_status_screenshot` (the "take a fresh screenshot of the current pane" status-bar action — this is the only status-bar action that legitimately belongs in screenshot_callbacks), `_handle_live_start`, `_handle_live_stop`, `build_screenshot_keyboard`, `_parse_target`, `_clear_key_refreshes`.
3. Update imports in:
   - `callback_registry.load_handlers` to import `status_bar_actions`.
   - `bot.py` (none directly — screenshot/panes commands stay registered from `screenshot_callbacks`).
4. Update CLAUDE.md handler inventory with the new `status_bar_actions` module.

## Testability Goals

- **Unit-test `screenshot.text_to_image`** with a fixture string — output PNG is deterministic enough for byte-hash comparison.
- **Unit-test `build_screenshot_keyboard`** — pure function.
- **Integration-test `screenshot_command`** with a mocked `tmux_manager.capture_pane` and a mocked `bot.send_photo` — verify the screenshot round-trip.
- **Unit-test `_handle_notify_toggle`** with a fake `WindowView` and a mocked `session_manager.cycle_notification_mode` — verify the correct mode transition.
- **Unit-test `live_view.tick_single_view`** with a fake clock and a fake pane capture — verify content-hash skipping works.
