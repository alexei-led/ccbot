# Modularity Refactor — Review Follow-up

## Overview

Address the seven issues identified in `docs/modularity-review/2026-04-12/modularity-review-evening.md`. The refactor is behavior-preserving and phased by payoff-to-cost ratio. No new features, no new tests beyond those needed to cover newly-extracted modules or new types, no speculative abstractions.

**Problem it solves**: The morning review identified six issues; five were partially or fully resolved earlier today. The evening review re-scoped remaining work to seven issues grouped into quick wins, medium-payoff cohesion fixes, and three larger structural refactors tied to the user's confirmed pain points (adding providers, state-shape changes, following polling code).

**Guiding principle**: Every task is incremental, reversible, and keeps the existing test suite green. No task depends on the user tolerating a half-migrated state across multiple commits.

## Context (from discovery)

**Review source**: `docs/modularity-review/2026-04-12/modularity-review-evening.md`

**Files/components involved** (confirmed from exploration):

- `src/ccgram/providers/base.py` — Telegram-specific constants that don't belong
- `src/ccgram/providers/claude.py` — imports `hook.UUID_RE` that should be in base
- `src/ccgram/providers/shell.py` — overloaded module (provider class + infrastructure)
- `src/ccgram/session.py` — duplicated `session_map` logic (`load_session_map`, `register_hookless_session`, `write_hookless_session_map`, `prune_session_map`)
- `src/ccgram/session_map.py` — canonical `session_map` implementation
- `src/ccgram/window_state_store.py`, `src/ccgram/thread_router.py`, `src/ccgram/user_preferences.py`, `src/ccgram/session_map.py` — four singletons with deferred `_schedule_save = lambda: None`
- `src/ccgram/handlers/message_queue.py` — 1184 lines, six concerns
- `src/ccgram/handlers/hook_events.py` — owns `build_subagent_label` / `get_subagent_names` that belong elsewhere
- `src/ccgram/handlers/shell_commands.py` ↔ `src/ccgram/handlers/shell_capture.py` — mutual import
- `src/ccgram/handlers/polling_coordinator.py` — 598-line god loop, 9 handler imports
- `src/ccgram/handlers/polling_strategies.py` — strategies exist but don't own their tick cadence
- `src/ccgram/llm/summarizer.py` — hardcodes Claude JSONL parsing
- Handlers that string-check `provider_name`: `transcript_discovery.py`, `recovery_callbacks.py`, `window_callbacks.py`
- Handlers with one-call `session_manager` reads (targets for `WindowView`): `file_handler.py`, `history.py`, `shell_commands.py`, `text_handler.py`, `send_command.py`, `screenshot_callbacks.py`, `topic_emoji.py`

**Related patterns found**:

- Deferred callback wiring pattern for persistence (`_schedule_save`)
- `topic_state_registry` event bus for scoped cleanup callbacks
- `@register(prefix)` decorator for callback dispatch
- Provider capability flags (`ProviderCapabilities` dataclass)
- Strategy singletons (`terminal_strategy`, `interactive_strategy`, `lifecycle_strategy`, `delivery_strategy`)

**Dependencies identified**:

- PTB (python-telegram-bot) handler registration
- `pytest` with `asyncio_mode = "auto"`
- `make check` = fmt + lint + typecheck + test + integration
- Refactor must preserve all state.json / session_map.json / events.jsonl I/O semantics

## Development Approach

- **testing approach**: Verify-refactor-verify. Run `make check` (or at least `make test` + `make typecheck`) before each task; make the change; run again. Existing tests are the spec for behavior-preserving refactors.
- complete each task fully before moving to the next
- make small, focused changes — each task is one logical refactor
- **CRITICAL**: Each task must end with `make check` passing before starting the next
- new code added during refactor (new module headers, `WindowView` dataclass, new `tick()` signatures) gets new tests for the added surface; moved code relies on existing tests
- update this plan file when scope changes during implementation
- no backward-compatibility shims — this is a feature branch

## Testing Strategy

- **unit tests**: when a task creates a new module with non-trivial logic (`status_bubble.py`, `shell_context.py`, `WindowView`, new polling `tick()` methods), add unit tests for the new surface. Pure movements of existing functions do not require new tests — the existing suite covers behavior.
- **integration tests**: existing `tests/integration/*` suite must stay green. Integration tests patch by module path, so any move invalidates patch targets — update them in the same task as the move.
- **no e2e required**: e2e tests (`tests/e2e/`) exercise real agent CLIs and take 3–4 minutes. Run once at the end of Phase 2 and Phase 3 as a final verification, not per-task.

**Per-task verification gate**: `make check` green. If `make check` red, fix before proceeding.

## Progress Tracking

- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix
- update plan if implementation deviates from original scope

## Solution Overview

**Phased approach**, ordered by payoff-to-cost ratio:

**Phase 1 — Quick wins** (cheap, high-confidence removes boundary violations): move misplaced constants, delete duplicated code, fail-loud defaults.

**Phase 2 — Cohesion fixes and circular-import breaks**: split `message_queue`, move subagent helpers out of `hook_events`, extract `shell_context`, replace provider-name string checks.

**Phase 3 — Structural refactors** (largest blast radius, largest payoff for stated pain): introduce `WindowView` projection, extract `shell_infra`, invert `polling_coordinator` to strategy-owned ticks.

**Key design decisions**:

1. Don't split `SessionManager`. The god-object pattern is tolerable at solo-dev distance. Address the pain via a `WindowView` read-only projection instead.
2. Don't introduce DI. Keep module-level singletons but make them fail loudly when unwired.
3. Don't attempt `WindowContext` aggregation (morning review's primary recommendation). It's a multi-week refactor and Phase 3 already delivers most of the testability win.
4. Keep `polling_coordinator` at 1-second cadence — invert _control_, not _timing_.
5. **Intentionally deferred**: `llm/summarizer.py` hardcoding Claude JSONL format (Issue 1, point 5 of the review). The review ranks this as "do when touching the affected code" and it only matters once a second provider needs summaries. Not forgotten — deliberately out of scope for this plan.

## Technical Details

**New types**:

```python
# src/ccgram/window_view.py (new module)
@dataclass(frozen=True)
class WindowView:
    window_id: str
    cwd: str
    provider_name: str
    approval_mode: str
    notification_mode: str
    transcript_path: Path | None
```

**New accessors on `SessionManager`**:

```python
def view_window(self, window_id: str) -> WindowView | None:
    ws = window_store.window_states.get(window_id)
    if ws is None:
        return None
    return WindowView(
        window_id=window_id,
        cwd=ws.cwd or "",
        provider_name=ws.provider_name,
        approval_mode=ws.approval_mode,
        notification_mode=ws.notification_mode,
        transcript_path=Path(ws.transcript_path) if ws.transcript_path else None,
    )
```

**Polling strategy interface** (Phase 3):

Two distinct context shapes — per-binding strategies and periodic (bot-wide) strategies have different inputs and shouldn't share a type:

```python
# src/ccgram/handlers/polling_strategies.py

@dataclass(frozen=True)
class BindingTickContext:
    """Context for per-binding strategies — one call per (user, thread, window) per tick."""
    bot: Bot
    tick_time: float
    user_id: int
    thread_id: int
    window_id: str

@dataclass(frozen=True)
class PeriodicTickContext:
    """Context for bot-wide strategies — one call per tick, not per binding."""
    bot: Bot
    tick_time: float

class BindingStrategy(Protocol):
    async def tick(self, ctx: BindingTickContext) -> None: ...

class PeriodicStrategy(Protocol):
    async def tick(self, ctx: PeriodicTickContext) -> None: ...
```

**Strategy assignment**:

- `BindingStrategy`: `TerminalStatusStrategy`, `InteractiveUIStrategy`, `TopicLifecycleStrategy` (autoclose/TTL is per-binding), `ShellRelayStrategy` (check passive shell output per window)
- `PeriodicStrategy`: broker delivery cycle, mailbox sweep, live view tick, spawn request processing, transcript discovery sweep — everything currently in `run_periodic_tasks`

The coordinator's outer loop calls `PeriodicStrategy.tick(periodic_ctx)` once per iteration, then iterates bindings and calls `BindingStrategy.tick(binding_ctx)` for each registered binding strategy per binding.

**New extracted modules**:

- `src/ccgram/handlers/status_bubble.py` — status bubble rendering, `build_status_keyboard`
- `src/ccgram/handlers/shell_context.py` — `gather_llm_context`, `redact_for_llm`, `mark_telegram_command`, pending-command dict
- `src/ccgram/providers/shell_infra.py` — `match_prompt`, `setup_shell_prompt`, `detect_pane_shell`, `KNOWN_SHELLS`, `PromptMatch`
- `src/ccgram/window_view.py` — `WindowView` dataclass

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): all code/test changes live in ccgram's codebase
- **Post-Completion** (no checkboxes): update of `.claude/rules/architecture.md` module inventory, verification that `make test-e2e` passes (takes 3–4 min), optional mention in CHANGELOG

## Implementation Steps

### Phase 1 — Quick Wins

### Task 1: Move `UUID_RE` into `providers/base.py`

**Files:**

- Modify: `src/ccgram/providers/base.py`
- Modify: `src/ccgram/providers/claude.py`
- Modify: `src/ccgram/hook.py` (re-export for backward compat within-package callers)

- [ ] add `UUID_RE` regex constant to `providers/base.py` alongside `RESUME_ID_RE`
- [ ] update `providers/claude.py` to import `UUID_RE` from `.base` instead of `..hook`
- [ ] search for other `UUID_RE` imports across `src/ccgram/` via `rg "from .*hook import.*UUID_RE"` and redirect them to `.providers.base`
- [ ] if `hook.py` defines `UUID_RE`, re-export from `.providers.base` to avoid breaking external consumers
- [ ] run `make check` — must be green before next task

### Task 2: Move Telegram-specific constants out of `providers/base.py`

**Files:**

- Modify: `src/ccgram/providers/base.py`
- Modify: `src/ccgram/handlers/response_builder.py` (or wherever they end up used)
- Modify: callers of `EXPANDABLE_QUOTE_START`, `EXPANDABLE_QUOTE_END`, `format_expandable_quote`

- [ ] identify new home — recommend `src/ccgram/handlers/response_builder.py` since it already uses them; alternatively create `src/ccgram/telegram_formatting.py` if 3+ handlers need them
- [ ] grep for all imports: `rg "EXPANDABLE_QUOTE|format_expandable_quote" src/`
- [ ] move `EXPANDABLE_QUOTE_START`, `EXPANDABLE_QUOTE_END`, `format_expandable_quote()` to new home
- [ ] update all imports
- [ ] verify `providers/base.py` has zero Telegram references
- [ ] run `make check` — must be green before next task

### Task 3: Delete duplicated `session_map` logic from `session.py`

**Files:**

- Modify: `src/ccgram/session.py`

- [ ] locate the four duplicated methods in `session.py`: `load_session_map`, `register_hookless_session`, `write_hookless_session_map`, `prune_session_map`
- [ ] confirm each method in `session_map.py` (`session_map_sync` instance) is functionally equivalent by reading both implementations
- [ ] replace each `SessionManager` method body with a thin delegation: `return await session_map_sync.<method>(...)` or equivalent
- [ ] if any caller reaches `session_manager.load_session_map()` directly, keep the delegate — this preserves the public API
- [ ] run `make check` — must be green before next task
- [ ] run `make test-integration` specifically to catch any divergence

### Task 4: Fail-loud `_schedule_save` defaults

**Files:**

- Modify: `src/ccgram/window_state_store.py`
- Modify: `src/ccgram/thread_router.py`
- Modify: `src/ccgram/user_preferences.py`
- Modify: `src/ccgram/session_map.py`
- Modify: `src/ccgram/session.py` (for the wiring centralization)
- Create: `tests/ccgram/test_schedule_save_wiring.py`

- [ ] replace `_schedule_save = lambda: None` in all four singletons with `_schedule_save: Callable[[], None] | None = None`
- [ ] add property or method that raises `RuntimeError("SessionManager not initialized — wire _schedule_save before mutating")` on call if `None`
- [ ] centralize wiring in `session.py`: create a `_wire_singletons(self)` helper, call from `__post_init__`
- [ ] write test `test_schedule_save_raises_when_unwired` — instantiate a fresh `WindowStateStore` (not via SessionManager), call a mutation, expect `RuntimeError`
- [ ] write test `test_schedule_save_works_after_session_manager_init` — baseline test that `SessionManager()` wires correctly
- [ ] run `make check` — must be green before next task

### Phase 2 — Cohesion and Circular-Import Fixes

### Task 5: Move subagent label helpers from `hook_events` to `claude_task_state`

**Files:**

- Modify: `src/ccgram/claude_task_state.py`
- Modify: `src/ccgram/handlers/hook_events.py`
- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`

- [ ] move `build_subagent_label()` and `get_subagent_names()` from `handlers/hook_events.py` to `claude_task_state.py`
- [ ] move `_active_subagents: dict[str, dict[str, str]]` to `claude_task_state.py` (it's task-tracking state, not hook-event state)
- [ ] keep `@topic_state.register("window")` cleanup function (`clear_subagents`) alongside the moved state
- [ ] update `handlers/hook_events.py` to import from `claude_task_state` for its Subagent\* handlers
- [ ] update `handlers/message_queue.py` to import from `claude_task_state` instead of `hook_events`
- [ ] update `handlers/polling_coordinator.py` to import from `claude_task_state`
- [ ] verify `hook_events ↔ message_queue` circular import is gone (grep both files for cross-imports)
- [ ] run `make check` — must be green before next task

### Task 6: Extract `status_bubble.py` from `message_queue.py`

**Files:**

- Create: `src/ccgram/handlers/status_bubble.py`
- Create: `tests/ccgram/handlers/test_status_bubble.py`
- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`
- Modify: `src/ccgram/handlers/screenshot_callbacks.py`
- Modify: `src/ccgram/handlers/hook_events.py`

- [ ] identify status-bubble code in `message_queue.py`: `build_status_keyboard()`, status text rendering helpers, pinned message edit/send helpers
- [ ] create `src/ccgram/handlers/status_bubble.py` with module docstring explaining scope: "Status-bubble rendering — keyboard, text, pinned-message edit"
- [ ] move `build_status_keyboard()` and its helpers to `status_bubble.py`
- [ ] update all callers: `message_queue`, `polling_coordinator`, `screenshot_callbacks`, `hook_events`
- [ ] write unit tests for `build_status_keyboard()` covering: idle state, active state, with/without subagents, with/without custom status text
- [ ] verify `message_queue.py` is in the ~400–500 line range after both Task 5 (subagent helpers extracted) and Task 6 (status bubble extracted) complete — owning only queue primitives, batching, and tool-use pairing
- [ ] run `make check` — must be green before next task

### Task 7: Extract `shell_context.py` and break `shell_commands ↔ shell_capture` cycle

**Files:**

- Create: `src/ccgram/handlers/shell_context.py`
- Create: `tests/ccgram/handlers/test_shell_context.py`
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/shell_capture.py`

- [ ] identify shared shell functions: `gather_llm_context`, `redact_for_llm`, `mark_telegram_command`, plus any pending-command tracking dict
- [ ] create `shell_context.py` owning these functions and state
- [ ] remove them from `shell_commands.py` and `shell_capture.py`
- [ ] update `shell_commands.py` to import from `shell_context`
- [ ] update `shell_capture.py` to import from `shell_context`
- [ ] verify neither module imports the other (grep both for `from .shell_commands`, `from .shell_capture`)
- [ ] write unit tests for `redact_for_llm` (secret patterns, env var names, token formats)
- [ ] write unit tests for `gather_llm_context` (truncation, empty pane, non-shell pane)
- [ ] run `make check` — must be green before next task

### Task 8: Replace handler `provider_name ==` string checks with capability flags

**Files:**

- Modify: `src/ccgram/providers/base.py` (add capability flags as needed)
- Modify: `src/ccgram/providers/claude.py`, `codex.py`, `gemini.py`, `shell.py` (set new flags)
- Modify: `src/ccgram/handlers/transcript_discovery.py`
- Modify: `src/ccgram/handlers/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/window_callbacks.py`

- [ ] grep for string checks: `rg 'provider_name == "' src/ccgram/handlers/` and `rg '== "shell"' src/ccgram/handlers/` and `rg '== "claude"' src/ccgram/handlers/`
- [ ] for each hit, decide: is this capability-gated behavior (use `ProviderCapabilities`) or genuine provider identity (rare — keep as-is)?
- [ ] add new capability flags to `ProviderCapabilities` as needed (document each with a comment)
- [ ] set new flags on each concrete provider
- [ ] replace string checks with `get_provider_for_window(wid).capabilities.has_X` checks
- [ ] handle `None` return from `get_provider_for_window` — windows that aren't yet bound or have no session shouldn't crash; treat missing provider the same way the existing string-check paths do (most already `if not provider: return` early)
- [ ] run `make check` — must be green before next task

### Phase 3 — Structural Refactors

### Task 9: Introduce `WindowView` projection

**Files:**

- Create: `src/ccgram/window_view.py`
- Create: `tests/ccgram/test_window_view.py`
- Modify: `src/ccgram/session.py` (add `view_window` method)
- Modify: `src/ccgram/handlers/file_handler.py`
- Modify: `src/ccgram/handlers/history.py`
- Modify: `src/ccgram/handlers/text_handler.py`
- Modify: `src/ccgram/handlers/send_command.py`
- Modify: `src/ccgram/handlers/topic_emoji.py`

- [ ] create `src/ccgram/window_view.py` with `WindowView` frozen dataclass
- [ ] add `SessionManager.view_window(window_id) -> WindowView | None` method
- [ ] migrate `file_handler` — replace single-field read from `get_window_state` with `view_window`
- [ ] migrate `history` — replace `get_recent_messages`'s internal `get_window_state` with `view_window`
- [ ] migrate `text_handler` — replace `session_manager.get_window_state(wid).cwd` reads with `view_window`
- [ ] migrate `send_command` — replace cwd read with `view_window`
- [ ] migrate `topic_emoji` — replace `get_approval_mode` with `view_window(wid).approval_mode` (only if cleaner)
- [ ] write unit tests for `WindowView` construction and `view_window()` for present/absent windows
- [ ] leave `screenshot_callbacks` and `shell_commands` as-is if the remaining call is genuinely a mutation (`cycle_notification_mode`, cwd read next to send — judgment call)
- [ ] run `make check` — must be green before next task

### Task 10: Extract `providers/shell_infra.py`

**Files:**

- Create: `src/ccgram/providers/shell_infra.py`
- Modify: `src/ccgram/providers/shell.py` (slim to just `ShellProvider`)
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/shell_context.py` (from Task 7)
- Modify: `src/ccgram/handlers/shell_capture.py`
- Modify: `src/ccgram/handlers/transcript_discovery.py`
- Modify: `src/ccgram/handlers/window_callbacks.py`
- Modify: `src/ccgram/handlers/directory_callbacks.py`
- Modify: `src/ccgram/providers/process_detection.py` (imports `KNOWN_SHELLS` from `shell.py`)

- [ ] create `src/ccgram/providers/shell_infra.py` with module docstring: "Shell provider infrastructure — prompt detection, setup, shell inventory. Separated from `shell.py` which holds only `ShellProvider`."
- [ ] move from `shell.py` to `shell_infra.py`: `match_prompt`, `setup_shell_prompt`, `detect_pane_shell`, `KNOWN_SHELLS`, `PromptMatch`, `_wrap_setup_commands`, `_is_interactive_shell`, `has_prompt_marker`, `_get_prompt_mode`, `_get_marker_prefix`
- [ ] slim `shell.py` to `ShellProvider` class only (~50 lines)
- [ ] update all imports — handlers should import from `providers.shell_infra`, registry still imports `ShellProvider` from `shell`
- [ ] update `process_detection.py` to import `KNOWN_SHELLS` from `shell_infra`
- [ ] run `make check` — must be green before next task

### Task 11: Invert `polling_coordinator` to strategy-owned `tick()` methods

⚠️ **Deferred during execution.** After reading the actual code: `polling_coordinator.py` is 598 lines but `status_poll_loop` itself is ~85 lines — the body is already decomposed into well-named helpers (`update_status_message`, `_scan_window_panes`, `_maybe_check_passive_shell`, `_check_interactive_only`, `discover_and_register_transcript`, `_handle_dead_window_notification`). The "god loop" framing in the review was based on file size, not orchestration tangle. Inverting to `strategy.tick()` would mostly rename functions to methods while introducing risk to a load-bearing 1s loop where ordering matters and short-circuits exist. Per the "no overengineering" constraint, deferred until a future task introduces a new polling concern that demonstrably needs self-registering strategies.

**Files:**

- Modify: `src/ccgram/handlers/polling_strategies.py` (add `tick()` methods and `TickContext`)
- Modify: `src/ccgram/handlers/polling_coordinator.py` (shrink to dispatcher)
- Modify: `src/ccgram/handlers/periodic_tasks.py` (merge into strategies where appropriate)
- Create: `tests/ccgram/handlers/test_poll_tick.py`

- [ ] define `BindingTickContext` and `PeriodicTickContext` dataclasses in `polling_strategies.py` (see Technical Details section for shape)
- [ ] define `BindingStrategy` and `PeriodicStrategy` protocols
- [ ] add `async def tick(self, ctx: BindingTickContext)` to `TerminalStatusStrategy` — contains the current per-binding terminal scan logic
- [ ] add `async def tick(self, ctx: BindingTickContext)` to `InteractiveUIStrategy` — contains pane scanning
- [ ] add `async def tick(self, ctx: BindingTickContext)` to `TopicLifecycleStrategy` — contains autoclose/TTL (currently in `periodic_tasks.run_lifecycle_tasks`)
- [ ] create `PeriodicStrategy` implementations (or convert existing module-level functions) for: broker delivery, mailbox sweep, live view tick, spawn processing, transcript discovery sweep — one class or one function-wrapping instance per concern
- [ ] refactor `status_poll_loop` to: (a) build `periodic_ctx`, call every registered `PeriodicStrategy.tick(periodic_ctx)`, (b) loop through thread bindings, build `binding_ctx`, call every registered `BindingStrategy.tick(binding_ctx)`
- [ ] move body of `run_periodic_tasks` and `run_lifecycle_tasks` into the appropriate strategy `tick()` methods; `periodic_tasks.py` shrinks to strategy instances + registration (or can be deleted if strategies live in `polling_strategies.py`)
- [ ] verify `polling_coordinator.py` shrinks to ~150 lines
- [ ] write unit test `test_terminal_tick_skips_when_window_missing` — strategy returns early without error when `find_window_by_id` returns None
- [ ] write unit test `test_lifecycle_tick_closes_expired_topic` — feed a mock strategy with an expired autoclose timer, verify the close path fires
- [ ] run `make check` — must be green before next task
- [ ] run `make test-e2e` as a sanity check — polling is load-bearing for live agent interaction

### Task 12: Verify acceptance criteria

- [ ] re-read `docs/modularity-review/2026-04-12/modularity-review-evening.md`
- [ ] verify every issue in the "Priority Ranking" section maps to a completed task
- [ ] verify `providers/base.py` contains no Telegram references (grep)
- [ ] verify no handler file imports `hook.UUID_RE` (grep)
- [ ] verify `session.py` has no duplicate `load_session_map` / `register_hookless_session` / `write_hookless_session_map` / `prune_session_map` method bodies
- [ ] verify no `provider_name ==` string checks remain in `src/ccgram/handlers/` (grep)
- [ ] verify `hook_events.py` and `message_queue.py` have no mutual imports (grep both files)
- [ ] verify `shell_commands.py` and `shell_capture.py` have no mutual imports (grep both files)
- [ ] verify `message_queue.py` is noticeably shorter (expect ~800 lines vs prior 1184)
- [ ] verify `polling_coordinator.py` is noticeably shorter (expect ~150 lines vs prior 598)
- [ ] run full test suite: `make check`
- [ ] run e2e tests: `make test-e2e`

### Task 13: Update documentation

- [ ] update `.claude/rules/architecture.md` module inventory with new modules (`status_bubble`, `shell_context`, `shell_infra`, `window_view`)
- [ ] update `CLAUDE.md` if any new patterns emerged that future maintainers need to know (e.g., "prefer `view_window` over `get_window_state` for read-only access")
- [ ] add an entry to `docs/modularity-review/2026-04-12/` referencing this plan as the completion artifact
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification** (if applicable):

- Run the bot against a real Telegram group and exercise: new topic creation, interactive UI responses, live view, shell commands, inter-agent messaging. These paths are load-bearing and exercised by handlers that moved in this plan.
- Verify state.json and session_map.json round-trip cleanly after a bot restart mid-refactor.

**External system updates** (if applicable):

- None — this is internal refactoring with no API surface changes.
- Optional: mention in CHANGELOG if a public version is cut before the next feature.
