# Architecture — Messaging Cluster + Polling Loop Redesign

**Date**: 2026-04-14
**Scope**: Issues A and B from [`../../modularity-review/2026-04-14/modularity-review.md`](../../modularity-review/2026-04-14/modularity-review.md)
**Model**: [Balanced Coupling](https://coupling.dev/posts/core-concepts/balance/)

## Functional Requirements Summary

The Apr 14 modularity review flagged three structural issues remaining
after the Round 2 architecture refactor. Two of them — **Issue A**
(messaging cluster has bidirectional import cycles from a union
dataclass) and **Issue B** (`polling_coordinator` is still a 598-line
god loop) — are addressed by this design. Issue C (`WindowView`
migration) is explicitly out of scope and will be handled as a
mechanical follow-up.

**Requirements that shape the design**:

1. The `MessageTask` data shape must become an explicit sum type with
   no optional grab-bag fields.
2. `tool_batch` and `status_bubble` must depend on the message-task
   contract only, not on `message_queue`. Bidirectional coupling must
   be eliminated.
3. `polling_coordinator` must become a loop shell only. Per-window
   decisions must live in a dedicated module.
4. The refactor must be implementable incrementally with preserved
   observable behavior — no single-shot big-bang.
5. The existing test suite (`test_status_polling.py`,
   `test_tool_batching.py`, `test_status_bubble.py`,
   `test_polling_strategies.py`, `test_message_queue.py`) must continue
   to pass, migrating to the new module boundaries.

## Module Map

| Module                            | Role                                                  | Lines (target) | New / Modified                                                    |
| --------------------------------- | ----------------------------------------------------- | -------------- | ----------------------------------------------------------------- |
| `handlers/message_task.py`        | Pure data — sum type for `MessageTask` variants       | ~60            | **New**                                                           |
| `handlers/message_queue.py`       | Queue primitives + dispatcher                         | ~450           | **Modified** — drops status & batch logic, gains match dispatcher |
| `handlers/tool_batch.py`          | Claude tool-use batch state machine                   | ~450           | **Modified** — returns data, no back-edge                         |
| `handlers/status_bubble.py`       | Status message lifecycle                              | ~300           | **Modified** — returns data, no back-edge                         |
| `handlers/window_tick.py`         | Per-window poll cycle (all per-window logic)          | ~450           | **New**                                                           |
| `handlers/polling_coordinator.py` | Outer poll loop, backoff, periodic task orchestration | ~100           | **Modified** — reduced from 598                                   |

**Net change**: +2 new modules, 4 modified. Total lines in the affected
cluster: roughly the same as today — the refactor _moves_ logic, it does
not delete it. The win is in **where** logic lives and **which direction
imports flow**.

## How the Modules Work Together

### Flow 1: Content message delivery (happy path)

```
polling_coordinator.status_poll_loop
    └─ for each binding:
       └─ window_tick.tick_window(...)
          └─ _update_status(...)
             └─ message_queue.enqueue_status_update(...)   [eventually flushes status bubble]

[elsewhere, hook or monitor produces a ContentTask]
    └─ message_queue.enqueue_content_message(...)
       └─ worker dequeue
          └─ match task:
             case ContentTask (batchable):
                └─ tool_batch.process_tool_event(task) → None | ContentTask
                   └─ if followup: message_queue._process_content_task(followup)
             case ContentTask (not batchable):
                └─ tool_batch.flush_if_active(...)
                └─ message_queue._process_content_task(task)
             case StatusUpdateTask:
                └─ status_bubble.process_status_update(task) → None | ContentTask
                   └─ if followup: message_queue._process_content_task(followup)
             case StatusClearTask:
                └─ status_bubble.process_status_clear(task)
```

**Contract**: `tool_batch` and `status_bubble` never call back into
`message_queue`. When they need the content-delivery primitive, they
_return_ a `ContentTask` and the queue worker runs it through
`_process_content_task`.

### Flow 2: Poll cycle

```
polling_coordinator.status_poll_loop
    ├─ tmux_manager.list_windows + discover_external_sessions
    ├─ periodic_tasks.run_periodic_tasks(bot, windows, timers)
    ├─ for (user_id, thread_id, wid) in thread_router.iter_thread_bindings():
    │  └─ window_tick.tick_window(bot, user_id, thread_id, wid, lookup[wid])
    │     ├─ _handle_dead(...)                 [if window is None]
    │     ├─ discover_and_register_transcript(...)
    │     ├─ if queue non-empty:
    │     │  ├─ _check_interactive_only(...)
    │     │  ├─ _scan_window_panes(...)
    │     │  └─ _maybe_check_passive_shell(...)
    │     └─ else:
    │        ├─ _update_status(...)             [owns the state machine]
    │        ├─ _scan_window_panes(...)
    │        └─ _maybe_check_passive_shell(...)
    └─ periodic_tasks.run_lifecycle_tasks(bot, windows)
```

**Contract**: `polling_coordinator` sees one public entry point from
`window_tick`. All per-window collaborators (`claude_task_state`,
`interactive_ui`, `topic_emoji`, `message_queue`, etc.) are imported by
`window_tick`, not by the coordinator.

### Flow 3: Topic cleanup

All four affected modules register per-topic cleanup via
`topic_state_registry.register_bound`:

- `message_queue` — drains queue, clears `_tool_msg_ids`
- `tool_batch` — clears `_active_batches`
- `status_bubble` — clears `_status_msg_info`
- `window_tick` — clears per-window poll state via
  `terminal_poll_state.clear_for_topic`, etc. (indirect — the
  strategies already register themselves)

No cross-module cleanup wiring. Each module owns its own state and its
own cleanup hook.

## Coupling Assessment

Volatility classification (from the Apr 13 review, maintainer-confirmed):
messaging and polling are **core subdomain, high volatility**;
`message_task` and `polling_coordinator` (post-refactor) are
**supporting, low volatility** — they act as firebreaks.

| #   | Integration                                                                                  | Strength   | Distance | Volatility                 | Balanced?      | Commentary                                                                                                                                                                                                             |
| --- | -------------------------------------------------------------------------------------------- | ---------- | -------- | -------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| 1   | `message_queue` → `message_task`                                                             | Contract   | Same pkg | High (uses)/Low (contract) | **Yes**        | The sum type is minimal explicit knowledge. Balanced because the distance is low and the contract is small.                                                                                                            |
| 2   | `tool_batch` → `message_task`                                                                | Contract   | Same pkg | Low (contract)             | **Yes**        | Same.                                                                                                                                                                                                                  |
| 3   | `status_bubble` → `message_task`                                                             | Contract   | Same pkg | Low (contract)             | **Yes**        | Same.                                                                                                                                                                                                                  |
| 4   | `message_queue` → `tool_batch`                                                               | Functional | Same pkg | High                       | **Yes**        | One-way call, co-located. Functional strength is appropriate because distance is low.                                                                                                                                  |
| 5   | `message_queue` → `status_bubble`                                                            | Functional | Same pkg | High                       | **Yes**        | Same.                                                                                                                                                                                                                  |
| 6   | ~~`tool_batch` → `message_queue`~~                                                           | —          | —        | —                          | **Eliminated** | Replaced by returning `ContentTask                                                                                                                                                                                     | None` from public API. |
| 7   | ~~`status_bubble` → `message_queue`~~                                                        | —          | —        | —                          | **Eliminated** | Replaced by returning `ContentTask                                                                                                                                                                                     | None`.                 |
| 8   | all cluster → `message_sender`                                                               | Functional | Same pkg | Low                        | **Yes**        | Shared kernel (send primitives). Low volatility; functional+local is fine.                                                                                                                                             |
| 9   | `polling_coordinator` → `window_tick`                                                        | Functional | Same pkg | High                       | **Yes**        | Single entry point (`tick_window`). Loop shell co-located with per-window module.                                                                                                                                      |
| 10  | `window_tick` → (~12 collaborators)                                                          | Functional | Same pkg | High                       | **Yes**        | High fan-out but low distance. The fan-out is _inherent to the problem_ (the poll cycle does 12 things); the win is that it is now concentrated in one cohesive module instead of scattered across a loop + 7 helpers. |
| 11  | `polling_coordinator` → `periodic_tasks`, `tmux_manager`, `thread_router`, `config`, `utils` | Functional | Same pkg | Low                        | **Yes**        | Loop concerns only.                                                                                                                                                                                                    |

**Key observation**: every remaining integration is **same package,
same process**. Distance is low across the board. The fix for Issue A
was therefore not to "decouple everything" (that would force a contract
boundary where none is needed) but to **reduce strength** on the two
specific back-edges that common-coupled the cluster. Functional
coupling between co-located modules in the same process is balanced by
the low distance — that is exactly what the balance rule predicts.

**Integrations that were strengthened, not weakened**: note that
`message_queue` still has _functional coupling_ to `tool_batch` and
`status_bubble` (rows 4, 5). That's correct. The problem was **never**
that `message_queue` called them — it was that they called back. The
fix is directional, not architectural.

## Design Decisions and Trade-offs

### Decision 1: Extract `message_task.py` as pure data, not as a module with helpers

**Alternative considered**: Put helpers like `is_mergeable(a, b)`,
`with_merged_parts(a, b)` on the `ContentTask` dataclass or alongside
it in the same module.

**Chosen**: Keep `message_task.py` zero-behavior. All helpers live in
`message_queue.py`.

**Why**: Helpers tend to grow. The moment `is_mergeable` needs to know
something about rate limiting or batch eligibility, it pulls dependencies
into the data module and the cycle comes back. Keeping the data module
_structurally incapable_ of importing from `handlers/` is the whole
point. It's cheap discipline — a one-line lint rule — and it prevents
the same mistake from recurring.

### Decision 2: Return `ContentTask | None` instead of injecting a callback

**Alternative considered**: Pass `process_content_task: Callable[[ContentTask], Awaitable[None]]`
as a constructor argument to `tool_batch` and `status_bubble`, so they
can invoke it directly.

**Chosen**: Return data; let the queue worker invoke the primitive.

**Why**: Callback injection is a reasonable pattern but it creates a
subtle runtime coupling that's harder to test. Returning data is
functional — the same input produces the same output, and unit tests
can assert "given this input, the function returns this ContentTask"
without any stubbing. It also keeps the public API small and obvious:
three public functions per module, each with a typed return value.

### Decision 3: Do not split `window_tick` into `classify()` + `apply_effects()`

**Alternative considered**: Extract the decision logic in
`_update_status` into a pure `classify(pane_state) -> TickAction`
function returning a sum type, then a separate `apply_effects(action)`
function for side effects. This is the "functional core, imperative
shell" pattern.

**Chosen**: Defer. The Round 2 refactor plan explicitly cautioned
against premature state-machine extraction, and the Apr 14 review
corroborated it. First we want to see whether a single cohesive
`window_tick` module is stable under real feature pressure — if it is,
the split is unnecessary; if it isn't, we'll know exactly which
decisions deserve to be lifted out.

**When to revisit**: If a third per-window concern is added that
introduces a new dimension to the decision table (e.g., a notification
priority system that varies by provider _and_ by task state), the
state machine has grown enough to justify extraction.

### Decision 4: Keep the queue worker as the only owner of `_process_content_task`

**Alternative considered**: Move `_process_content_task` into a shared
`content_delivery.py` module that `message_queue`, `tool_batch`, and
`status_bubble` all call.

**Chosen**: Keep the primitive private to `message_queue`.

**Why**: `_process_content_task` does rate limiting, fallback
formatting, and `_tool_msg_ids` bookkeeping. That bookkeeping is
queue-local (the queue _is_ the thing that knows which tool_use
messages are still alive). Exposing the primitive would pull its
state out too. It's cheaper to keep the primitive private and route
through the return-a-ContentTask contract.

### Decision 5: Implement Issue A before Issue B

**Why**: Issue A is the root cause of the six rounds of "fix: address
code review findings" commits on the refactor branch. Issue B is a
god-loop that _already works_. Fixing A first makes every subsequent
change to the messaging cluster cheaper; fixing B first would not
unblock anything. Also, the two fixes are independent — they touch
disjoint files — so they can be PR'd separately and reviewed
separately.

### Decision 6: No contract boundary between `window_tick` and its collaborators

**Alternative considered**: Define a `WindowTickContext` protocol that
abstracts the ~12 collaborators `window_tick` talks to, and inject it
for testability.

**Chosen**: Keep direct functional calls to concrete modules.

**Why**: All the collaborators are in the same package, same process,
same deployment unit, and owned by the same maintainer. Introducing a
protocol here would be pure overhead — it increases strength (now
there's an explicit contract _and_ an implementation) without
decreasing distance (everything is still co-located). The balance rule
rewards this trade-off: low distance + functional strength is fine,
and a protocol would add cognitive load without reducing cascading
changes.

## Migration Plan

**Phase 1 — Fix A (messaging cluster)**: ~1-2 days, single branch.

1. Create `handlers/message_task.py` with the sum type. Add the
   `MessageTask = ContentTask | StatusUpdateTask | StatusClearTask`
   alias. Zero callers yet.
2. Switch `handlers/message_queue.py` to import the new types. Keep the
   old `@dataclass MessageTask` as a temporary alias for one commit to
   minimize diff; delete in the next.
3. Change `tool_batch.process_tool_event` signature to take `ContentTask`
   and return `ContentTask | None`. Update all internal helpers. Delete
   the local `from .message_queue import process_content_task` lines.
4. Change `status_bubble.process_status_update` / `process_status_clear`
   similarly. Delete the TYPE_CHECKING import of `MessageTask`.
5. Rewrite the queue worker's `_dispatch` to use `match` with the sum
   type. Add the content-delivery fallback for returned `ContentTask`s.
6. Add the "no back-edge" AST test in `test_message_queue.py` and
   `test_tool_batch.py`. Run the full suite.
7. Squash and land.

**Phase 2 — Fix B (polling decomposition)**: ~2-3 days, separate branch.

1. Create `handlers/window_tick.py`. Initially re-export
   `tick_window` as a thin wrapper that just calls the existing
   per-window helpers. This lets `polling_coordinator` switch to the
   new API without behavior change.
2. Move `_update_status`, `_handle_no_status`, `_check_interactive_only`,
   `_scan_window_panes`, `_maybe_check_passive_shell`,
   `_transition_to_idle`, `_handle_dead_window_notification` from
   `polling_coordinator.py` into `window_tick.py`. Resolve imports.
3. Reduce `polling_coordinator.status_poll_loop` to the loop shell
   shown in `polling_coordinator/design.md`.
4. Delete per-window imports from `polling_coordinator.py`.
5. Add the line-count canary test (`wc -l` ≤ 120 on
   `polling_coordinator.py`).
6. Run the full suite, verify `test_status_polling.py` still passes
   (it should — behavior is unchanged).
7. Land.

**Not in this pass**:

- `WindowView` migration for the remaining 71 call sites (Issue C).
- Further `window_tick` decomposition (classify + effects).
- `session.py` decomposition.

## Unresolved Risks

### R1 — `_tool_msg_ids` bookkeeping across overflow flushes (verified non-regression)

`_tool_msg_ids` lives in `message_queue.py` and records the Telegram
message id of each tool_use so that the matching tool_result can edit
it in place. When `tool_batch` flushes a batch, it is the module that
knows which message id is being edited. Today the bookkeeping works
because `tool_batch` is the one calling the edit — but under the new
"return data" contract, the queue worker might re-process a tool_result
that `tool_batch` rejected, and both modules need to agree on the
message id.

**Mitigation**: The dispatcher calls `tool_batch.flush_if_active`
_before_ handing the next task to `_process_content_task`. The flush
path finalizes the batch edit and records the final message id in
`_tool_msg_ids`. Subsequent `tool_result` tasks for the same
`tool_use_id` find the entry and edit in place.

**Verified against current code**: after overflow+flush, entries are
removed from `_active_batches`; late tool_results for pre-overflow
`tool_use_id`s already become standalone messages in the current
implementation. The new design preserves this behavior exactly — it
is **not a regression**, just a minor UX quirk worth knowing about.

**Revisit if**: Integration tests show a tool_result landing on the
wrong message after an overflow flush. In that case, extract a tiny
`tool_msg_registry.py` module that both `message_queue` and
`tool_batch` import, so they share a single source of truth for
`tool_use_id → message_id` mappings.

### R5 — Implicit `thread_id_or_0` convention across the cluster

All three messaging-cluster modules coerce `thread_id: int | None`
to `0` for use as a dict key (`_tool_msg_ids`, `_active_batches`,
`_status_msg_info`). The convention is duplicated across three
modules — if one changes (e.g., uses `-1` or `None` directly), the
others silently drift.

**Mitigation (fold into Phase 1)**: Add a single helper to
`handlers/message_task.py`:

```python
def thread_key(thread_id: int | None) -> int:
    """Canonical int key for dicts keyed by topic thread id."""
    return thread_id or 0
```

All three modules import and use it. One line to change if the
convention ever needs to evolve.

**Severity**: Minor. Fix during Phase 1 while touching the affected
modules anyway — cost is trivial, future-proofing is real.

### R2 — `window_tick` fan-out keeps growing

`window_tick` imports ~12 cooperating modules today. Every new
per-window concern (new provider capability, new notification mode)
will add another import. If it hits ~20, the module becomes hard to
reason about.

**Mitigation**: The state machine is the cognitive complexity driver,
not the fan-out count. If the decision logic starts to get genuinely
hard to follow, that is the signal to extract `classify()` and
`apply_effects()` (Decision 3's deferred alternative), not to split the
file by category.

**Revisit if**: A contributor complains that they can't figure out
which branch runs for their scenario, or if more than three new
branches are added to `_update_status` in a single feature.

### R3 — The sum type's exhaustiveness depends on pyright

Python's runtime doesn't enforce `match` exhaustiveness on a Union.
pyright `--strict` does. If CI type-checking is relaxed or skipped, a
new variant could be added to `MessageTask` without updating the
dispatcher, and the new variant would silently fall through to the
default case.

**Mitigation**: The dispatcher's default case logs a `logger.error`
and drops the task — noisy enough to be caught in dev. The
`test_union_alias_covers_all_concrete_variants` runtime test guards
against the opposite mistake (dropping a variant from the alias).

**Revisit if**: pyright strict mode is disabled for any reason. At
that point, consider generating an exhaustiveness guard via
`typing.assert_never` in the dispatcher's default branch.

### R4 — Backwards compatibility for `_do_*` helpers removed

Some tests in `test_message_queue.py` and `test_status_bubble.py`
currently patch private helpers like `_do_send_status_message`. After
the refactor, those helpers may be reshaped or removed.

**Mitigation**: Rewrite those tests during Phase 1 to use the new
public API (`process_status_update`, `process_status_clear`). The
public contracts are deliberately narrow (three functions per module)
so the rewrite is mechanical.

**Revisit if**: The rewrite reveals that a test was asserting
something the new API can't express. That would be a sign the new API
is missing something, not that the tests were right.
