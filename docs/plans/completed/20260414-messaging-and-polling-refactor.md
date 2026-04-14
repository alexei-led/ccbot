# Messaging Cluster + Polling Loop Refactor

## Overview

Implements Issues A and B from
[`docs/modularity-review/2026-04-14/modularity-review.md`](../modularity-review/2026-04-14/modularity-review.md),
following the design in
[`docs/design/2026-04-14/`](../design/2026-04-14/).

**Phase 1 — Issue A (messaging cluster)**: extract `MessageTask` into a
neutral `handlers/message_task.py` as a proper sum type, change
`tool_batch` and `status_bubble` to return `ContentTask | None` instead
of calling back into `message_queue`, and rewrite the worker dispatcher
as a `match` statement. Eliminates two structural import cycles caused
by the union dataclass living in `message_queue.py` while the
functions that operated on it lived elsewhere.

**Phase 2 — Issue B (polling decomposition)**: extract a new
`handlers/window_tick.py` that owns all per-window poll-cycle logic,
and reduce `handlers/polling_coordinator.py` to a ~100-line outer loop
shell. Eliminates 13 imports from the coordinator and concentrates the
state machine in one cohesive module.

Both phases preserve observable behavior. They are independent and
land on separate branches.

## Context (from discovery)

- Design source: `docs/design/2026-04-14/{architecture.md, message_task/, message_queue/, tool_batch/, status_bubble/, window_tick/, polling_coordinator/}`
- Modules touched (Phase 1): `src/ccgram/handlers/message_queue.py`, `src/ccgram/handlers/tool_batch.py`, `src/ccgram/handlers/status_bubble.py`
- Modules touched (Phase 2): `src/ccgram/handlers/polling_coordinator.py`
- New modules: `src/ccgram/handlers/message_task.py` (Phase 1), `src/ccgram/handlers/window_tick.py` (Phase 2)
- Tests touched: `tests/ccgram/handlers/test_message_queue.py`, `test_tool_batch.py`, `test_status_bubble.py`, `test_status_polling.py`, `test_polling_strategies.py`
- Conventions observed: `pytest` with `asyncio_mode = "auto"`, no docstrings in test files, dataclasses with frozen+slots where possible, `topic_state_registry.register_bound()` for per-topic cleanup
- Project tooling: `make check` (fmt + lint + typecheck + test); `make test` for unit tests only

## Development Approach

- **Testing approach**: Regular (code first, then tests). Each task implements the change, then immediately writes/updates tests for it, then runs the suite before moving on.
- **CRITICAL**: every task includes new/updated tests for the code it touches — tests are not optional.
- **CRITICAL**: all tests must pass before starting the next task — no exceptions.
- **CRITICAL**: update this plan file when scope changes during implementation.
- Make small, focused changes. One task = one logical refactor.
- After each task: `make fmt && make lint && make typecheck && make test` must be green.
- Phase 1 lands first (its own branch). Phase 2 lands second (its own branch). They share no files.
- Preserve observable behavior — these are pure refactors, not feature changes.
- Do not introduce backwards-compatibility shims — the union `MessageTask` is deleted in the same task that introduces the sum type.

## Testing Strategy

- **Unit tests**: required for every task. The design documents under `docs/design/2026-04-14/{module}/tests.md` enumerate the expected test cases per module — each task implements the relevant subset.
- **AST tests**: Phase 1 introduces three "no back-edge" tests that walk module ASTs to assert `tool_batch` and `status_bubble` never import from `.message_queue`. These are the canary tests that protect the whole Issue A fix.
- **Line-count canary**: Phase 2 introduces a `wc -l` test asserting `polling_coordinator.py` ≤ 120 lines.
- **No e2e tests required**: the project has e2e tests under `tests/e2e/` for agent CLI lifecycle, but neither phase touches agent CLI behavior or UI flows. `make test-e2e` is not in scope.
- **Integration tests**: `tests/integration/test_message_dispatch.py` and friends should continue to pass unchanged. If they fail, the refactor changed observable behavior — investigate before "fixing" the test.

## Progress Tracking

- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix
- update plan if implementation deviates from original scope
- keep plan in sync with actual work done

## Solution Overview

### Phase 1 dependency graph (target)

```
       message_task (pure data, zero handler deps)
          ▲          ▲          ▲
          │          │          │
   message_queue → tool_batch
          │
          ▼
    status_bubble
```

`message_queue` depends on the other two; the other two depend only on `message_task` and shared kernel modules (`message_sender`, `thread_router`, `topic_state_registry`). All cycles eliminated.

### Phase 2 dependency graph (target)

```
   polling_coordinator (loop shell, ~100 lines, ~6 imports)
          │
          ▼
     window_tick (per-window poll cycle, ~450 lines)
          │
          ▼
     ~12 collaborators (tmux, providers, polling_strategies,
                        interactive_ui, topic_emoji, etc.)
```

`polling_coordinator` no longer imports any per-window collaborator directly. All per-window decisions concentrated in `window_tick`.

### Key design decisions (recap from architecture.md)

1. **Return data instead of injecting callbacks** — `tool_batch.process_tool_event` and `status_bubble.process_status_update` return `ContentTask | None`; the queue worker handles the followup. No callback indirection.
2. **`message_task.py` is structurally incapable of importing handlers** — enforces the firebreak via discipline + lint.
3. **`_process_content_task` stays private to `message_queue`** — owns rate limiting, fallback formatting, and `_tool_msg_ids` bookkeeping. Other modules return `ContentTask`s for it to process.
4. **Defer further `window_tick` decomposition** — do the extraction first; only split into `classify()`/`apply_effects()` if real friction emerges.
5. **`thread_key()` helper in `message_task.py`** — single canonical `int | None → int` coercion for dict keys. Eliminates R5 implicit common coupling.

## Technical Details

### `MessageTask` sum type

```python
@dataclass(frozen=True, slots=True)
class ContentTask:
    window_id: str
    parts: tuple[str, ...]
    content_type: Literal["text", "tool_use", "tool_result"] = "text"
    tool_use_id: str | None = None
    tool_name: str | None = None
    thread_id: int | None = None

@dataclass(frozen=True, slots=True)
class StatusUpdateTask:
    window_id: str
    text: str | None
    thread_id: int | None = None

@dataclass(frozen=True, slots=True)
class StatusClearTask:
    window_id: str | None
    thread_id: int | None = None

MessageTask = ContentTask | StatusUpdateTask | StatusClearTask

def thread_key(thread_id: int | None) -> int:
    return thread_id or 0
```

### Dispatcher contract (queue worker)

```python
async def _dispatch(bot: Bot, user_id: int, task: MessageTask) -> None:
    match task:
        case ContentTask() as ct:
            if tool_batch.is_batch_eligible(ct):
                followup = await tool_batch.process_tool_event(bot, user_id, ct)
                if followup is not None:
                    await _process_content_task(bot, user_id, followup)
            else:
                await tool_batch.flush_if_active(bot, user_id, ct)
                await _process_content_task(bot, user_id, ct)
        case StatusUpdateTask() as st:
            followup = await status_bubble.process_status_update(bot, user_id, st)
            if followup is not None:
                await _process_content_task(bot, user_id, followup)
        case StatusClearTask() as cl:
            await status_bubble.process_status_clear(bot, user_id, cl)
```

### `tool_batch.process_tool_event` new signature

```python
async def process_tool_event(
    bot: Bot, user_id: int, task: ContentTask
) -> ContentTask | None:
    """Returns None if absorbed; ContentTask if the queue worker should
    process it as content (overflow, ineligible result, etc)."""
```

### `status_bubble.process_status_update` new signature

```python
async def process_status_update(
    bot: Bot, user_id: int, task: StatusUpdateTask
) -> ContentTask | None:
    """Returns None if absorbed; ContentTask if the bubble was promoted
    to content."""
```

### `window_tick.tick_window` signature

```python
async def tick_window(
    bot: Bot,
    user_id: int,
    thread_id: int,
    window_id: str,
    window: TmuxWindow | None,
) -> None:
    """Run one poll cycle for one binding. All per-window logic lives here."""
```

### `polling_coordinator.status_poll_loop` reduced shape

```python
async def status_poll_loop(bot: Bot) -> None:
    interval = config.status_poll_interval
    timers = {"topic_check": 0.0, "broker": 0.0, "sweep": 0.0, "live_view": 0.0}
    error_streak = 0
    while True:
        try:
            windows = await tmux_manager.list_windows()
            windows.extend(await tmux_manager.discover_external_sessions())
            lookup = {w.window_id: w for w in windows}
            await run_periodic_tasks(bot, windows, timers)
            for user_id, thread_id, wid in list(thread_router.iter_thread_bindings()):
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(window_id=wid)
                try:
                    await window_tick.tick_window(
                        bot, user_id, thread_id, wid, lookup.get(wid)
                    )
                except (TelegramError, OSError) as e:
                    log_throttled(logger, f"tick:{user_id}:{thread_id}", "...", e)
            await run_lifecycle_tasks(bot, windows)
            error_streak = 0
        except (TelegramError, OSError, RuntimeError, ValueError):
            logger.exception("status poll loop error")
            error_streak += 1
            await asyncio.sleep(min(_BACKOFF_MAX, _BACKOFF_MIN * 2**error_streak))
            continue
        await asyncio.sleep(interval)
```

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): all code, tests, and AST guards within `src/ccgram/` and `tests/`.
- **Post-Completion** (no checkboxes): manual verification scenarios, post-merge release-notes update.

## Implementation Steps

### Phase 1 — Issue A: Messaging Cluster

#### Task 1: Create `message_task.py` with sum type and `thread_key` helper

**Files:**

- Create: `src/ccgram/handlers/message_task.py`
- Create: `tests/ccgram/handlers/test_message_task.py`

- [x] create `src/ccgram/handlers/message_task.py` with module docstring per project convention
- [x] add `ContentTask`, `StatusUpdateTask`, `StatusClearTask` frozen+slots dataclasses (fields per design doc)
- [x] add `MessageTask = ContentTask | StatusUpdateTask | StatusClearTask` union alias
- [x] add `thread_key(thread_id: int | None) -> int` helper
- [x] verify the module imports nothing from `ccgram.handlers` (only stdlib + typing)
- [x] write tests in `tests/ccgram/handlers/test_message_task.py`: frozenness, hashability, `parts` tuple, optional fields, exhaustiveness via runtime `__args__` check
- [x] write tests for `thread_key` (None → 0, int → int, 0 → 0)
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 2

#### Task 2: Switch `tool_batch.py` to use `ContentTask` and return data

**Files:**

- Modify: `src/ccgram/handlers/tool_batch.py`
- Modify: `tests/ccgram/handlers/test_tool_batch.py`

- [x] in `tool_batch.py`, change `from .message_queue import MessageTask` (TYPE_CHECKING) to `from .message_task import ContentTask`
- [x] change `is_batch_eligible(task: MessageTask, window_id: str) -> bool` signature to `is_batch_eligible(task: ContentTask) -> bool`; derive `window_id` from `task.window_id`
- [x] change `process_tool_event(bot, user_id, task: MessageTask) -> None` to `process_tool_event(bot, user_id, task: ContentTask) -> ContentTask | None`
- [x] in `_handle_tool_result`, replace `from .message_queue import process_content_task; await process_content_task(...)` with `return task` (queue worker handles followup)
- [x] in the overflow branch of `process_tool_event`, replace the local `from .message_queue import process_content_task` with `return task`
- [x] add `flush_if_active(bot, user_id, task: ContentTask) -> None` as the public flush helper called by the queue worker before delivering non-batchable content
- [x] use `thread_key(task.thread_id)` for `_active_batches` keys
- [x] verify no `from .message_queue` lines remain anywhere in `tool_batch.py` (module scope, function scope, TYPE_CHECKING)
- [x] update `tests/ccgram/handlers/test_tool_batch.py` to call the new signatures and assert returned `ContentTask | None`
- [x] add the AST guard test `test_no_import_from_message_queue` per design's `tool_batch/tests.md`
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 3

#### Task 3: Switch `status_bubble.py` to use the sum type and return data

**Files:**

- Modify: `src/ccgram/handlers/status_bubble.py`
- Modify: `tests/ccgram/handlers/test_status_bubble.py`

- [x] in `status_bubble.py`, replace TYPE_CHECKING import of `MessageTask` with `from .message_task import ContentTask, StatusUpdateTask, StatusClearTask`
- [x] change `process_status_update_task(bot, user_id, task: MessageTask)` → `process_status_update(bot, user_id, task: StatusUpdateTask) -> ContentTask | None`
- [x] change `process_status_clear_task` → `process_status_clear(bot, user_id, task: StatusClearTask) -> None`
- [x] in `convert_status_to_content`, return a `ContentTask` instead of calling `process_content_task` directly
- [x] use `thread_key(task.thread_id)` for `_status_msg_info` keys
- [x] verify no `from .message_queue` lines remain anywhere in `status_bubble.py`
- [x] update `tests/ccgram/handlers/test_status_bubble.py` to call the new signatures
- [x] add the AST guard test `test_no_import_from_message_queue` per design's `status_bubble/tests.md`
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 4

#### Task 4: Rewrite `message_queue.py` worker dispatcher and delete the old `MessageTask`

**Files:**

- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `tests/ccgram/handlers/test_message_queue.py`

- [x] delete the local `@dataclass class MessageTask` from `message_queue.py`
- [x] import `ContentTask, StatusUpdateTask, StatusClearTask, MessageTask, thread_key` from `.message_task`
- [x] rewrite the worker `_dispatch` (or equivalent) as a `match` over the sum type per the design's dispatcher contract
- [x] in the `ContentTask` branch: call `tool_batch.is_batch_eligible(ct)`; if True, await `process_tool_event` and if it returns a followup, run `_process_content_task(followup)`; otherwise await `tool_batch.flush_if_active(ct)` then `_process_content_task(ct)`
- [x] in the `StatusUpdateTask` branch: await `status_bubble.process_status_update`; if it returns a followup, run `_process_content_task(followup)`
- [x] in the `StatusClearTask` branch: await `status_bubble.process_status_clear`
- [x] update all `enqueue_*` helpers to construct the correct concrete dataclass (no more grab-bag `MessageTask(task_type=...)`)
- [x] update merge logic (`_can_merge_tasks`, `_collect_mergeable_tasks`) to take and return `ContentTask` only — status tasks never merge
- [x] use `thread_key(task.thread_id)` for `_tool_msg_ids` keys
- [x] update `tests/ccgram/handlers/test_message_queue.py` to use concrete dataclasses; cover all four dispatch branches per design's `message_queue/tests.md`
- [x] add the AST guard test `test_no_back_edge_imports` (walks `tool_batch.py` and `status_bubble.py`)
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 5

#### Task 5: Update all `enqueue_*` call sites and integration tests

**Files:**

- Modify: `src/ccgram/handlers/cleanup.py`
- Modify: `src/ccgram/handlers/command_orchestration.py`
- Modify: `src/ccgram/handlers/hook_events.py`
- Modify: `src/ccgram/handlers/message_routing.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/text_handler.py`
- Modify: `tests/integration/test_message_dispatch.py` (if it constructs `MessageTask` directly)
- Modify: `tests/ccgram/test_status_singleton.py`, `tests/ccgram/test_status_polling.py`, `tests/ccgram/test_status_buttons.py`, `tests/ccgram/test_status_recall_callback.py`, `tests/ccgram/test_tool_batching.py` (if any reference `MessageTask` fields directly)

- [x] grep for `MessageTask(` and `task_type=` across `src/` and `tests/`; update each call site to construct the right concrete dataclass
- [x] grep for `task.tool_use_id`, `task.parts`, `task.text` on union typed values; ensure each access is inside a branch that has narrowed the type
- [x] verify pyright `--strict` is happy with all narrowing (no `reportOptionalMemberAccess` warnings on the new dataclasses)
- [x] update any test that constructs a `MessageTask` directly to use the right concrete dataclass instead
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 6
- [x] run `make test-integration` — must pass

#### Task 6: Phase 1 acceptance verification

- [x] verify the dependency graph: `grep -rn "from .message_queue" src/ccgram/handlers/tool_batch.py src/ccgram/handlers/status_bubble.py` returns zero matches (module, function, and TYPE_CHECKING scope)
- [x] verify `MessageTask` is no longer defined in `message_queue.py` (only imported from `message_task.py`)
- [x] verify `make check` passes (fmt + lint + typecheck + test)
- [x] verify `make test-integration` passes
- [x] manually exercise the bot for ~5 minutes (skipped — not automatable, deferred to post-merge)

### Phase 2 — Issue B: Polling Loop Decomposition

#### Task 7: Create `window_tick.py` skeleton with `tick_window` entry point

**Files:**

- Create: `src/ccgram/handlers/window_tick.py`
- Create: `tests/ccgram/handlers/test_window_tick.py`

- [x] create `src/ccgram/handlers/window_tick.py` with module docstring per project convention
- [x] declare `async def tick_window(bot, user_id, thread_id, window_id, window) -> None` as the only public function
- [x] in the initial commit, have `tick_window` import the existing per-window helpers from `polling_coordinator` and call them — this is a thin wrapper for one commit, before the move
- [x] write a smoke test in `tests/ccgram/handlers/test_window_tick.py` that asserts `tick_window` exists and is callable
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 8

#### Task 8: Move per-window helpers from `polling_coordinator.py` into `window_tick.py`

**Files:**

- Modify: `src/ccgram/handlers/polling_coordinator.py`
- Modify: `src/ccgram/handlers/window_tick.py`
- Modify: `tests/ccgram/handlers/test_window_tick.py`

- [x] move `_send_typing_throttled` from `polling_coordinator` into `window_tick` (private helper)
- [x] move `_parse_with_pyte` similarly
- [x] move `_check_transcript_activity`, `_transition_to_idle`, `_handle_no_status` similarly
- [x] move `_scan_window_panes`, `_check_interactive_only`, `_maybe_check_passive_shell` similarly
- [x] move `_handle_dead_window_notification` similarly
- [x] move `update_status_message` and rename to `_update_status` (private to `window_tick`)
- [x] update `window_tick.tick_window` body to inline the per-binding logic that currently lives in `status_poll_loop`'s inner loop (dead detection → transcript discovery → queue check → interactive-only or status-update branch → pane scan → passive shell)
- [x] update imports in `window_tick.py`: it now needs `claude_task_state`, `providers`, `tmux_manager`, `cleanup`, `interactive_ui`, `message_queue`, `message_sender`, `polling_strategies`, `recovery_callbacks`, `topic_emoji`, `transcript_discovery`, `thread_router`, `session`
- [x] update imports in `polling_coordinator.py`: delete all of the above; add `from . import window_tick`
- [x] write tests in `test_window_tick.py` per the design doc's per-branch unit tests (state machine branches, interactive precedence, queue-non-empty fast path, dead window, etc.)
- [x] move relevant test cases from `tests/ccgram/test_status_polling.py` into `test_window_tick.py` where they exercise per-window behavior
- [x] add the contract tests: `test_tick_window_is_sole_public_function`, `test_polling_coordinator_imports_only_tick_window`, `test_polling_coordinator_does_not_import_per_window_collaborators`
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 9

#### Task 9: Reduce `polling_coordinator.status_poll_loop` to outer-shell form

**Files:**

- Modify: `src/ccgram/handlers/polling_coordinator.py`
- Modify: `tests/ccgram/handlers/test_polling_coordinator.py`

- [x] simplify `status_poll_loop` body to: enumerate windows + external → build lookup → `run_periodic_tasks` → for each binding `await window_tick.tick_window(...)` → `run_lifecycle_tasks` → backoff handling
- [x] delete now-unused imports: `claude_task_state`, `providers`, `providers.base`, `session`, `session_monitor`, `cleanup`, `interactive_ui`, `message_queue`, `message_sender`, `polling_strategies`, `recovery_callbacks`, `topic_emoji`, `transcript_discovery`
- [x] keep imports: `window_tick`, `periodic_tasks`, `tmux_manager`, `thread_router`, `config`, `utils`, `structlog`, `telegram.error`
- [x] verify the file is now ≤ 120 lines
- [x] add the line-count canary test `test_module_line_count_under_ceiling` per design's `polling_coordinator/tests.md`
- [x] add the import whitelist test `test_imports_are_minimal`
- [x] update `tests/ccgram/handlers/test_polling_coordinator.py` to mock `window_tick.tick_window` and assert iteration / periodic tasks / backoff (no per-window behavior tests left here — those live in `test_window_tick.py`)
- [x] run `make fmt && make lint && make typecheck && make test` — must pass before Task 10
- [x] run `make test-integration` — must pass

#### Task 10: Phase 2 acceptance verification

- [x] `wc -l src/ccgram/handlers/polling_coordinator.py` — must be ≤ 120 (actual: 92)
- [x] `grep -c "^from\|^import" src/ccgram/handlers/polling_coordinator.py` — must be ≤ 12 (actual: 9)
- [x] verify `make check` passes (3562 passed)
- [x] verify `make test-integration` passes (95 passed)
- [x] manually exercise the bot for ~5 minutes (skipped - not automatable, deferred to Post-Completion)

### Final tasks

#### Task 11: Verify acceptance criteria

- [x] all Issue A goals from `architecture.md` met (zero back-edges, sum type adopted, `thread_key` helper landed)
- [x] all Issue B goals met (`polling_coordinator` ≤ 120 lines, 13 imports deleted, `window_tick` is the only entry point)
- [x] full test suite green: `make check`
- [x] integration tests green: `make test-integration`
- [x] no `MessageTask(` constructor calls remain in the codebase
- [x] no `from .message_queue import` lines in `tool_batch.py` or `status_bubble.py`

#### Task 12: Update documentation

- [x] update `.claude/rules/architecture.md` Module Inventory table to reflect new modules (`message_task.py`, `window_tick.py`) and the slimmed `polling_coordinator.py`
- [x] update `.claude/rules/message-handling.md` if the message queue's behavior description is now stale
- [x] add a "Resolution" section to `docs/modularity-review/2026-04-14/modularity-review.md` linking back to this plan
- [x] move this plan to `docs/plans/completed/`

## Post-Completion

_Items requiring manual intervention or external systems — no checkboxes, informational only._

**Manual verification** after Phase 1 lands and after Phase 2 lands:

- Smoke test with a real Claude Code session: send a message, observe tool_use → tool_result edit-in-place; observe status bubble transitions; observe topic emoji updates.
- Smoke test with a real Codex session: send a message, observe status bubble transitions (no tool batching expected).
- Smoke test with a real shell session: send a command, observe passive output relay, observe `!` raw command path.
- Smoke test multi-pane window: open a Claude agent team window, observe interactive prompts surfaced from non-active panes.
- Smoke test dead window detection: kill a tmux window externally, observe recovery keyboard within ~2s.

**Release notes** (post-Phase-2):

- Mention the architectural cleanup in CHANGELOG.md under "Internal" — no user-visible behavior change.
- No version bump required; this is a refactor, not a feature.

**Risks to monitor** post-merge (from `architecture.md` Unresolved Risks):

- R1 — `_tool_msg_ids` bookkeeping across overflow flushes: behavior preserved, but watch for any reports of tool_results landing on the wrong message.
- R2 — `window_tick` fan-out growth: if a contributor adds a third new branch to `_update_status` within a few weeks, that's the signal to extract `classify()` / `apply_effects()` (deferred Decision 3).
- R3 — sum type exhaustiveness depends on pyright `--strict`: if CI type-checking is ever relaxed, add `assert_never` in the dispatcher's default branch as a runtime guard.
