# `handlers/window_tick` — Per-Window Poll Cycle

## Functional Responsibilities

Runs one poll cycle for one thread-bound tmux window. Owns all the
per-window decisions that used to live inline in
`polling_coordinator.status_poll_loop` / `update_status_message`:

- Dead-window detection and notification.
- Transcript discovery and registration (delegates to
  `transcript_discovery`).
- Pane capture and `pyte` parse.
- Vim INSERT-mode passive indicator tracking.
- Interactive UI detection and dispatch (delegates to `interactive_ui`).
- Multi-pane scanning for interactive prompts in non-active panes.
- Passive shell output relay (delegates to `shell_capture`).
- Terminal status line extraction and formatting (emoji prefix,
  subagent label).
- Idle / active / startup / done state transitions.
- Topic emoji updates.
- Autoclose timer coordination.
- Typing indicator throttling.
- Enqueueing status updates into the message queue.

## Encapsulated Knowledge

- **The per-window state machine**: which transition fires given
  `(queue_non_empty, has_provider_status, is_interactive,
is_shell_prompt, provider_capabilities, startup_timer_state,
transcript_activity)`.
- **The side-effect ordering**: typing → emoji → autoclose → enqueue is
  not arbitrary. Changing the order causes visible glitches in the
  Telegram UI (typing flickers, emoji/text mismatch).
- **The interactive-vs-status precedence rule**: interactive UI wins over
  status line; status line wins over idle transition.
- **Multi-pane scan gating**: `is_single_pane_cached` fast-path to avoid
  enumerating panes for single-pane windows.

## Subdomain Classification

**Core** — polling behaviour is high-volatility. Every new provider
capability, every new notification mode, every new status source gets
wired in here.

## Integration Contracts

`window_tick` is the **only** module that understands how per-window
state translates into effects. It fans out to ~12 cooperating modules;
that fan-out is inherited from the current coordinator and is expected.
The point is that the decision logic is now concentrated in a single
cohesive module rather than scattered across a loop + helpers.

| Integration            | Direction             | Strength   | What is shared                                                                                                               |
| ---------------------- | --------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `tmux_manager`         | `window_tick` → calls | Functional | `find_window_by_id`, `capture_pane`, `list_panes`, `get_pane_title`, `notify_vim_insert_seen`                                |
| `providers`            | `window_tick` → calls | Functional | `get_provider_for_window(wid)`, `provider.parse_terminal_status`, `provider.capabilities`                                    |
| `polling_strategies`   | `window_tick` → calls | Functional | `terminal_screen_buffer`, `terminal_poll_state`, `interactive_strategy`, `lifecycle_strategy`, `is_shell_prompt`             |
| `interactive_ui`       | `window_tick` → calls | Functional | `handle_interactive_ui`, `clear_interactive_msg`, `get_interactive_window`, `set_interactive_mode`, `clear_interactive_mode` |
| `topic_emoji`          | `window_tick` → calls | Functional | `update_topic_emoji`                                                                                                         |
| `transcript_discovery` | `window_tick` → calls | Functional | `discover_and_register_transcript`                                                                                           |
| `shell_capture`        | `window_tick` → calls | Functional | `check_passive_shell_output`                                                                                                 |
| `message_queue`        | `window_tick` → calls | Functional | `enqueue_status_update`, `get_message_queue` (read-only check for queue length)                                              |
| `recovery_callbacks`   | `window_tick` → calls | Functional | `build_recovery_keyboard` (used in dead window notification)                                                                 |
| `claude_task_state`    | `window_tick` → reads | Model      | `clear_wait_header`, `set_last_status`, `build_subagent_label`, `get_subagent_names`                                         |
| `thread_router`        | `window_tick` → calls | Functional | `resolve_chat_id`, `get_display_name`                                                                                        |
| `session_manager`      | `window_tick` → reads | Model      | `get_notification_mode`, `get_window_state.provider_name` — candidate for `WindowView` migration (Issue C)                   |

### Public API — one entry point

```python
async def tick_window(
    bot: Bot,
    user_id: int,
    thread_id: int,
    window_id: str,
    window: TmuxWindow | None,
) -> None:
    """Run one poll cycle for one window. Own all per-window side effects.

    Preconditions:
        - thread_id is a real topic (not None for dead detection path)
        - window may be None (dead window case)
    Postconditions:
        - Any status/emoji updates have been enqueued or delivered
        - Interactive UI state has been reconciled
        - Autoclose timers reflect the current state
    """
```

All the `_handle_*`, `_scan_*`, `_check_*`, `_transition_*`, and
`_maybe_*` helpers that currently clutter `polling_coordinator` are
**private to this module**. The outer loop does not know they exist.

### Internal structure (private)

```python
# window_tick.py

async def tick_window(...) -> None:
    if _is_dead(window_id, window):
        await _handle_dead(bot, user_id, thread_id, window_id)
        return

    await discover_and_register_transcript(window_id, ...)

    queue = get_message_queue(user_id)
    if queue and not queue.empty():
        # interactive-only fast path
        await _check_interactive_only(bot, user_id, window_id, thread_id, window)
        await _scan_window_panes(bot, user_id, window_id, thread_id)
        await _maybe_check_passive_shell(bot, user_id, window_id, thread_id)
        return

    await _update_status(bot, user_id, window_id, thread_id, window)
    await _scan_window_panes(bot, user_id, window_id, thread_id)
    await _maybe_check_passive_shell(bot, user_id, window_id, thread_id)
```

`_update_status` absorbs today's `update_status_message`. `_handle_dead`
absorbs `_handle_dead_window_notification`. Everything else is lifted
verbatim.

## Change Vectors

1. **New provider with a new status signal** — extend the provider
   capabilities check in `_update_status`. Isolated.
2. **New notification mode** — one new branch in the enqueue section.
3. **Different autoclose policy** — isolated to the `lifecycle_strategy`
   calls.
4. **New passive observer** (e.g., passive emacs mode tracking alongside
   vim INSERT) — one new hook call in `_update_status`. Isolated.

Changes that still ripple:

- Fundamentally changing _when_ the poll runs (per-binding vs. per-user,
  event-driven vs. polling) — requires reworking the outer loop in
  `polling_coordinator`, not just `window_tick`.
- A second provider capability that fundamentally changes the state
  machine — may require extracting a pure `classify()` function in a
  future round, which is the prior review's recommendation (deferred).
