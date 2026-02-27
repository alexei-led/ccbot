---
id: TASK-044
title: Pane-aware interactive UI and callbacks
status: done
priority: high
req: REQ-021
epic: EPIC-009
depends: [TASK-042, TASK-043]
---

# TASK-044: Pane-aware interactive UI and callbacks

Extend interactive UI rendering and callback handling to support pane-specific prompts. When a non-active pane has an interactive prompt, render it with pane context and route button responses to the correct pane.

## Implementation Steps

1. Extend callback data constants in `callback_data.py`:
   - Current format: `"aq:enter:@12"` (action:window_id)
   - New format for pane-specific: `"aq:enter:@12:%5"` (action:window_id:pane_id)
   - Pane_id is optional — absent means active pane (backward compatible)
   - Verify total length stays under 64 bytes: `"aq:enter:@12:%99"` = 17 bytes — safe

2. Extend `handle_interactive_ui` in `interactive_ui.py`:
   - Add optional `pane_id: str | None = None` parameter
   - When `pane_id` is provided:
     a. Use `tmux_manager.capture_pane_by_id(pane_id)` instead of `capture_pane(window_id)`
     b. Prepend pane context to the rendered message: `"🔀 Pane {index} ({command}):"`
     c. Include pane_id in all callback data for the inline keyboard
   - When `pane_id` is None: current behavior unchanged

3. Extend interactive state tracking:
   - Current key: `(user_id, thread_id)` → `window_id`
   - Add parallel tracking for pane alerts: `_pane_interactive: dict[tuple[int, int, str], str]`
     - Key: `(user_id, thread_id, pane_id)` → `window_id`
   - Functions: `get_interactive_pane(user_id, thread_id, pane_id)`, `set_interactive_pane(...)`, `clear_interactive_pane(...)`
   - The main `get_interactive_window` / `set_interactive_mode` remain unchanged for active-pane prompts

4. Update keyboard builder to include pane_id:
   - When building inline keyboard buttons, append `:pane_id` to callback data if pane_id is set
   - Example: `CB_ASK_ENTER + window_id + ":" + pane_id` → `"aq:enter:@12:%5"`

5. Extend `handle_interactive_callback` in `interactive_callbacks.py`:
   - Parse callback data: split on ":" — if 4 parts, extract pane_id; if 3 parts, no pane_id
   - When pane_id is present:
     a. Use `tmux_manager.send_keys_to_pane(pane_id, key)` instead of `tmux_manager.send_keys(window_id, key)`
     b. After sending, re-capture that specific pane to check if prompt resolved
   - When pane_id is absent: current behavior unchanged
   - Handle stale pane: if `send_keys_to_pane` returns False, edit message to "Pane closed"

6. Add the "Refresh" button behavior for pane alerts:
   - On refresh, re-capture the specific pane and re-render
   - If prompt no longer present, edit to "✓ Resolved"

## Acceptance Criteria

- [ ] Pane-specific prompts render with pane context prefix
- [ ] Button presses route to the correct pane via pane_id in callback data
- [ ] Active-pane prompts work exactly as before (no regression)
- [ ] Multiple simultaneous pane alerts are supported (different panes, same topic)
- [ ] Stale pane (closed) handled gracefully — message edited, no error
- [ ] Callback data stays under 64 bytes
- [ ] Tests cover: pane callback parsing, pane-targeted send, refresh, stale pane
- [ ] `make check` passes
