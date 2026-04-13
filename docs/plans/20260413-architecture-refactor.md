# Architecture Refactor — Modularity Review Round 2

## Overview

Execute the target architecture from `docs/design/2026-04-13/architecture.md`. This is the follow-up refactor after the April 12 modularity review round 1: that round shipped quick wins (UUID_RE, session_map dedup, shell_infra, shell_context, window_view, toolbar_callbacks extraction, fail-loud save wiring) but left six Significant issues — exacerbated in one case by the `/send` + toolbar + tool-batching feature bundle that landed in the same commit.

The six refactor targets (confirmed by the maintainer as active pain points):

1. **Message Delivery** — `message_queue.py` is still 1132 lines holding queue primitives + Claude tool batching + batch formatting + status bubble I/O. Split into four cohesive files.
2. **Shell Prompt Setup** — the `ensure_setup` decision is duplicated across 5 handlers with implicit ordering. Consolidate behind one orchestrator.
3. **Polling Strategies** — `TerminalStatusStrategy` (270 lines / 31 methods / 3 state machines) plus 20+ compat wrappers at the bottom of `polling_strategies.py` because `@topic_state.register` can't bind methods. Split the class and extend the registry.
4. **Toolbar** — mixes TOML config loading + key dispatch + intrusive Claude pane scraping. Move scraping to `AgentProvider.scrape_current_mode`; split the keyboard builder from the callback dispatcher.
5. **Screenshot Callbacks** — still 764 lines with 4 concerns. Extract `status_bar_actions.py` to finish the partial extraction from Apr 12.
6. **WindowView Adoption + Residual Leaks** — handler calls to `session_manager` grew from 62 → 77; three refactor residues remain (`provider_name == "claude"` check, `thread_router.window_display_names` direct access, `send_command._upload_file` private import).

**No Critical or Significant coupling issues expected in the post-refactor state.** Every change is incremental, reversible, and merge-independent — no flag days.

## Context (from discovery)

**Primary source**: `docs/design/2026-04-13/architecture.md` (target module map, coupling assessment, design decisions, implementation sequencing).

**Module design docs** under `docs/design/2026-04-13/`:

- [`message-delivery/`](../design/2026-04-13/message-delivery/design.md) — 4-file split
- [`shell-provider-ux/`](../design/2026-04-13/shell-provider-ux/design.md) — orchestrator
- [`polling-and-events/`](../design/2026-04-13/polling-and-events/design.md) — registry + class split
- [`toolbar/`](../design/2026-04-13/toolbar/design.md) — 3-way split
- [`provider-layer/`](../design/2026-04-13/provider-layer/design.md) — `scrape_current_mode` capability
- [`screenshot-and-live-view/`](../design/2026-04-13/screenshot-and-live-view/design.md) — `status_bar_actions` extraction
- [`session-and-state/`](../design/2026-04-13/session-and-state/design.md) — `WindowView` migration
- [`directory-browser/`](../design/2026-04-13/directory-browser/design.md) — capability flag
- [`send-command/`](../design/2026-04-13/send-command/design.md) — `_upload_file` rename

**Modularity review source**: `docs/modularity-review/2026-04-13/modularity-review.md` (9 issues, 5 Significant).

**Files involved (by refactor target)**:

- Message delivery: `src/ccgram/handlers/message_queue.py` (split), `src/ccgram/handlers/status_bubble.py` (expand), `src/ccgram/handlers/message_routing.py` (no changes), `src/ccgram/handlers/tool_batch.py` (NEW)
- Shell orchestrator: `src/ccgram/handlers/shell_prompt_orchestrator.py` (NEW), `src/ccgram/handlers/directory_callbacks.py`, `src/ccgram/handlers/window_callbacks.py`, `src/ccgram/handlers/transcript_discovery.py`, `src/ccgram/handlers/shell_commands.py`, `src/ccgram/providers/shell_infra.py`
- Polling registry + class split: `src/ccgram/handlers/topic_state_registry.py`, `src/ccgram/handlers/polling_strategies.py`, `src/ccgram/handlers/polling_coordinator.py`
- Toolbar + provider capability: `src/ccgram/providers/base.py`, `src/ccgram/providers/claude.py`, `src/ccgram/handlers/toolbar_keyboard.py` (NEW), `src/ccgram/handlers/toolbar_callbacks.py`
- Status bar extraction: `src/ccgram/handlers/status_bar_actions.py` (NEW), `src/ccgram/handlers/screenshot_callbacks.py`
- WindowView migration: `src/ccgram/handlers/file_handler.py`, `src/ccgram/handlers/history.py`, `src/ccgram/handlers/shell_commands.py`, `src/ccgram/handlers/text_handler.py`, `src/ccgram/handlers/send_command.py`, `src/ccgram/handlers/topic_emoji.py`
- Residual fixes: `src/ccgram/session.py`, `src/ccgram/handlers/directory_callbacks.py`, `src/ccgram/handlers/send_callbacks.py`, `src/ccgram/handlers/send_command.py`

**Related patterns found**:

- `@topic_state.register(scope)` decorator — needs `register_bound(scope, method)` extension for instance methods.
- `ProviderCapabilities` dataclass — extend with new capability flags.
- Debounced persistence via `_schedule_save` / `unwired_save()` fail-loud default — preserved unchanged.
- `WindowView` frozen dataclass — exists; adoption is the work.
- Topic state cleanup registry — existing, used from many handlers.

**Dependencies identified**:

- `python-telegram-bot` (PTB) handler registration — unchanged.
- `pytest` + `asyncio_mode = "auto"` — unchanged.
- `make check` = fmt + lint + typecheck + test + integration — must stay green throughout.
- Existing test files mirror the source layout; moves invalidate mock patch paths and must be updated in the same task.
- `tests/integration/test_message_dispatch.py` — base pattern for integration tests via PTB `Application + _do_post` patch.

## Development Approach

- **Testing approach**: Regular (code first, then tests in the same task). Existing test suite is rich enough that pure moves rely on it; new code (orchestrator, `tool_batch.format_batch_message`, `register_bound`) gets new unit tests.
- Complete each task fully before moving to the next.
- Make small, focused changes — each task is one logical refactor.
- **CRITICAL**: every task ends with `make check` green. No exceptions.
- **CRITICAL**: each task writes/updates tests for all code touched in that task.
  - New modules: new test files covering unit + integration contracts + boundaries.
  - Moved code: update existing test imports and mock patch paths.
  - Handler migrations: update tests to use `WindowView` fixtures where the handler now reads via `view_window`.
  - All four test categories (unit, contract, boundary, behaviour) from the module's `tests.md` are in scope — but don't front-load; write what's relevant to the code changed in this task.
- Run `make check` after each task. If red, fix before proceeding.
- **CRITICAL**: update this plan file when scope changes during implementation.
- Maintain backward compatibility of external interfaces (state.json, session_map.json, events.jsonl, mailbox/, ~/.claude/settings.json hook entries).

## Testing Strategy

- **Unit tests**: required for every task. Target the module design doc's `tests.md` as the spec — each task implements a slice of that spec.
- **Integration tests**: `tests/integration/*` must stay green. Patch targets may need updating when code moves between files.
- **E2E tests**: `tests/e2e/*` takes 3–4 minutes against real agent CLIs. Run at the end of each Phase (1, 2, 3, 4) as a sanity check, not per-task.
- **Per-task verification gate**: `make check` green. If red, fix before proceeding.
- **Coverage check** at Phase end: `uv run --extra test python -m pytest tests/ccgram/handlers/ --cov=src/ccgram/handlers -v` (or project-standard command).

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.

## Solution Overview

**Phased approach**, ordered by payoff-to-cost ratio and merge independence:

- **Phase 1 — Message Delivery split** (highest payoff, addresses the #1 user-flagged pain). Extract `tool_batch.py`, expand `status_bubble.py` with status send/clear, slim `message_queue.py`. Three tasks, one merge.
- **Phase 2 — Polling registry + class split**. Extend `topic_state_registry` with `register_bound`; delete 20+ compat wrappers; split `TerminalStatusStrategy` into `TerminalScreenBuffer` + `TerminalPollState`. Two tasks, one merge.
- **Phase 3 — Shell prompt orchestrator**. Create orchestrator; migrate 5 trigger sites. Two tasks, one merge.
- **Phase 4 — Toolbar + provider capability**. Add `scrape_current_mode` to provider protocol; implement on Claude; extract `toolbar_keyboard.py`; slim `toolbar_callbacks.py`. Three tasks, one merge.
- **Phase 5 — Opportunistic cleanup**. Extract `status_bar_actions.py`; migrate 7 handlers to `WindowView`; fix 3 residual leaks. Four tasks, one merge.

**Key design decisions** (from `architecture.md`):

1. **Don't split `SessionManager`** — god-object tolerable at solo-dev distance; `WindowView` fixes the cascade pain.
2. **Don't invert `polling_coordinator` to strategy-owned `tick()`** — deferred correctly by the Apr 12 plan; the real friction is in the strategy layer, not the loop.
3. **Don't extract summariser to provider layer** — user confirmed no new provider planned; volatility neutralises the imbalance.
4. **Don't introduce DI / `WindowContext` aggregation** — multi-week refactors dominated by the 6 targets above.

## Technical Details

### New modules

- **`src/ccgram/handlers/tool_batch.py`** (~350 lines) — Claude tool-use batching state machine, formatting, cleanup. Public API:

  ```python
  async def process_tool_event(bot: Bot, user_id: int, task: MessageTask) -> None
  async def flush_batch(bot: Bot, user_id: int, thread_id: int) -> None
  def is_batch_eligible(task: MessageTask, window_id: str) -> bool
  def format_batch_message(entries: list[ToolBatchEntry], subagent_label: str | None = None) -> str
  ```

  Moved from `message_queue.py`: `ToolBatchEntry`, `ToolBatch`, `_active_batches`, `_process_batch_task`, `_flush_batch`, `_is_batch_eligible`, `_should_batch`, `BATCH_MAX_ENTRIES`, `BATCH_MAX_LENGTH`, `_TASK_TOOL_NAMES`, and all 10 `_format_*` helpers.

- **`src/ccgram/handlers/shell_prompt_orchestrator.py`** (~120 lines) — single entry point for prompt-marker setup decisions. Public API:

  ```python
  Trigger = Literal["auto", "external_bind", "provider_switch", "lazy"]

  async def ensure_setup(window_id: str, trigger: Trigger) -> None
  async def accept_offer(window_id: str) -> None
  def record_skip(window_id: str) -> None
  def clear_state(window_id: str) -> None  # @topic_state.register_bound("window")
  ```

- **`src/ccgram/handlers/toolbar_keyboard.py`** (~200 lines) — keyboard rendering + per-window label state. Public API:

  ```python
  def build_toolbar_keyboard(window_id: str, provider_name: str = "claude") -> InlineKeyboardMarkup
  async def seed_button_states(window_id: str) -> None
  def reload_toolbar_config() -> None
  def _set_action_label(window_id: str, action_name: str, label: str) -> None
  def _get_action_label(window_id: str, action_name: str) -> str | None
  ```

  Moved from `toolbar_callbacks.py`.

- **`src/ccgram/handlers/status_bar_actions.py`** (~200 lines) — status-bubble button callbacks. Public API via `@register` decorators for `CB_STATUS_NOTIFY`, `CB_STATUS_RECALL`, `CB_STATUS_REMOTE`, `CB_STATUS_ESC`, `CB_STATUS_KEY`. Moved from `screenshot_callbacks.py`.

### Modified modules

- **`src/ccgram/handlers/topic_state_registry.py`** — add `register_bound(scope, method)` that accepts a bound instance method and stores it for `fire(scope, id)` dispatch.

- **`src/ccgram/handlers/polling_strategies.py`** — split `TerminalStatusStrategy` (270 lines / 31 methods) into `TerminalScreenBuffer` (pyte, screen buffer pool, pane count cache, rendered text cache) and `TerminalPollState` (RC debounce, probe failures, startup grace, unbound timers, seen-status, recent-activity). Delete all 20+ module-level wrapper functions (L566-652). Strategies' `__init__` calls `topic_state.register_bound("window", self.method)` directly.

- **`src/ccgram/handlers/message_queue.py`** — slim to ~500 lines of queue primitives: `MessageTask`, `_message_queue_worker`, `_process_content_task`, `_merge_content_tasks`, `_coalesce_status_updates`, `_can_merge_tasks`, `enqueue_content_message`, `enqueue_status_update`, `get_or_create_queue`, `shutdown_workers`. The worker dispatches content tasks to `tool_batch.process_tool_event` (branch) or its internal `_process_content_task`.

- **`src/ccgram/handlers/status_bubble.py`** — grows from 81 to ~300 lines. Absorbs from `message_queue.py`: `_process_status_update_task`, `_process_status_clear_task`, `_do_send_status_message`, `_do_clear_status_message`, `_convert_status_to_content`, `_format_claude_task_status`, `_status_msg_info`. Public API: `send_status_text`, `clear_status_text`, `edit_status_in_place`, `build_status_keyboard` (already here), `clear_status_msg_info`.

- **`src/ccgram/providers/base.py`** — add `scrape_current_mode(window_id: str) -> str | None` to the `AgentProvider` protocol with a default `return None`. Add `has_yolo_confirmation: bool = False` to `ProviderCapabilities`.

- **`src/ccgram/providers/claude.py`** — implement `scrape_current_mode` with the regexes moved from `toolbar_callbacks.py`. Set `has_yolo_confirmation = True` in `ClaudeProvider.capabilities`.

- **`src/ccgram/handlers/toolbar_callbacks.py`** — slim to ~300 lines of dispatch only. Remove `_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`, `build_toolbar_keyboard` (moved to `toolbar_keyboard.py`), `_window_action_labels` (moved). `_refresh_button_label` becomes: `provider = get_provider_for_window(window_id); label = await provider.scrape_current_mode(window_id) or action.default_label; toolbar_keyboard._set_action_label(...)`.

- **`src/ccgram/handlers/screenshot_callbacks.py`** — slim to ~350 lines. Keep screenshot capture, panes command, live view, `build_screenshot_keyboard`. Move status-bar actions to `status_bar_actions.py`.

### Minor cleanups

- **`src/ccgram/session.py` L412, L414, L495** — replace `thread_router.window_display_names[wid]` direct access with `thread_router.get_display_name(wid)` / `pop_display_name(wid)`.
- **`src/ccgram/handlers/directory_callbacks.py` L593** — replace `provider_name == "claude"` with `provider.capabilities.has_yolo_confirmation`.
- **`src/ccgram/handlers/send_command.py`** — promote `_upload_file` → `upload_file` (public name). Update `send_callbacks.py` import.

### WindowView migration targets

Migrate these read-only handlers from `session_manager.get_window_state(wid).{field}` to `session_manager.view_window(wid).{field}`:

- `handlers/file_handler.py` — reads `cwd`
- `handlers/history.py` — reads `transcript_path`
- `handlers/shell_commands.py` — reads `cwd`
- `handlers/text_handler.py` — reads `cwd`
- `handlers/send_command.py` — reads `cwd`
- `handlers/topic_emoji.py` — reads `approval_mode`

Skip `screenshot_callbacks.py` (mutates via `cycle_notification_mode`).

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes) — code changes, tests, patch updates, documentation updates tracked in this plan.
- **Post-Completion** (no checkboxes) — e2e smoke against a real Telegram group, CHANGELOG entry if a public version is cut, architecture.md update if scope deviates.

## Implementation Steps

### Phase 1 — Message Delivery Split

### Task 1: Extract `handlers/tool_batch.py`

**Files:**

- Create: `src/ccgram/handlers/tool_batch.py`
- Modify: `src/ccgram/handlers/message_queue.py`
- Create: `tests/ccgram/handlers/test_tool_batch.py`
- Modify: `tests/ccgram/handlers/test_message_queue.py` (update imports)

- [ ] create `src/ccgram/handlers/tool_batch.py` with module docstring: "Claude tool-use batching — state machine, formatting, edit-in-place delivery"
- [ ] move to `tool_batch.py`: `BATCH_MAX_ENTRIES`, `BATCH_MAX_LENGTH`, `_TASK_TOOL_NAMES`, `ToolBatchEntry`, `ToolBatch`, `_active_batches`, `_is_batch_eligible`, `_should_batch`, `_process_batch_task` → renamed `process_tool_event`, `_flush_batch` → renamed `flush_batch`, `format_batch_message`, `_format_task_create_batch`, `_format_mixed_batch_lines`, `_format_task_create_section`, `_format_task_update_section`, `_format_task_list_section`, `_batch_result_prefix`, `_format_batch_entry`, `_extract_task_create_title`, `_extract_task_tool_suffix`
- [ ] add public `is_batch_eligible(task, window_id) -> bool` wrapper combining `_is_batch_eligible(task) and _should_batch(window_id)`
- [ ] register `@topic_state.register("topic")` cleanup on the `_active_batches` (moved from message_queue)
- [ ] update `message_queue._handle_content_task` to branch via `if tool_batch.is_batch_eligible(task, window_id): await tool_batch.process_tool_event(bot, user_id, task)` instead of inline check
- [ ] update `message_queue.py` imports to reference `tool_batch` for the branch function; remove moved symbols
- [ ] write unit tests in `test_tool_batch.py` covering: `format_batch_message` for single/multiple/task-tool batches, `_extract_task_create_title` markdown and plain variants, `is_batch_eligible` predicate, `_batch_result_prefix` ok/error, `ToolBatchEntry` + `ToolBatch` dataclass construction
- [ ] write integration test: enqueue tool_use + tool_result, verify batch message is sent then edited
- [ ] update `test_message_queue.py` imports (functions now live in `tool_batch`)
- [ ] run `make check` — must be green before Task 2

### Task 2: Expand `handlers/status_bubble.py` with status I/O

**Files:**

- Modify: `src/ccgram/handlers/status_bubble.py`
- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py` (if it imports status helpers)
- Modify: `src/ccgram/handlers/hook_events.py` (if it imports status helpers)
- Modify: `src/ccgram/handlers/tool_batch.py` (imports `status_bubble.clear_status_text`)
- Create: `tests/ccgram/handlers/test_status_bubble.py` (or expand existing)

- [ ] move from `message_queue.py` to `status_bubble.py`: `_process_status_update_task`, `_process_status_clear_task`, `_do_send_status_message`, `_do_clear_status_message`, `_convert_status_to_content`, `_format_claude_task_status`, `_status_msg_info` dict, `clear_status_msg_info`
- [ ] rename: `_do_send_status_message` → `send_status_text` (public), `_do_clear_status_message` → `clear_status_text` (public)
- [ ] add `@topic_state.register("topic")` cleanup for `_status_msg_info` inside `status_bubble.py`
- [ ] update `tool_batch.process_tool_event` to import `from .status_bubble import clear_status_text` and call `await clear_status_text(bot, user_id, thread_id)` before sending a new batch message
- [ ] update `message_queue._message_queue_worker` dispatch: status_update task → `status_bubble.send_status_text(...)`, status_clear task → `status_bubble.clear_status_text(...)`
- [ ] update all callers of `clear_status_msg_info` — most will stay as-is via re-export or direct import of `status_bubble.clear_status_msg_info`
- [ ] write unit tests for `send_status_text` (new send path, edit-in-place path, dedup on identical content), `clear_status_text`, `_format_claude_task_status` (no tasks / with wait header / with task list)
- [ ] update `test_message_queue.py` — status tests move to `test_status_bubble.py`
- [ ] run `make check` — must be green before Task 3

### Task 3: Slim `handlers/message_queue.py` to queue primitives

**Files:**

- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `tests/ccgram/handlers/test_message_queue.py` (trim + refocus on queue primitives)

- [ ] verify `message_queue.py` contains only: `MessageTask` (unchanged discriminated dataclass), `_message_queue_queues`, `_queue_workers`, `_queue_locks` dicts, `get_message_queue`, `get_or_create_queue`, `_inspect_queue`, `_can_merge_tasks`, `_merge_content_tasks`, `_coalesce_status_updates`, `_handle_content_task` (now a thin router), `_message_queue_worker`, `_process_content_task` (for non-batch content), `_is_ghost_window_task_at_enqueue`, `_get_idle_history`, `_send_kwargs`, `enqueue_content_message`, `enqueue_status_update`, `clear_batch_for_topic` → delegates to `tool_batch.clear_batch_for_topic`, `clear_tool_msg_ids_for_topic`, `shutdown_workers`
- [ ] delete: dataclasses, batch helpers, status handlers, Claude task formatting — anything moved in Task 1 or Task 2
- [ ] verify file is in the 450–550 line range (from 1132)
- [ ] update `test_message_queue.py` — keep tests for FIFO, merging, rate-limit coalescing, worker startup/shutdown; remove batch-specific and status-specific tests (they moved to `test_tool_batch.py` / `test_status_bubble.py`)
- [ ] add `test_enqueue_creates_worker`, `test_enqueue_reuses_worker`, `test_merge_consecutive_text_tasks`, `test_merge_stops_on_tool_use`, `test_merge_stops_at_3800_chars`, `test_status_update_coalesces` (if not already present)
- [ ] run `make check` — must be green
- [ ] run `make test-e2e` — Phase 1 sanity check (message delivery is load-bearing for every agent interaction)

### Phase 2 — Polling Registry and Strategy Split

### Task 4: Extend `topic_state_registry` to accept bound methods; delete compat wrappers

**Files:**

- Modify: `src/ccgram/handlers/topic_state_registry.py`
- Modify: `src/ccgram/handlers/polling_strategies.py` (delete L566-652 wrappers, add `register_bound` calls in strategy constructors)
- Modify: `src/ccgram/handlers/polling_coordinator.py` (update imports if any wrappers were imported)
- Modify: `src/ccgram/handlers/cleanup.py` (if it imports any of the deleted wrappers)
- Modify callers of the deleted free functions: grep `rg "from \.polling_strategies import " src/ccgram/` and update each import to use the strategy instance method
- Create: `tests/ccgram/handlers/test_topic_state_registry.py` (or expand existing)

- [ ] add `register_bound(scope: Scope, method: MethodType) -> None` to `TopicStateRegistry` — store as callable in the same scope registry that `register` populates
- [ ] update `fire(scope, ...)` to call all callables in the scope's registry (bound methods already carry `self`)
- [ ] in `TerminalStatusStrategy.__init__` (soon to be split — see Task 5), in `InteractiveUIStrategy.__init__`, in `TopicLifecycleStrategy.__init__`: call `topic_state.register_bound("window", self.clear_state)` etc. for every cleanup-relevant method
- [ ] delete the 20+ module-level wrappers at L566-L652 of `polling_strategies.py`: `clear_window_poll_state`, `clear_screen_buffer`, `reset_screen_buffer_state`, `is_rc_active`, `clear_topic_poll_state`, `clear_autoclose_timer`, `reset_autoclose_state`, `clear_dead_notification`, `reset_dead_notification_state`, `clear_probe_failures`, `reset_probe_failures_state`, `clear_typing_state`, `clear_seen_status`, `reset_seen_status_state`, `reset_typing_state`, `has_pane_alert`, `clear_pane_alerts` — including their `@topic_state.register` decorators
- [ ] grep `rg "from \.polling_strategies import (clear_|reset_|is_rc|has_pane)" src/ccgram/` and update each caller to use the strategy instance method (`terminal_strategy.clear_state(wid)`, etc.)
- [ ] write `test_register_bound_window_scope` — instantiate a fake class with a cleanup method, register via `register_bound`, call `fire`, verify the method is called with the correct self
- [ ] write `test_register_bound_topic_scope` — same for topic scope with `(user_id, thread_id)` signature
- [ ] write `test_failing_callback_does_not_block_others` — verify one raising callback doesn't prevent the others in the same scope from running
- [ ] run `make check` — must be green before Task 5

### Task 5: Split `TerminalStatusStrategy` into `TerminalScreenBuffer` + `TerminalPollState`

**Files:**

- Modify: `src/ccgram/handlers/polling_strategies.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py` (update references from `terminal_strategy` to `terminal_screen_buffer` + `terminal_poll_state`)
- Modify: other callers — grep `rg "terminal_strategy\." src/ccgram/` and route each call to the new owner
- Modify: `tests/ccgram/handlers/test_polling_strategies.py` — split into two test classes

- [ ] create `TerminalScreenBuffer` class in `polling_strategies.py` owning: `clear_screen_buffer`, `reset_screen_buffer_state`, `get_screen_buffer`, `parse_with_pyte`, `update_pane_count_cache`, `is_single_pane_cached` — all the pyte / screen buffer / pane count concerns
- [ ] create `TerminalPollState` class in `polling_strategies.py` owning: `get_state`, `clear_state`, `clear_unbound_timers`, `get_expired_unbound`, `get_orphaned_window_ids`, `is_rc_active`, `update_rc_state`, `reset_probe_failures`, `clear_seen_status`, `set_unbound_timer`, `clear_unbound_timer`, `reset_all_probe_failures`, `reset_all_seen_status`, `reset_all_unbound_timers`, `cancel_startup_timer`, `begin_startup_timer`, `check_seen_status`, `get_rendered_text`, `is_recently_active`, `is_startup_expired`, `mark_seen_status` — RC debounce + probe failures + startup grace + activity tracking
- [ ] expose `terminal_screen_buffer` and `terminal_poll_state` module-level singletons; add `@topic_state.register_bound("window", self.clear_screen_buffer)` calls in `TerminalScreenBuffer.__init__`, similar for `TerminalPollState.clear_state` etc.
- [ ] delete the old `TerminalStatusStrategy` class
- [ ] route callers: `polling_coordinator._parse_with_pyte` → `terminal_screen_buffer.parse_with_pyte`; `_handle_no_status` and friends → `terminal_poll_state.*`; `InteractiveUIStrategy.__init__(self, terminal_screen_buffer)` if pane alerts need the screen buffer
- [ ] update `TopicLifecycleStrategy.__init__(self, terminal_poll_state)` if it still needs RC state
- [ ] verify with `rg "TerminalStatusStrategy" src/ccgram/` — zero matches expected
- [ ] add unit tests for `TerminalScreenBuffer` (pyte parsing, cache TTL) and `TerminalPollState` (RC debounce, probe failure counter, startup grace, unbound timer expiry, recent activity)
- [ ] run `make check` — must be green

### Phase 3 — Shell Prompt Orchestrator

### Task 6: Create `handlers/shell_prompt_orchestrator.py`

**Files:**

- Create: `src/ccgram/handlers/shell_prompt_orchestrator.py`
- Create: `tests/ccgram/handlers/test_shell_prompt_orchestrator.py`

- [ ] create the module with the `Trigger` enum (`Literal["auto", "external_bind", "provider_switch", "lazy"]`), `_WindowOrchestratorState` dataclass, `_state: dict[str, _WindowOrchestratorState]` private dict
- [ ] implement `async def ensure_setup(window_id: str, trigger: Trigger) -> None` with the decision table:
  - `auto` → always call `setup_shell_prompt(clear=True)`
  - `lazy` → call only if `not state.skip_flag and not await has_prompt_marker(window_id)`, with `clear=False`
  - `external_bind` → show offer keyboard if marker missing and not already offered; no-op otherwise
  - `provider_switch` → show offer keyboard if not `state.skip_flag`; reoffer is OK if skip was cleared
- [ ] implement `async def accept_offer(window_id: str) -> None` — sets `was_offered=True`, calls `setup_shell_prompt(clear=False)`
- [ ] implement `def record_skip(window_id: str) -> None` — sets `state.skip_flag=True`, session-scoped
- [ ] implement `def clear_state(window_id: str) -> None` and register via `@topic_state.register_bound("window", ...)` inside an init hook or at module load
- [ ] write table-driven unit tests matching the design doc's 10 scenarios (auto_always_runs, lazy_no_op_when_marker_present, lazy_runs_when_marker_missing, lazy_respects_skip_flag, external_bind_shows_offer, external_bind_no_offer_if_marker_present, provider_switch_reoffers_after_skip_cleared, provider_switch_respects_skip, accept_offer_runs_setup, record_skip_sets_flag)
- [ ] mock `has_prompt_marker` and `setup_shell_prompt` in tests — orchestrator is pure policy
- [ ] run `make check` — must be green before Task 7

### Task 7: Migrate 5 shell setup trigger sites

**Files:**

- Modify: `src/ccgram/handlers/directory_callbacks.py` (`_create_window_and_bind` flow)
- Modify: `src/ccgram/handlers/window_callbacks.py` (external window bind handler)
- Modify: `src/ccgram/handlers/transcript_discovery.py` (provider switch detection)
- Modify: `src/ccgram/handlers/shell_commands.py` (`_ensure_prompt_marker` pre-send hook)
- Modify: `src/ccgram/handlers/shell_capture.py` (verify no orphan trigger — remove if present)

- [ ] in `directory_callbacks._create_window_and_bind`, replace the current call to `setup_shell_prompt(wid)` with `await shell_prompt_orchestrator.ensure_setup(wid, "auto")`
- [ ] in `window_callbacks._handle_bind` (or equivalent), replace the current offer-keyboard trigger with `await shell_prompt_orchestrator.ensure_setup(wid, "external_bind")` — the orchestrator internally shows the offer keyboard via a helper
- [ ] in `transcript_discovery.discover_and_register_transcript` (on shell transition), replace with `await shell_prompt_orchestrator.ensure_setup(wid, "provider_switch")`
- [ ] in `shell_commands._ensure_prompt_marker`, replace body with `await shell_prompt_orchestrator.ensure_setup(wid, "lazy")`
- [ ] grep `rg "setup_shell_prompt\(" src/ccgram/handlers/` — only `shell_prompt_orchestrator.py` should have calls, everything else goes through `ensure_setup`
- [ ] factor the offer-keyboard rendering (inline keyboard with Set up / Skip) into `shell_prompt_orchestrator._show_offer_keyboard(window_id)` — called from the `external_bind` and `provider_switch` branches
- [ ] wire the "Set up" / "Skip" callbacks to `shell_prompt_orchestrator.accept_offer` / `record_skip` via the existing `handlers/shell_prompt_callbacks.py` (or add a small new callback dispatcher in this file)
- [ ] update tests in `test_directory_callbacks`, `test_window_callbacks`, `test_transcript_discovery`, `test_shell_commands` — mock `shell_prompt_orchestrator.ensure_setup` and assert correct trigger name
- [ ] write integration test: fake `has_prompt_marker=False`, call each trigger, verify expected `setup_shell_prompt` invocation pattern
- [ ] run `make check` — must be green
- [ ] run `make test-e2e` — Phase 3 sanity check (shell provider UX is e2e-tested)

### Phase 4 — Toolbar + Provider Capability

### Task 8: Add `scrape_current_mode` + `has_yolo_confirmation` to provider protocol

**Files:**

- Modify: `src/ccgram/providers/base.py`
- Modify: `src/ccgram/providers/claude.py`
- Modify: `src/ccgram/providers/codex.py`, `gemini.py`, `shell.py` (inherit the default)
- Modify: `tests/ccgram/providers/test_claude.py`, `test_shell.py`, etc.

- [ ] add `has_yolo_confirmation: bool = False` to `ProviderCapabilities` in `providers/base.py`
- [ ] add `async def scrape_current_mode(self, window_id: str) -> str | None: return None` method to the `AgentProvider` protocol in `providers/base.py` with docstring from the design doc
- [ ] in `providers/claude.py`, set `has_yolo_confirmation=True` in `ClaudeProvider.capabilities`
- [ ] in `providers/claude.py`, implement `scrape_current_mode` — move `_find_mode_line`, `_mode_short_label`, and the sentinel strings (`"auto-accept edits"`, `"Plan mode"`, `"Full tool access"`) from `toolbar_callbacks.py`. Use `tmux_manager.capture_pane` via `self._capture_pane` or direct import.
- [ ] `providers/codex.py`, `gemini.py`, `shell.py` do NOT override — they use the Protocol default
- [ ] add unit tests: `test_claude_scrape_current_mode_edit`, `test_claude_scrape_current_mode_plan`, `test_claude_scrape_current_mode_full`, `test_claude_scrape_current_mode_none`, `test_shell_scrape_current_mode_default_returns_none`, `test_has_yolo_confirmation_only_claude`
- [ ] run `make check` — must be green before Task 9

### Task 9: Extract `handlers/toolbar_keyboard.py`; slim `toolbar_callbacks.py`

**Files:**

- Create: `src/ccgram/handlers/toolbar_keyboard.py`
- Modify: `src/ccgram/handlers/toolbar_callbacks.py`
- Modify: `src/ccgram/handlers/callback_registry.py` (add `toolbar_keyboard` import if it registers callbacks — it probably doesn't, keyboard is pure UI)
- Modify: `src/ccgram/bot.py` (toolbar_command already uses `build_toolbar_keyboard`; update import path)
- Create: `tests/ccgram/handlers/test_toolbar_keyboard.py`
- Modify: `tests/ccgram/handlers/test_toolbar_callbacks.py`

- [ ] create `src/ccgram/handlers/toolbar_keyboard.py` with: `build_toolbar_keyboard(window_id, provider_name)`, `_make_button`, `_window_action_labels` dict, `_set_action_label`, `_get_action_label`, `_clear_window_labels` (cleanup via `@topic_state.register_bound("window", ...)` or free function if that's simpler here), `_get_toolbar_config`, `reload_toolbar_config`, `seed_button_states`
- [ ] in `toolbar_callbacks.py`, delete the now-moved functions; import from `toolbar_keyboard` where needed
- [ ] update `_refresh_button_label` in `toolbar_callbacks.py`:
  ```python
  async def _refresh_button_label(action, query, window_id):
      await asyncio.sleep(_READ_STATE_DELAY_S)
      provider = get_provider_for_window(window_id)
      label = await provider.scrape_current_mode(window_id) or action.default_label
      toolbar_keyboard._set_action_label(window_id, action.name, label)
      view = session_manager.view_window(window_id)
      provider_name = view.provider_name if view else "claude"
      new_kb = toolbar_keyboard.build_toolbar_keyboard(window_id, provider_name)
      try:
          await query.edit_message_reply_markup(reply_markup=new_kb)
      except TelegramError: ...
      return label
  ```
- [ ] delete `_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`, `_READ_STATE_DELAY_S` from `toolbar_callbacks.py` (moved to provider in Task 8)
- [ ] verify `toolbar_callbacks.py` is ~300 lines (dispatch + built-ins only)
- [ ] write unit tests for `toolbar_keyboard.build_toolbar_keyboard` (default layout, unknown provider fallback, label override, style variants, callback data format, ≤64 bytes)
- [ ] update `test_toolbar_callbacks.py` — keep callback parsing tests, dispatch tests, built-in tests; remove scraping tests (now in `test_claude.py`)
- [ ] grep `rg "from \.toolbar_callbacks import build_toolbar_keyboard" src/ccgram/` — update each caller to `from .toolbar_keyboard import build_toolbar_keyboard`
- [ ] run `make check` — must be green

### Task 10: Replace `provider_name == "claude"` with capability flag

**Files:**

- Modify: `src/ccgram/handlers/directory_callbacks.py` L593

- [ ] replace `if approval_mode == "yolo" and provider_name == "claude":` with `if approval_mode == "yolo" and provider.capabilities.has_yolo_confirmation:` — the `provider` object is already in scope at this point (resolved earlier in the function)
- [ ] update relevant test in `test_directory_callbacks.py` to pass a provider with `has_yolo_confirmation=True/False` and verify both branches
- [ ] run `make check` — must be green
- [ ] run `make test-e2e` — Phase 4 sanity check

### Phase 5 — Opportunistic Cleanup

### Task 11: Extract `handlers/status_bar_actions.py`

**Files:**

- Create: `src/ccgram/handlers/status_bar_actions.py`
- Modify: `src/ccgram/handlers/screenshot_callbacks.py`
- Modify: `src/ccgram/handlers/callback_registry.py` (`load_handlers` imports)
- Create: `tests/ccgram/handlers/test_status_bar_actions.py`
- Modify: `tests/ccgram/handlers/test_screenshot_callbacks.py`

- [ ] create `status_bar_actions.py` with module docstring: "Status-bubble button callbacks (notify toggle, recall, remote control, esc, keys)"
- [ ] move from `screenshot_callbacks.py`: `_handle_notify_toggle`, `_handle_status_recall`, `_handle_remote_control`, `_handle_status_esc`, `_handle_keys`, `_schedule_key_refresh` (and its inner `_do_refresh`), `_pending_key_refreshes` dict, `_clear_key_refreshes` cleanup
- [ ] add a new `_dispatch` function decorated with `@register(CB_STATUS_NOTIFY, CB_STATUS_RECALL, CB_STATUS_REMOTE, CB_STATUS_ESC, CB_STATUS_KEY)`
- [ ] `_handle_status_screenshot` stays in `screenshot_callbacks.py` — it is the one status-bar action that legitimately belongs there
- [ ] `_handle_status_esc` stays? review: it's "send Escape via the status bubble button" — belongs in status_bar_actions (key dispatch), not screenshot
- [ ] update `callback_registry.load_handlers()` to import `status_bar_actions`
- [ ] verify `screenshot_callbacks.py` is ~350 lines after the move (down from 764)
- [ ] write unit tests for each moved function against its respective CB\_ prefix — use mocked `session_manager`, mocked `tmux_manager`
- [ ] update `test_screenshot_callbacks.py` — remove moved tests
- [ ] run `make check` — must be green before Task 12

### Task 12: WindowView migration for 6 read-only handlers

**Files:**

- Modify: `src/ccgram/handlers/file_handler.py`
- Modify: `src/ccgram/handlers/history.py`
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/text_handler.py`
- Modify: `src/ccgram/handlers/send_command.py`
- Modify: `src/ccgram/handlers/topic_emoji.py`
- Modify: corresponding tests

- [ ] in each handler, replace `session_manager.get_window_state(wid).{field}` reads with `session_manager.view_window(wid).{field}` where the only purpose is to read a scalar
- [ ] `file_handler.py` — read `cwd` via `view_window`
- [ ] `history.py` — read `transcript_path` via `view_window`
- [ ] `shell_commands.py` — read `cwd` via `view_window`
- [ ] `text_handler.py` — read `cwd` via `view_window`
- [ ] `send_command.py` — read `cwd` via `view_window`
- [ ] `topic_emoji.py` — read `approval_mode` via `view_window` (only if it is a pure read; if it also calls `set_approval_mode`, keep `get_window_state`)
- [ ] handle `None` return from `view_window` in every migrated site — match the existing behaviour when `get_window_state` returned a default
- [ ] update each handler's tests to use `WindowView` fixtures instead of `WindowStateStore` wiring — where possible
- [ ] track progress with `grep -c 'session_manager\.get_window_state' src/ccgram/handlers/*.py` — verify the count decreased by 6
- [ ] run `make check` — must be green before Task 13

### Task 13: Residual cleanup — `session.py` display-name access, `send_command._upload_file` rename

**Files:**

- Modify: `src/ccgram/session.py` (L412, L414, L495)
- Modify: `src/ccgram/handlers/send_command.py`
- Modify: `src/ccgram/handlers/send_callbacks.py`
- Modify: corresponding tests

- [ ] in `session.py` L412, L414: replace `thread_router.window_display_names[wid]` with `thread_router.get_display_name(wid)` / `pop_display_name(wid)` — verify which semantics the current code needs at each site
- [ ] in `session.py` L495: replace `thread_router.window_display_names[wid]` with `thread_router.get_display_name(wid)` (read-only)
- [ ] verify: `rg "thread_router\.window_display_names\[" src/ccgram/` — zero matches expected
- [ ] in `send_command.py`, rename `_upload_file` → `upload_file` (promote to public)
- [ ] in `send_callbacks.py`, update the import: `from .send_command import upload_file, build_file_browser`
- [ ] grep: `rg "_upload_file" src/ccgram/` and `rg "upload_file" src/ccgram/` — verify no other callers leaked
- [ ] update tests: `test_session.py` for the display-name path (existing tests should stay green); `test_send_command.py` / `test_send_callbacks.py` for the renamed function
- [ ] run `make check` — must be green before verification

### Task 14: Verify acceptance criteria

- [ ] re-read `docs/design/2026-04-13/architecture.md` — verify every "Refactored" module in the module map is actually refactored in this plan
- [ ] re-read `docs/modularity-review/2026-04-13/modularity-review.md` — verify every Significant issue maps to a completed task
- [ ] grep validations:
  - `rg "TerminalStatusStrategy" src/ccgram/` — zero matches
  - `rg "window_display_names\[" src/ccgram/` — zero matches
  - `rg '== "claude"' src/ccgram/handlers/` — zero matches
  - `rg "_upload_file" src/ccgram/` — zero matches
  - `rg "def _scrape_current_mode" src/ccgram/handlers/toolbar_callbacks.py` — zero matches
- [ ] line-count sanity:
  - `wc -l src/ccgram/handlers/message_queue.py` — expect 450–550 (from 1132)
  - `wc -l src/ccgram/handlers/tool_batch.py` — expect ~350
  - `wc -l src/ccgram/handlers/status_bubble.py` — expect ~300
  - `wc -l src/ccgram/handlers/toolbar_callbacks.py` — expect ~300
  - `wc -l src/ccgram/handlers/toolbar_keyboard.py` — expect ~200
  - `wc -l src/ccgram/handlers/screenshot_callbacks.py` — expect ~350
  - `wc -l src/ccgram/handlers/status_bar_actions.py` — expect ~200
  - `wc -l src/ccgram/handlers/shell_prompt_orchestrator.py` — expect ~120
  - `wc -l src/ccgram/handlers/polling_strategies.py` — expect ~550 (from 653, minus 20+ wrappers)
- [ ] `grep -c 'session_manager\.get_window_state' src/ccgram/handlers/*.py` — verify total count dropped
- [ ] run `make check` — full suite green
- [ ] run `make test-e2e` — final e2e run (~3-4 min)

### Task 15: Update documentation

**Files:**

- Modify: `.claude/rules/architecture.md` (module inventory)
- Modify: `CLAUDE.md` (handler list, if any entries changed)
- Modify: `docs/modularity-review/2026-04-13/modularity-review.md` (add a "Resolved" section at the end pointing at this plan)

- [ ] update `.claude/rules/architecture.md` module inventory: add `tool_batch.py`, `toolbar_keyboard.py`, `shell_prompt_orchestrator.py`, `status_bar_actions.py`; note the `TerminalStatusStrategy` split; note the `topic_state.register_bound` capability
- [ ] update `CLAUDE.md` if any user-visible pattern changed — probably just the handler inventory table
- [ ] add a short "Resolved by 20260413-architecture-refactor" note at the bottom of `docs/modularity-review/2026-04-13/modularity-review.md`
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification** (if applicable):

- Run the bot against a real Telegram group: exercise `/toolbar` (especially toggle buttons — verify the label updates via the new provider capability), `/send` (browse + upload), `/history`, `/resume`, `/restore`, shell topic creation (verify auto-setup), external shell window bind (verify offer keyboard), provider switch mid-session (verify provider_switch trigger), tool-use batching (Claude session with many tool calls in one turn).
- Verify state.json and session_map.json round-trip cleanly after a bot restart mid-refactor.
- Soak test: leave the bot running with an active Claude session for ≥1h; verify no leaked state in the scattered per-window dicts (look for growth in `_active_batches`, `_status_msg_info`, `_window_action_labels`, etc.).

**External system updates** (if applicable):

- None — this is internal refactoring with no API surface changes.
- Optional: bump version + CHANGELOG entry if cutting a release. Recommended version: `2.10.0` (minor bump; no public API breakage, but substantial internal reshuffle).
- Architecture map doc (`docs/ai-agents/architecture-map.md`) may need a refresh if module boundaries are user-facing.
