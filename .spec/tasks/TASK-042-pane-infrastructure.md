---
id: TASK-042
title: Pane infrastructure in tmux_manager
status: done
priority: high
req: REQ-021
epic: EPIC-009
---

# TASK-042: Pane infrastructure in tmux_manager

Add pane-level operations to `tmux_manager.py`: list all panes in a window, capture a specific pane by ID, and send keys to a specific pane. All methods follow existing patterns (libtmux + `asyncio.to_thread`).

## Implementation Steps

1. Add `PaneInfo` dataclass after the existing `TmuxWindow` dataclass:

   ```python
   @dataclass
   class PaneInfo:
       pane_id: str      # "%3" — stable global ID
       index: int        # 0-based position in window
       active: bool
       command: str      # "claude", "bash", etc.
       path: str         # working directory
       width: int
       height: int
   ```

2. Add `list_panes(window_id) -> list[PaneInfo]` method to `TmuxManager`:
   - Use `self.get_session()` → `session.windows.get(window_id=window_id)`
   - Iterate `window.panes`, map to `PaneInfo`
   - libtmux returns string values — cast `pane_active == "1"`, `int(pane_width)`, etc.
   - Wrap in `asyncio.to_thread`
   - Return empty list on error (log warning)

3. Add `capture_pane_by_id(pane_id, with_ansi=False) -> str | None` method:
   - For ANSI: `tmux capture-pane -e -p -t <pane_id>` via subprocess (same pattern as `_capture_pane_ansi` but targeting pane_id directly)
   - For plain: resolve pane via libtmux server, call `pane.capture_pane()`
   - Wrap in `asyncio.to_thread`
   - Return None on error

4. Add `send_keys_to_pane(pane_id, text, enter=True, literal=True) -> bool` method:
   - Resolve pane via libtmux: iterate `server.panes` or use session to find by `pane_id`
   - Call `pane.send_keys(text, enter=enter, literal=literal)`
   - Follow same literal-then-enter pattern as `_send_literal_then_enter` if needed
   - Wrap in `asyncio.to_thread`
   - Return False on error

5. Add internal helper `_find_pane(pane_id) -> libtmux.Pane | None`:
   - Get session via `self.get_session()`
   - Iterate all windows and their panes to find matching `pane_id`
   - Cache is not needed (pane lookup is fast)

6. Add tests in `tests/ccbot/test_tmux_manager.py`:
   - Test `list_panes` returns correct `PaneInfo` objects
   - Test `capture_pane_by_id` with valid/invalid pane_id
   - Test `send_keys_to_pane` delegates to correct pane
   - Mock libtmux session/window/pane objects

## Acceptance Criteria

- [ ] `PaneInfo` dataclass exists with all fields
- [ ] `list_panes` returns all panes for a window, empty list for missing window
- [ ] `capture_pane_by_id` captures specific pane content (plain and ANSI)
- [ ] `send_keys_to_pane` sends to the correct pane, not the active one
- [ ] All methods handle errors gracefully (return None/empty/False, log warning)
- [ ] All methods are async (wrapped in `asyncio.to_thread`)
- [ ] Tests pass: `make test`
- [ ] Lint passes: `make lint`
