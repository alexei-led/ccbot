# Modularity Review — Post Architecture Round 2

**Scope**: Entire `src/ccgram/` after `refactor/architecture-round-2`
**Date**: 2026-04-14
**Model**: [Balanced Coupling](https://coupling.dev/posts/core-concepts/balance/)
**Previous review**: [`2026-04-13/modularity-review.md`](../2026-04-13/modularity-review.md)

## Executive Summary

The refactor delivers on most of the prior review. Six of nine flagged issues
are resolved or materially improved; three structural problems persist — and
they are all manifestations of the same underlying mistake: extractions were
done along line‑of‑sight boundaries without fixing the **shared type** that
glues the modules together.

Total refactor footprint: **106 files, +8225/−2333**, 28 commits on
`refactor/architecture-round-2`, five rounds of code‑review fixes afterward.
Code quality is tangibly better: `message_queue.py` went 1132→479, `toolbar_callbacks.py` 557→264, `screenshot_callbacks.py` 764→513,
and `topic_state_registry.register_bound()` now gives 15+ handlers a clean way
to auto‑clean per‑topic state.

**Overall posture**: healthy, with three concentrated structural problems
around a shared union dataclass, a still‑god polling loop, and a session
facade whose migration only produced a beachhead.

### What got fixed (6 of 9)

| Prior issue                                                | Resolution                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#2 `toolbar_callbacks` 3‑concerns + Claude pane scrape** | Split into `toolbar_callbacks.py` (264 lines, dispatch only) + `toolbar_keyboard.py` (155 lines, builder). Mode‑line scrape pushed behind `provider.scrape_current_mode()` capability. Clean.                                                                                                                           |
| **#3 Shell prompt‑marker distributed setup**               | Five callers (`directory_callbacks`, `shell_commands`, `transcript_discovery` ×2, `window_callbacks`) now go through `shell_prompt_orchestrator.ensure_setup(window_id, trigger)` (178 lines). Implicit ordering replaced by explicit trigger enum and per‑window `_OrchestratorState` with skip/offer/accepted states. |
| **#8 Residual Claude string checks**                       | `provider.capabilities.has_yolo_confirmation` flag replaces hardcoded `provider_name == "claude"`. `provider.scrape_current_mode()` moved to protocol.                                                                                                                                                                  |
| **#9 `summarizer.py` Claude‑hardcoded**                    | Acknowledged as low‑volatility in prior review; unchanged, correctly.                                                                                                                                                                                                                                                   |
| **#6 `screenshot_callbacks` 4 concerns**                   | `status_bar_actions.py` (307 lines) extracted cleanly. Screenshot module down to 513 lines. Still holds screenshot + live view start/stop + pane screenshot + `/panes` command — see **residual note #1** below.                                                                                                        |
| **Polling strategy classes** (part of #4)                  | `TerminalScreenBuffer`, `TerminalPollState`, `InteractiveUIStrategy`, `TopicLifecycleStrategy` are now proper classes with encapsulated state. `register_bound()` wires them into topic cleanup. This is the cleanest piece of the refactor.                                                                            |

### What remains (3 structural issues + residuals)

## Issue A — `MessageTask` Is the Wrong Shape, and It Now Causes Two Import Cycles

**Integration**: `message_queue.py` ↔ `tool_batch.py` ↔ `status_bubble.py`
**Strength**: common coupling (union dataclass) + implicit structural cycle
**Distance**: same package, same process
**Volatility**: core subdomain (message routing is heavily modified every feature)
**Severity**: **Significant** — root cause of the biggest remaining pain point

### What's shared

`MessageTask` (message_queue.py:42) is still a union‑shaped dataclass:

```python
@dataclass
class MessageTask:
    task_type: Literal["content", "status_update", "status_clear"]
    text: str | None = None
    window_id: str | None = None
    parts: list[str] = field(default_factory=list)
    tool_use_id: str | None = None
    tool_name: str | None = None
    content_type: str = "text"
    thread_id: int | None = None
```

Half of the fields are only legal for `content` tasks (`parts`, `tool_use_id`,
`tool_name`, `content_type`); readers of every site must maintain the
"which fields are valid in which states" contract in their heads — classic
[common coupling](https://coupling.dev/posts/related-topics/module-coupling/).

### The cycle this produces

Because `MessageTask` stayed in `message_queue.py` while the functions that
operate on it moved out, the extracted modules must import back:

```
message_queue.py  ──imports──▶  tool_batch.py
                                (is_batch_eligible, process_tool_event,
                                 flush_batch, has_active_batch, clear_all_batches)
tool_batch.py     ──imports──▶  message_queue.py
                                ├─ TYPE_CHECKING: MessageTask
                                └─ 3× runtime local `from .message_queue
                                   import process_content_task`

message_queue.py  ──imports──▶  status_bubble.py
                                (process_status_update_task,
                                 process_status_clear_task,
                                 clear_status_message, convert_status_to_content)
status_bubble.py  ──imports──▶  message_queue.py
                                └─ TYPE_CHECKING: MessageTask
```

Both extracted modules depend on their parent through local/deferred imports.
This is **structural circular coupling** — the refactor removed the line‑level
code from `message_queue.py` but the type contract is still woven through it,
so future changes to `MessageTask` still cascade into both children, and the
children cannot be tested or imported in isolation.

### Why it matters

Messaging is the most volatile area in the codebase. Every feature that
touches Telegram output (status bubble conversion, tool batching, Claude task
lists, subagent labels) reopens two of the three modules. The per‑round
`"fix: address code review findings"` commits — **six rounds** — are a
direct symptom: one change ripples through whichever module happened to be
the one chosen for an imported helper.

### Fix

Replace `MessageTask` with a proper sum type in a neutral `message_task.py`:

```python
@dataclass(frozen=True)
class ContentTask:
    window_id: str
    parts: list[str]
    content_type: Literal["text", "tool_use", "tool_result"]
    tool_use_id: str | None = None
    tool_name: str | None = None
    thread_id: int | None = None

@dataclass(frozen=True)
class StatusUpdateTask:
    window_id: str
    text: str | None
    thread_id: int | None

@dataclass(frozen=True)
class StatusClearTask:
    window_id: str | None
    thread_id: int | None

MessageTask = ContentTask | StatusUpdateTask | StatusClearTask
```

Move it to a neutral module that depends on nothing else in `handlers/`.
`message_queue.py`, `status_bubble.py`, and `tool_batch.py` all import _from_
it; none of them import _each other_ for types. The functional cycle
(`tool_batch` needing `process_content_task` to flush) can be resolved by
injecting the callback at registration time, or — simpler — by having
`message_queue.py` own the single "fallback to content" path and have
`tool_batch.py` return an `Optional[ContentTask]` that the queue processes.

This is the single most valuable change left in the codebase.

## Issue B — `polling_coordinator.py` Is Still a 598‑Line God Loop

**Integration**: `polling_coordinator.py` orchestrates 15+ modules per cycle
**Strength**: functional coupling (direct calls) + temporal coupling (ordering)
**Distance**: same package, same async loop
**Volatility**: high (polling behaviour touched every time a new status source is added)
**Severity**: **Significant** — but less acute than Issue A

### What's happening

The refactor was supposed to slim this module down by promoting strategies
into classes. The strategies _are_ promoted (`TerminalScreenBuffer`,
`TerminalPollState`, `InteractiveUIStrategy`, `TopicLifecycleStrategy`), and
that is a real win. But `status_poll_loop` and `update_status_message` still
directly orchestrate the work:

```python
# status_poll_loop body (polling_coordinator.py:513)
#   1. list_windows + discover_external_sessions
#   2. run_periodic_tasks (broker / sweep / spawn / live view)
#   3. for each thread binding:
#      - is_dead_notified check
#      - dead window notification branch
#      - discover_and_register_transcript
#      - if queue not empty: _check_interactive_only + _scan_window_panes + _maybe_check_passive_shell
#      - else: update_status_message + _scan_window_panes + _maybe_check_passive_shell
#   4. run_lifecycle_tasks

# update_status_message body (polling_coordinator.py:415)
#   - capture_pane + pyte parse
#   - vim INSERT indicator tracking
#   - interactive UI detection + dispatch
#   - status line formatting + emoji prefix
#   - claude_task_state wait header + last status
#   - subagent label building
#   - typing indicator throttling
#   - topic emoji updates
#   - autoclose timer coordination
#   - enqueue status update
```

15 imports at the top, 11 in function bodies. The strategies now hold state
but the **decisions** about what to do next are still in the coordinator.
Any new concern (e.g. a new notification mode, a new vim‑style passive
observer) adds another branch to `update_status_message` or another call site
in the loop.

### Why prior review called this "god loop" and still does

The difference between "coordinates strategies" and "is a god loop" is
whether the loop contains **decision logic** or just dispatches on state the
strategies own. Right now it contains decisions: `if queue and not
queue.empty()` chooses interactive vs status, `is_shell_prompt` chooses
shell vs non‑shell idle transition, `is_active` chooses typing vs idle, etc.

### Fix (incremental)

Don't try to dissolve the loop in one go. Instead:

1. Promote the `per_window_tick(user_id, thread_id, window_id, bot)` step to
   its own module `handlers/window_tick.py`. The loop becomes ~50 lines:
   list windows → periodic tasks → for binding: `await window_tick(...)` →
   lifecycle tasks.
2. Inside `window_tick`, the remaining decisions can be lifted into a small
   state machine keyed by `(has_pending_queue, has_terminal_status,
is_interactive, is_shell_idle)`.
3. Don't split `update_status_message` further until step 1 is done — the
   extraction order matters and premature splitting creates more import
   lines, not fewer.

This is the kind of change that _must_ land on a dedicated branch because
the observable behaviour is subtle and the test coverage in
`test_status_polling.py` and `test_polling_strategies.py` is the only safety
net.

## Issue C — `WindowView` Is a Beachhead, Not a Migration

**Integration**: handlers → `session_manager` (77 direct calls) + `view_window` (6 handlers)
**Strength**: model/contract coupling (reach into SessionManager for single scalars)
**Distance**: same package, same process
**Volatility**: moderate (session.py is touched less often than polling/messaging, but still quarterly)
**Severity**: **Minor** (but worth flagging so the migration actually happens)

### Numbers

- `session_manager.` direct call sites in `handlers/`: **77** (unchanged from prior review's 77)
- `SessionManager` methods: **46**
- `session.py`: **803 lines** (unchanged)
- `view_window()` adopters: **6** handlers (`send_command`, `file_handler`,
  `shell_context`, `text_handler`, `toolbar_keyboard`, `toolbar_callbacks`) —
  up from **0** in prior review

The `WindowView` dataclass is exactly right — frozen, read‑only,
window_id/cwd/provider_name/approval_mode/notification_mode/transcript_path.
Six handlers adopted it. **But adoption stopped there**, and the facade
didn't shrink by a single method. The refactor landed the foundation and
then moved on.

### Why it matters

Every `session_manager.get_notification_mode(window_id)`,
`session_manager.get_approval_mode(window_id)`, `session_manager.
get_window_state(window_id).cwd` in the 71 non‑adopted sites couples the
caller to the full `SessionManager` shape — rename a WindowState field and
every read cascades.

### Fix (cheap, incremental)

Grep for `session_manager\.(get_notification_mode|get_approval_mode|
get_window_state|get_display_name)` — these are the four methods that
account for most of the 77 calls. Replace each with
`session_manager.view_window(window_id).notification_mode` (etc.). Done per
handler; each edit is 2–5 lines and entirely mechanical. The mutation paths
(`set_notification_mode`, `set_approval_mode`) stay as direct method calls
because `WindowView` is read‑only by design.

## Residual notes (not tracked as full issues)

1. **`screenshot_callbacks.py` (513 lines, 4 concerns remaining)**. After
   pulling `status_bar_actions` out, the screenshot module now owns:
   keyboard building, live‑view start/stop, pane screenshot handler,
   status refresh, `/screenshot` and `/panes` commands. Less severe than
   before. Don't split further unless the file actively causes friction.

2. **Module‑level `_prefixed` dicts pattern — 35+ instances, pattern
   unchanged**. The refactor _did not_ dissolve the pattern but it did fix
   the real problem: `topic_state_registry.register_bound()` is now adopted
   by 15 modules and wires per‑window dicts into topic‑close cleanup. New
   dicts added by the refactor (`tool_batch._active_batches`,
   `status_bar_actions._pending_key_refreshes`,
   `shell_prompt_orchestrator._state`, `toolbar_keyboard._window_action_labels`)
   all use the registry. This is now a cognitive/style issue — not a
   correctness/leak risk — and can be left alone.

3. **`session.py` at 803 lines with 46 public methods**. Ties to Issue C.
   Unchanged. Not worth splitting before WindowView migration is done —
   splitting first would just create a second facade.

4. **`MessageTask.content_type` as a `str` field** (message_queue.py:52).
   Should be `Literal["text", "tool_use", "tool_result"]` for the same
   reason `task_type` is a Literal. Minor; fix alongside Issue A.

5. **Six rounds of `"fix: address code review findings"` commits** in a
   single branch is a signal worth noting. Most of the findings came from
   the same few files repeatedly (`message_queue`, `polling_coordinator`,
   `status_bubble`, `tool_batch`) — the same cluster that still has the
   unresolved structural cycle. This is corroboration, not coincidence.

## Priority Ranking

| #   | Issue                                            | Severity         | Effort               | Order                                              |
| --- | ------------------------------------------------ | ---------------- | -------------------- | -------------------------------------------------- |
| A   | `MessageTask` shape + bidirectional import cycle | Significant      | 1–2 days             | **Do first** — unblocks the cluster                |
| B   | `polling_coordinator` god loop                   | Significant      | 2–3 days             | Do second, on its own branch                       |
| C   | `WindowView` migration (71 more sites)           | Minor            | 4–6 hours mechanical | Do anytime; good first contribution for a subagent |
| —   | Residual notes 1–5                               | Minor / cosmetic | —                    | Leave unless they actively cause friction          |

## Summary

Round 2 of the architecture refactor was a substantial quality win: six of
nine flagged issues are closed, `topic_state_registry` is a genuine cohesion
improvement, and the shell‑prompt orchestrator/toolbar split/status‑bar
extraction are all clean. Module sizes are down across the board.

The three remaining issues are not new regressions — they are **pre‑existing
structural problems that the refactor approached but did not finish**:

- The messaging cluster was split into three modules while keeping the
  shared `MessageTask` union, which produced two bidirectional import cycles
  and six rounds of drift.
- The polling loop got proper strategy classes but kept all the decision
  logic in the coordinator.
- `WindowView` was introduced and then adopted only six times out of seventy‑seven.

All three have low‑risk, incremental fixes. Issue A is the one worth
prioritising: it is both the root cause of the cluster's instability _and_
the smallest fix by actual code volume.

**Overall posture**: the codebase is in its best shape in this review
series. No new structural problems were introduced by the refactor — the
ones remaining are ones that the refactor explicitly chose to defer.

## Resolution

Issues A and B from this review were addressed in the [Messaging Cluster + Polling Loop Refactor](../../plans/completed/20260414-messaging-and-polling-refactor.md) plan, executed on 2026-04-14:

- **Issue A (Messaging cluster circular imports)**: Resolved by extracting `MessageTask` into `message_task.py` as a dependency-free sum type (three frozen dataclasses: `ContentTask`, `StatusTask`, `ToolResultTask`). All bidirectional imports between `message_queue`, `tool_batch`, and `status_bubble` were eliminated.
- **Issue B (Polling coordinator size)**: Resolved by extracting per-window poll logic into `window_tick.py` (entry point: `tick_window`), reducing `polling_coordinator.py` from ~600 lines to ~92 lines. The coordinator is now a thin orchestrator that iterates thread bindings and delegates.
- **Issue C (WindowView adoption)**: Deferred — low priority, no structural risk.

All acceptance criteria verified: zero circular imports, full test suite passing, polling coordinator under 120 lines.
