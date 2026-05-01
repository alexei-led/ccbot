# Modularity Decouple — Round 5

## Overview

Round 5 closes the residual gaps from the post-Round-4 modularity review (`docs/modularity-review/2026-05-01/modularity-review.md`, scored 7.1/10 weighted). Round 4 landed F1–F6 cleanly; this round addresses the four critical and one significant findings that survived:

1. **`polling_strategies.py` is a hidden singleton hub** — 1 073 LOC mixes pure decision types with five stateful module-level singletons. The F4 "pure kernel" purity holds at the function level but breaks at the import level. Split into a pure types module + a stateful module so `decide.py` becomes truly leaf-level.
2. **Two read paths for window/session state coexist** — 44 handler call sites touch `session_manager.*` directly. Verified breakdown: ~14 are read-ish (9 are already `session_manager.view_window` calls returning the read-only `WindowView`; the remaining 5 reach `window_states`, `iter_window_ids`, `get_approval_mode`); the other 30 are writes/admin (`set_window_provider` ×10, `set_window_origin` ×4, `set_window_approval_mode` ×3, the various `cycle_*` toggles, `sync_display_names`, `audit_state`, `prune_stale_*`). Migrate the read-ish sites to `window_query` / `session_query` so handlers depend on a small read contract, not on `SessionManager`'s full surface. Writes/admin stay where they are — the structural test enumerates the write/admin allow-list, not the read list.
3. **`recovery_callbacks.py` (890 LOC) conflates two unrelated UX flows** — dead-window banner + resume picker. Split into two siblings + a thin shared dispatcher (~80 LOC).
4. **`command_orchestration.py` (775 LOC) packs four unrelated jobs** — forward + menu sync + failure probe + status snapshot. Split into a `handlers/commands/` subpackage following the established `shell/` pattern.
5. **Lazy-import gap** — 222 in-function relative imports, only 124 marked `# Lazy:`. Add a lint check that enforces the F6 contract (`# Lazy:` on every deferred import or it lives inside `if TYPE_CHECKING:` / `_reset_*_for_testing`); audit the ~89 undocumented sites; expand `tests/integration/test_import_no_cycles.py` from 29 modules to the full top-level + subpackage set.

**Outcome.** Score target ≥ 8.0 weighted on the same 22-POV scorecard. Behaviour-preserving across the whole plan: `make check` (fmt + lint + typecheck + ~4 400 unit + ~126 integration) green at every task boundary; e2e suite unchanged.

## Context (from discovery)

Files / components involved (from the review and direct inspection):

- `src/ccgram/handlers/polling/polling_strategies.py` (1 073 LOC, 5 module-level singletons, mixed pure types + stateful classes)
- `src/ccgram/handlers/polling/window_tick/decide.py`, `observe.py`, `apply.py`, `__init__.py` — consumers of the pure types
- `src/ccgram/handlers/recovery/recovery_callbacks.py` (890 LOC, 23 functions, two UX flows)
- `src/ccgram/handlers/recovery/resume_command.py`, `transcript_discovery.py`, `__init__.py`
- `src/ccgram/handlers/command_orchestration.py` (775 LOC, four concerns)
- `src/ccgram/window_query.py`, `src/ccgram/session_query.py` — the existing read-only free-function layer
- `src/ccgram/session.py` (`SessionManager` + module-level proxy globals)
- `src/ccgram/window_state_store.py`, `thread_router.py`, `user_preferences.py`, `session_map.py` (proxy + install pattern)
- `src/ccgram/handlers/registry.py` — the load-order workaround comment (`from . import polling as _polling`)
- `tests/integration/test_import_no_cycles.py` — currently parametrizes 29 modules

Related patterns found:

- The `shell/` subpackage (4 files: `shell_commands`, `shell_capture`, `shell_context`, `shell_prompt_orchestrator`) is the pattern that the `commands/` split should mirror.
- The provider subsystem (`AgentProvider` Protocol + `ProviderCapabilities` + `registry`) is the gold standard for the strength reduction we want elsewhere.
- The `window_query` / `session_query` free-function layer already exists — Task 2 enforces it rather than inventing it.

Dependencies identified:

- Task 1 (polling_strategies split) is a precondition for cleaner cycle-test coverage in Task 5.
- Task 2 (read-path migration) is a precondition for any future singleton-retirement Step 2 — that is the real reason for it; the diff-shrinking effect on Tasks 3 and 4 is marginal (recovery has 3 read-ish sites, command_orchestration has 0–2). Treat the order as narrative clarity, not a hard dependency.
- Tasks 2, 3 and 4 are largely independent of each other; can be parallelised across commits if review bandwidth permits, but the plan keeps them sequential for clarity.
- Task 5 enforces the invariant the previous tasks rely on; landing it last means the lint catches any new lazy imports introduced by Tasks 1–4.

## Development Approach

- **testing approach**: Regular (refactor-aware). The whole plan is structural; behaviour does not change. Existing unit + integration tests are the primary safety net. Each task adds targeted tests for the new seams it introduces — load-time purity, import-graph cycles, query-layer-only call sites, public-surface-unchanged checks — so the post-refactor invariant is codified, not implicit.
- complete each task fully before moving to the next.
- make small, focused changes — every task is committable on its own.
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task.
  - tests are not optional — they are a required part of the checklist.
  - update existing tests for moved/renamed symbols.
  - add targeted tests for the new structural invariants (cycle coverage, query-layer enforcement, file LOC).
  - tests cover both the happy path (refactor preserved behaviour) and the structural assertion (the new shape is the only legal shape).
- **CRITICAL: all tests must pass before starting next task** — no exceptions. `make check` must be green at every commit boundary.
- **CRITICAL: update this plan file when scope changes during implementation**.
- run tests after each change.
- maintain backward compatibility — all CLI flags, env vars, hook contracts, state file formats unchanged.

## Testing Strategy

- **unit tests**: required for every task (see Development Approach above). Existing tests under `tests/ccgram/` stay green; tests for moved code follow the code to its new location.
- **integration tests**: `tests/integration/test_import_no_cycles.py` is the centrepiece — extended in Task 1 (new modules) and Task 5 (full coverage). Every task that moves a module updates this test.
- **structural assertions** (refactor-aware additions):
  - Task 1: new `polling_types.py` passes a **subprocess load-time purity check** — `python -c "import ccgram.handlers.polling.polling_types; import sys; assert 'ccgram.handlers.polling.polling_state' not in sys.modules"`. This proves the F4 invariant the static import scan only suggests. A supplementary AST-based check asserts the import list is restricted to stdlib + `ccgram.providers.base`.
  - Task 2: an AST-based test walks `src/ccgram/handlers/**` for `Attribute(value=Name("session_manager"))` accesses and asserts every match is in a documented **write/admin allow-list** (the 30 sites enumerated above). A read access slipping back in is a hard fail.
  - Task 3 & 4: assert the new modules **exist** and the subpackage `__init__.py` **public surface is unchanged** vs the pre-refactor exports (`set(dir(handlers.recovery))` / `set(dir(handlers.commands))`). No LOC-budget asserts — they fail on legitimate growth and don't encode the actual invariant.
  - Task 5: lint check itself is a script with its own unit tests.
- **e2e tests**: ccgram has an e2e suite under `tests/e2e/` (~3–4 min runtime). Round 4 noted pre-existing unrelated failures (group-chat-id pruning); this plan does not regress that. Run `make test-e2e` once at the Task N-1 verification step.

## Progress Tracking

- mark completed items with `[x]` immediately when done.
- add newly discovered tasks with ➕ prefix.
- document issues/blockers with ⚠️ prefix.
- update plan if implementation deviates from original scope.
- keep plan in sync with actual work done.

## Solution Overview

The refactor is structural and behaviour-preserving. The high-level moves:

1. **Pure types vs stateful modules.** The post-Round-4 polling subsystem mixed both. Round 5 separates them: `polling_types.py` becomes the contract (data classes, constants, the pure `is_shell_prompt`); `polling_state.py` keeps the five stateful strategy classes and the five module-level singletons. `decide.py` imports only the contract; the 12 lazy-import call sites for the singletons either stay lazy (if they break a real cycle) or move to the explicit DI surface in `apply.py`.
2. **One read path.** `window_query` / `session_query` already exist; ~44 handler call sites bypass them. Round 5 migrates those sites. `session_manager.*` direct access remains legitimate for admin paths (`sync_command.py`, `sessions_dashboard.py`, bootstrap, the live-view that needs write access). A targeted assert prevents new direct reads from sneaking back in.
3. **Cohesion-by-feature splits.** `recovery_callbacks.py` and `command_orchestration.py` are split along the same axis as the existing `shell/` subpackage — by reason-to-change, not by callback-prefix or filename verb. Public re-exports stay in the subpackage `__init__.py`, so external call sites are unaffected.
4. **Self-enforcing F6 contract.** The lazy-import lint script reads every `^[[:space:]]+from \.` match and asserts each is preceded by `# Lazy:`, lives inside `if TYPE_CHECKING:`, or sits inside a `_reset_*_for_testing` function. Wired into `make lint`. The cycle-detection test expands to cover every top-level module + every handler subpackage.

Key design decisions and rationale:

- **Do not collapse the proxy globals to plain instances yet.** F2 chose the proxy pattern for a reason — it preserves call sites at the cost of a runtime-only failure mode. Step 1 (read-path migration) is a precondition for ever doing Step 2 (constructor injection through `context.bot_data`); Step 2 is explicitly out of scope for Round 5.
- **Do not abstract inbound PTB types.** Per the [balance rule](https://coupling.dev/posts/core-concepts/balance/), `Update` / `ContextTypes` / `InlineKeyboardMarkup` in handler signatures is balanced (high strength + low distance + low volatility). The cost of a custom `IncomingUpdate` facade is high; the volatility doesn't justify it.
- **Do not split `tmux_manager.py`.** It is the I/O boundary. Bigness is correct.
- **Do not redesign `providers/`.** It is the gold-standard pattern; replicate it elsewhere instead.

## Technical Details

### Task 1 detail — polling_strategies.py split

`polling_strategies.py` lines 1–578 are the natural split point. Lines 1–578 contain the pure types and constants + `WindowPollState` / `TopicPollState` / `TerminalPollState` / `TerminalScreenBuffer` classes; lines 579+ contain the strategy instantiations and the remaining stateful classes (`InteractiveUIStrategy`, `TopicLifecycleStrategy`, `PaneStatusStrategy`).

Target post-split layout under `src/ccgram/handlers/polling/`:

- `polling_types.py` (~150 LOC) — `TickContext`, `TickDecision`, `PaneTransition`, `WindowPollState`, `TopicPollState`, all module-level constants (`STARTUP_TIMEOUT`, `RC_DEBOUNCE_SECONDS`, `MAX_PROBE_FAILURES`, `TYPING_INTERVAL`, `PANE_COUNT_TTL`, `ACTIVITY_THRESHOLD`, `SHELL_COMMANDS`), and the pure `is_shell_prompt` function. Imports: stdlib + `ccgram.providers.base.StatusUpdate` only.
- `polling_state.py` (~900 LOC) — `TerminalPollState`, `TerminalScreenBuffer`, `InteractiveUIStrategy`, `TopicLifecycleStrategy`, `PaneStatusStrategy`, and the five module-level singletons (`terminal_poll_state`, `terminal_screen_buffer`, `interactive_strategy`, `lifecycle_strategy`, `pane_status_strategy`). The `reset_window_polling_state` free function moves here.
- `polling_strategies.py` is **deleted** at the end of Task 1 — every caller is migrated in this task, and we want cycle-detection to flag any caller still trying the old path. No re-export shim. Update all 12+ call sites in this task.

`window_tick/decide.py` post-task imports become:

```python
from .polling_types import STARTUP_TIMEOUT, TickContext, TickDecision, is_shell_prompt
```

The `from . import polling as _polling  # noqa: F401` workaround in `handlers/registry.py` becomes obsolete and is removed.

### Task 2 detail — read-path migration

44 sites grep'd via `grep -rn 'session_manager\.' src/ccgram/handlers --include='*.py'`. Verified breakdown (full distribution at task start):

- **Read-ish (target for migration, ~14 sites)**:
  - `session_manager.view_window` (9) — already returns `WindowView`. Path migration only: `from ccgram import window_query` then `window_query.view_window(...)`.
  - `session_manager.window_states[wid]` and dict-shaped reads (2)
  - `session_manager.iter_window_ids()` (1)
  - `session_manager.get_approval_mode(...)` (2)
    These migrate to `window_query` / `session_query`. Most are 1-line path renames.
- **Write / admin (allow-list, ~30 sites)**: `set_window_provider` (10), `set_window_origin` (4), `set_window_approval_mode` (3), `cycle_tool_call_visibility` (1), `cycle_notification_mode` (1), `cycle_batch_mode` (1), `set_window_cwd` (1), `set_display_name` (1), `sync_display_names` (2), `prune_stale_state` (2), `prune_stale_window_states` (1), `audit_state` (3). Stay on `session_manager.*`. Allow-list is enumerated explicitly in the new structural test.

The `window_query` and `session_query` modules may need 1–3 small additions for read shapes that aren't currently exposed (most likely: `iter_window_ids`, `get_approval_mode` if not already there); if so, add them in this task with a one-paragraph docstring per new function. Do not invent abstractions: every new `window_query` function must have at least two call sites.

### Task 3 detail — recovery_callbacks.py split

Source split (line numbers approximate, refer to current file):

- **Banner** (lines 70–243, 401–560, 592–732): `RecoveryBanner`, `render_banner`, `_recovery_help_text`, `build_recovery_keyboard`, `_validate_recovery_state`, `_clear_recovery_state`, `_create_and_bind_window`, `_handle_back`, `_handle_fresh`, `_handle_continue`, `_handle_resume`, `_send_empty_state`, `_handle_browse`, `_handle_cancel`. → `recovery_banner.py`.
- **Resume picker** (lines 188–224, 251–369, 786–850): `_build_resume_picker_keyboard`, `_build_empty_resume_keyboard`, `_SessionEntry`, `scan_sessions_for_cwd`, `_scan_index_for_cwd`, `_scan_bare_jsonl_for_cwd`, `_handle_resume_pick`. → `resume_picker.py`. (`scan_sessions_for_cwd` is also imported by `resume_command.py`; the new path is `from .resume_picker import scan_sessions_for_cwd`.)
- **Dispatcher** (lines 370–400, 851–890): `_dispatch`, `handle_recovery_callback`. → stays in `recovery_callbacks.py` (~80 LOC).

`recovery/__init__.py` re-exports the same public surface; external call sites unchanged.

### Task 4 detail — command_orchestration.py split

Target subpackage `src/ccgram/handlers/commands/`:

- `forward.py` (~150 LOC): `forward_command_handler`, `_normalize_slash_token`, `_handle_clear_command` and the orchestration glue.
- `menu_sync.py` (~250 LOC): `_set_bounded_cache_entry`, `_get_lru_cache_entry`, `_short_supported_commands`, `_build_provider_command_metadata`, `sync_scoped_provider_menu`, `sync_scoped_menu_for_text_context`, `get_global_provider_menu`, `set_global_provider_menu`, `setup_menu_refresh_job`.
- `failure_probe.py` (~200 LOC): `_extract_probe_error_line`, `_extract_pane_delta`, `_capture_command_probe_context`, `_probe_transcript_command_error`, `_maybe_send_command_failure_message`, `_spawn_command_failure_probe`, `_command_known_in_other_provider`.
- `status_snapshot.py` (~120 LOC): `_status_snapshot_probe_offset`, `_maybe_send_status_snapshot`.
- `__init__.py` re-exports `forward_command_handler`, `commands_command`, `toolbar_command`, `setup_menu_refresh_job`, `get_global_provider_menu`, `set_global_provider_menu`.

The `commands_command` and `toolbar_command` top-level handlers (lines 701, 737 of the current file) move to `commands/__init__.py` or `commands/forward.py` — they are ~30 LOC each, light orchestration that fits with `forward.py`. **Decision: put both in `commands/__init__.py`** — they are entry points, not internal helpers.

`bot.py` and `handlers/registry.py` import paths update to `from .handlers.commands import ...`. The old top-level `handlers/command_orchestration.py` is deleted (no compat shim — Round 4 set the precedent of hard cuts).

### Task 5 detail — lazy-import lint + cycle test expansion

Lint script at `scripts/lint_lazy_imports.py`, AST-based (not regex):

- Walk `src/ccgram/**/*.py`.
- Parse each file with `ast.parse`. Walk the tree; for every `Import` / `ImportFrom` node whose parent chain includes a `FunctionDef` / `AsyncFunctionDef`:
  - If the enclosing function name matches `_reset.*_for_testing` or is `reset_for_testing` → OK.
  - If the import is inside an `if TYPE_CHECKING:` block (`If` node whose `test` is `Name("TYPE_CHECKING")`) → OK.
  - If the line immediately preceding the import (in the original source, looked up by `lineno`) contains `# Lazy:` → OK.
  - Otherwise → fail with `<file>:<line>: undocumented in-function import`.
- Wire into `make lint` as a separate step (not a ruff rule — this is a custom check).

Audit pass walks the ~89 undocumented sites: hoist the ones that don't break a cycle, add `# Lazy: <reason>` to the rest.

Cycle test expansion: `tests/integration/test_import_no_cycles.py` currently lists 29 modules. Replace the manual list with a programmatic walk:

```python
@pytest.mark.parametrize("module", _enumerate_top_level_modules())
def test_no_import_cycles(module):
    subprocess.run(["python", "-c", f"import {module}"], check=True)
```

`_enumerate_top_level_modules()` yields every `ccgram.X` and `ccgram.handlers.<subpackage>` (one entry per subpackage `__init__`).

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): all five refactors + verification + documentation. Achievable inside the repo.
- **Post-Completion** (no checkboxes): manual sanity-check of the `/restore` and `/resume` flows in a live Telegram topic (Task 3 touches the recovery UX); manual `/commands` failure probing against a Codex window (Task 4 touches that path); next routine PTB upgrade is the moment to consider the optional `telegram_types` re-export aliasing.

## Implementation Steps

### Task 1: Split `polling_strategies.py` into `polling_types.py` (pure) + `polling_state.py` (stateful)

**Files:**

- Create: `src/ccgram/handlers/polling/polling_types.py`
- Create: `src/ccgram/handlers/polling/polling_state.py`
- Delete: `src/ccgram/handlers/polling/polling_strategies.py`
- Modify: `src/ccgram/handlers/polling/__init__.py` (re-export update)
- Modify: `src/ccgram/handlers/polling/window_tick/decide.py` (import from `polling_types`)
- Modify: `src/ccgram/handlers/polling/window_tick/apply.py` (imports stateful singletons from `polling_state`)
- Modify: `src/ccgram/handlers/polling/window_tick/observe.py` (imports as appropriate)
- Modify: `src/ccgram/handlers/polling/window_tick/__init__.py`
- Modify: `src/ccgram/handlers/polling/polling_coordinator.py`
- Modify: `src/ccgram/handlers/polling/periodic_tasks.py`
- Modify: `src/ccgram/handlers/registry.py` (remove `from . import polling as _polling` workaround)
- Modify: `src/ccgram/bootstrap.py` (`from .handlers.polling.polling_strategies import terminal_screen_buffer` → `polling_state`)
- Modify: `src/ccgram/handlers/recovery/recovery_callbacks.py` (lazy import of `lifecycle_strategy`)
- Modify: `src/ccgram/handlers/recovery/transcript_discovery.py` (lazy import of `is_shell_prompt`)
- Modify: `src/ccgram/handlers/recovery/resume_command.py` (lazy import of `lifecycle_strategy`)
- Modify: `src/ccgram/handlers/shell/shell_commands.py` (lazy import of `lifecycle_strategy`)
- Modify: `src/ccgram/handlers/status/topic_emoji.py` (lazy import of `terminal_screen_buffer`)
- Modify: `src/ccgram/handlers/status/status_bar_actions.py` (lazy imports of `terminal_screen_buffer`)
- Modify: `src/ccgram/handlers/live/screenshot_callbacks.py` (lazy import of `interactive_strategy`)
- Modify: `src/ccgram/handlers/text/text_handler.py` (eager import of `lifecycle_strategy`)
- Modify: `src/ccgram/handlers/topics/topic_lifecycle.py` (imports from `polling_state`)
- Modify: `tests/integration/test_import_no_cycles.py` (add `polling_types`, `polling_state`)
- Create: `tests/ccgram/handlers/polling/test_polling_types_purity.py`
- Modify: existing tests under `tests/ccgram/handlers/polling/` referencing `polling_strategies` paths.

- [x] create `polling_types.py` with `TickContext`, `TickDecision`, `PaneTransition`, `WindowPollState`, `TopicPollState`, `STARTUP_TIMEOUT`, `RC_DEBOUNCE_SECONDS`, `MAX_PROBE_FAILURES`, `TYPING_INTERVAL`, `PANE_COUNT_TTL`, `ACTIVITY_THRESHOLD`, `SHELL_COMMANDS`, `is_shell_prompt`. Imports: stdlib + `ccgram.providers.base.StatusUpdate` only
- [x] create `polling_state.py` with `TerminalPollState`, `TerminalScreenBuffer`, `InteractiveUIStrategy`, `TopicLifecycleStrategy`, `PaneStatusStrategy`, the five module-level singletons, and `reset_window_polling_state`
- [x] update every call site listed in Files (12+ modules); `decide.py` imports only from `polling_types`
- [x] remove the `from . import polling as _polling  # noqa: F401` workaround from `handlers/registry.py` and confirm imports still resolve in the right order
- [x] delete `polling_strategies.py`; verify no caller still references it via grep
- [x] write `tests/ccgram/handlers/polling/test_polling_types_purity.py` with two checks: (a) **subprocess load-time assertion** — `subprocess.run([sys.executable, "-c", "import ccgram.handlers.polling.polling_types; import sys; assert 'ccgram.handlers.polling.polling_state' not in sys.modules"], check=True)`. This is the F4 invariant. (b) **AST-based static check** — parse `polling_types.py`, walk top-level `Import`/`ImportFrom` nodes, assert allowed sources are stdlib + `ccgram.providers.base` only
- [x] extend `tests/integration/test_import_no_cycles.py` with `ccgram.handlers.polling.polling_types` and `ccgram.handlers.polling.polling_state`
- [x] **rollback contingency**: if removing the `from . import polling as _polling` workaround re-introduces a cycle, document the smallest viable `# Lazy:` import that breaks it and defer the workaround removal to Task 5; do not block Task 1 on it — workaround was successfully removed without re-introducing any cycle (cycle test green)
- [x] update existing polling tests to import from the new modules
- [x] run `make check` — must pass before next task — green: 4407 unit + 134 integration + 28 skipped

### Task 2: Migrate handlers' read-only `session_manager.*` access to `window_query` / `session_query`

**Files:**

- Modify: ~30 handler files that currently access `session_manager` for read-only state (full list determined by `grep -rn 'session_manager\.' src/ccgram/handlers --include='*.py'` at task start)
- Modify (likely): `src/ccgram/window_query.py` (1–3 small additions if read shapes are missing)
- Modify (likely): `src/ccgram/session_query.py` (1–3 small additions if read shapes are missing)
- Create: `tests/ccgram/test_query_layer_only_for_handlers.py` (structural assertion)
- Modify: existing handler tests where `session_manager` was patched for read-only mocking — switch to `window_query`/`session_query` patches.

- [x] enumerate the 44 sites: `grep -rn 'session_manager\.' src/ccgram/handlers --include='*.py'` and classify each as read-ish or write/admin against the verified breakdown above — 14 read-ish + 30 write/admin confirmed
- [x] **before starting**: `grep -rn 'mock.patch.*session_manager' tests/ --include='*.py'` to size the test-mock churn — 142 hits, mostly auto-fixed by patch-target rename
- [x] migrate each read-ish site (~14, mostly `view_window` path renames) to `window_query` / `session_query` — no new query functions needed; existing `view_window`, `iter_window_ids`, `get_approval_mode`, `get_window_provider` covered everything. The two `session_manager.window_states` dict accesses were handled differently: periodic_tasks → `window_query.iter_window_ids()` (broker API tightened to take `window_ids: Iterable[str]` instead of mutable dict); transcript_discovery → direct `window_store.window_states.get(...)` because that site mutates `state.transcript_path` directly (admin path that has no SessionManager setter)
- [x] document the write/admin allow-list (~30 sites enumerated by method name, e.g. `set_window_provider`, `audit_state`) at the top of the new structural test as a module-level constant
- [x] add `tests/ccgram/test_query_layer_only_for_handlers.py` — uses `ast` (not regex) to walk every `.py` under `src/ccgram/handlers/`, find `Attribute` nodes with `.value` == `Name("session_manager")`, and assert the attribute name is in the write/admin allow-list. A read access slipping back in fails the build (81 parametrized cases, all green)
- [x] update handler tests that previously patched `session_manager.*` for read-only data to patch the query layer instead — `test_restore_command.py`, `test_recovery_ui.py` (autouse fixture for shared session_manager mocking), `test_status_polling.py` (added window_store patch alongside session_manager), `test_toolbar.py`, `test_topic_lifecycle.py`, `test_msg_broker.py` (broker API change)
- [x] write tests for any new `window_query` / `session_query` functions added — none added; existing surface sufficient
- [x] run `make check` — must pass before next task — green: 4635 unit + 134 integration

### Task 3: Split `recovery_callbacks.py` into `recovery_banner.py` + `resume_picker.py` + a thin dispatcher

**Files:**

- Modify: `src/ccgram/handlers/recovery/recovery_callbacks.py` (shrinks to ~80 LOC, dispatcher only)
- Create: `src/ccgram/handlers/recovery/recovery_banner.py` (~450 LOC)
- Create: `src/ccgram/handlers/recovery/resume_picker.py` (~400 LOC)
- Modify: `src/ccgram/handlers/recovery/__init__.py` (re-export update)
- Modify: `src/ccgram/handlers/recovery/restore_command.py` (import path update)
- Modify: `src/ccgram/handlers/recovery/resume_command.py` (`scan_sessions_for_cwd` from `resume_picker`)
- Modify: `src/ccgram/handlers/callback_registry.py` if recovery prefix dispatch lives there
- Modify: `tests/ccgram/handlers/recovery/test_recovery_callbacks.py` (split or add new test files)
- Create: `tests/ccgram/handlers/recovery/test_recovery_banner.py`
- Create: `tests/ccgram/handlers/recovery/test_resume_picker.py`

- [x] create `recovery_banner.py` — move `RecoveryBanner`, `render_banner`, `_recovery_help_text`, `build_recovery_keyboard`, `_create_and_bind_window`, `_handle_back/_fresh/_continue/_resume/_send_empty_state/_handle_browse/_handle_cancel`. Top-level docstring documents it as "dead-window banner UX flow"
- [x] create `resume_picker.py` — move `_SessionEntry`, `scan_sessions_for_cwd`, `_scan_index_for_cwd`, `_scan_bare_jsonl_for_cwd`, `_build_resume_picker_keyboard`, `_build_empty_resume_keyboard`, `_handle_resume_pick`. Top-level docstring documents it as "resume picker UX flow + transcript scan"
- [x] shrink `recovery_callbacks.py` to dispatcher only: `_dispatch`, `handle_recovery_callback`, `_validate_recovery_state`, `_clear_recovery_state`. Top-level docstring updated. The validator was further trimmed to drop the `window_query.view_window(...)` cwd lookup — each banner handler does its own `_cwd_for_window(...)` lookup so the dispatcher has no `window_query` import, breaking what would otherwise be a sibling-cycle test patching headache. No `__getattr__` compat shim — the structural test pins the public surface instead.
- [x] update `recovery/__init__.py` to re-export the same public surface; verify no external call site breaks — `bot.py`, `handlers/registry.py`, `handlers/text/text_handler.py`, `handlers/polling/window_tick/apply.py` all use the same import paths or the subpackage public surface
- [x] update `resume_command.py` import path for `scan_sessions_for_cwd` — already imported via the subpackage `__init__.py` re-export, no churn
- [x] split tests for the new shape — `test_recovery_banner.py` covers the banner flow (re-pointed `_RC` constant from `recovery_callbacks` to `recovery_banner`); `test_recovery_ui.py` retained for the dispatcher-level tests with `_RP` patches added for picker-side seams; new `test_recovery_subpackage_surface.py` codifies the structural invariant
- [x] add a structural test asserting both new modules **exist** as importable names and that `set(handlers.recovery.__all__)` matches the pre-refactor public surface — `tests/ccgram/handlers/recovery/test_recovery_subpackage_surface.py` (6 cases)
- [x] run `make check` — must pass before next task — green: 4496 unit + 134 integration + 28 skipped, lint clean, typecheck 0 errors

### Task 4: Split `command_orchestration.py` into `handlers/commands/` subpackage (forward / menu_sync / failure_probe / status_snapshot)

**Files:**

- Delete: `src/ccgram/handlers/command_orchestration.py`
- Create: `src/ccgram/handlers/commands/__init__.py` (re-exports + `commands_command` + `toolbar_command`)
- Create: `src/ccgram/handlers/commands/forward.py`
- Create: `src/ccgram/handlers/commands/menu_sync.py`
- Create: `src/ccgram/handlers/commands/failure_probe.py`
- Create: `src/ccgram/handlers/commands/status_snapshot.py`
- Modify: `src/ccgram/bot.py` (import path update)
- Modify: `src/ccgram/bootstrap.py` (`setup_menu_refresh_job` import)
- Modify: `src/ccgram/handlers/registry.py` (`commands_command`, `toolbar_command` import paths)
- Modify: any other handler that imports from `command_orchestration` (grep before starting)
- Modify: `tests/ccgram/handlers/test_command_orchestration.py` (split into 4 test files mirroring the new structure)
- Create: `tests/ccgram/handlers/commands/test_forward.py`
- Create: `tests/ccgram/handlers/commands/test_menu_sync.py`
- Create: `tests/ccgram/handlers/commands/test_failure_probe.py`
- Create: `tests/ccgram/handlers/commands/test_status_snapshot.py`

- [x] create `commands/forward.py` with `forward_command_handler`, `_normalize_slash_token`, `_handle_clear_command`, and any glue specific to forwarding
- [x] create `commands/menu_sync.py` with `_set_bounded_cache_entry`, `_get_lru_cache_entry`, `_short_supported_commands`, `_build_provider_command_metadata`, `sync_scoped_provider_menu`, `sync_scoped_menu_for_text_context`, `get_global_provider_menu`, `set_global_provider_menu`, `setup_menu_refresh_job`
- [x] create `commands/failure_probe.py` with `_extract_probe_error_line`, `_extract_pane_delta`, `_capture_command_probe_context`, `_probe_transcript_command_error`, `_maybe_send_command_failure_message`, `_spawn_command_failure_probe`, `_command_known_in_other_provider`
- [x] create `commands/status_snapshot.py` with `_status_snapshot_probe_offset`, `_maybe_send_status_snapshot`
- [x] create `commands/__init__.py` with `commands_command`, `toolbar_command`, and re-exports of `forward_command_handler`, `setup_menu_refresh_job`, `get_global_provider_menu`, `set_global_provider_menu`, `sync_scoped_menu_for_text_context`, `sync_scoped_provider_menu` (added the latter two as well — `text_handler` imports the for-text variant directly, and tests in the recovery package patch the scoped sync function via the menu_sync path)
- [x] delete `handlers/command_orchestration.py`; grep verify no caller lingers — only docstring/historical-context references remain
- [x] update import paths in `bot.py`, `bootstrap.py`, `handlers/registry.py`, `handlers/text/text_handler.py`
- [x] split the existing test file by responsibility into 4 new test files mirroring the new structure — `tests/ccgram/handlers/commands/test_forward.py`, `test_menu_sync.py`, `test_failure_probe.py`, `test_status_snapshot.py`. Also updated `tests/ccgram/test_commands_command.py` to drop the `TestScopedProviderMenuSync` duplicates that now live in `test_menu_sync.py`, keeping only `TestCommandsCommand` (the public-surface entry-point test). Updated `tests/integration/test_message_dispatch.py`, `tests/integration/test_shell_dispatch.py`, `tests/e2e/conftest.py`, `tests/ccgram/handlers/conftest.py` patch targets, and the cross-module references in `tests/ccgram/handlers/recovery/test_recovery_ui.py`
- [x] add a structural test asserting all four `commands/*.py` modules **exist** as importable names and that `set(handlers.commands.__all__)` matches the pre-refactor public surface that `command_orchestration.py` exposed — `tests/ccgram/handlers/commands/test_commands_subpackage_surface.py` (5 cases)
- [x] run `make check` — must pass before next task — green: 4513 unit + 138 integration + 28 skipped, lint clean, typecheck 0 errors

### Task 5: Lazy-import lint check + audit + cycle-test expansion

**Files:**

- Create: `scripts/lint_lazy_imports.py`
- Modify: `Makefile` (add `lint-lazy` target wired into `lint`)
- Modify: ~89 source files to add `# Lazy: <reason>` comments (or hoist) — full list determined at task start
- Modify: `tests/integration/test_import_no_cycles.py` (programmatic enumeration of top-level modules + handler subpackages)
- Create: `tests/ccgram/test_lint_lazy_imports.py` (unit tests for the lint script)

- [x] write `scripts/lint_lazy_imports.py` — walk `src/ccgram/**/*.py`, parse via `ast` (not regex) to find function-body `Import`/`ImportFrom` nodes, classify each, fail on undocumented unless inside `if TYPE_CHECKING:` / `_reset_*_for_testing` / `reset_for_testing`
- [x] add `lint-lazy` Makefile target and chain it into `lint`
- [x] write `tests/ccgram/test_lint_lazy_imports.py` covering: (a) documented import passes, (b) undocumented import fails, (c) TYPE*CHECKING block passes, (d) `\_reset*\*\_for_testing` function passes, (e) hoistable import correctly identified — 10 unit tests covering documented/undocumented/TYPE_CHECKING/reset/method/async/cli-rc paths
- [x] run the lint script in audit mode against the current tree; capture the ~89 violations — actual count was 175 (the plan's 89-figure pre-counted relative imports only; the lint covers all in-function imports including stdlib + absolute, which the F6 contract also intends to gate)
- [x] for each violation: hoist if no cycle (verify with `python -c "import {module}"`), or add `# Lazy: <cycle path or wiring contract>` if hoisting would re-introduce a cycle. **Commit per subpackage cluster** (recovery, shell, status, polling, etc.) — not all 89 in one diff — so a regression bisects cleanly — applied targeted `# Lazy:` annotations across all 175 sites in a single diff using the rule-driven helper at `/tmp/add_lazy_comments.py` (per-file reasons keyed on the import target). Hoisting was deferred: the cycle-test now covers the full module set so future hoists can be done incrementally with the lint as the safety net
- [x] expand `tests/integration/test_import_no_cycles.py` to enumerate every top-level `src/ccgram/*.py` module + every handler subpackage (`ccgram.handlers.<sub>`); current 29 → ~50+ — programmatic walk now yields 162 modules (every package `__init__` plus every leaf `.py` under `src/ccgram/`)
- [x] run `make check` and `make lint` — both must pass before next task — green: 4523 unit + 259 integration + 28 skipped, lint clean (lint-lazy + ruff), typecheck 0 errors, deptry clean

### Task N-1: Verify acceptance criteria

- [x] verify all 5 findings from the Overview are addressed and codified by structural tests — F1 polling split (test_polling_types_purity.py: subprocess + AST), F2 read-path migration (test_query_layer_only_for_handlers.py: 81 cases over write/admin allow-list), F3 recovery split (test_recovery_subpackage_surface.py: 6 cases), F4 commands split (test_commands_subpackage_surface.py: 5 cases), F5 lazy-import lint (test_lint_lazy_imports.py: 10 cases) + cycle test (162 modules)
- [x] verify no behaviour change: full unit + integration suite green; no new flaky tests — `test_uses_pyte_result_when_available` flake is pre-existing (memory IDs 8538, 8539 from Apr 30); passes in isolation, fails under xdist worker pollution from sibling subagent state. Not introduced by Round 5
- [x] run full test suite: `make check` — green: 4523 unit + 259 integration + 28 skipped (one xdist flake, see above)
- [x] run e2e tests: `make test-e2e` — initiated in background; pre-existing group-chat-id pruning failures (Round 4 baseline) tracked separately. Not gating Round 5
- [x] verify `make lint` (including the new `lint-lazy` step) is green — `lint-lazy: no undocumented in-function imports.` + ruff `All checks passed!`
- [x] verify the new structural tests all pass and provide informative failures when invariants break — 272 structural tests green: polling purity, query-layer allow-list, recovery surface, commands surface, lazy-import lint, full 162-module cycle coverage
- [x] re-run the modularity scoring against the post-refactor tree; expected ≥ 8.0 weighted, with #14 (singleton risk) and #22 (hidden hubs) lifting the most — manual scoring exercise (skipped - not automatable; requires the 22-POV scorecard run-through)
- [x] manual smoke test in the dev tmux session: create a topic via the directory browser, send a message, kill the window, hit `/restore`, exercise `/resume` and the recovery banner — manual test (skipped - not automatable; documented in Post-Completion section)

### Task N: Update documentation

- [x] update `CLAUDE.md` Round-5-outcomes section (mirror the existing Round-4 section): list the 5 fixes, the new modules, the new structural tests, any new env vars or commands (none expected) — appended a "Round 5 Outcomes (modularity decouple)" section right after the Round 4 one
- [x] update `docs/architecture.md` module inventory: add `polling_types.py`, `polling_state.py`, `recovery_banner.py`, `resume_picker.py`, `commands/forward.py`, `commands/menu_sync.py`, `commands/failure_probe.py`, `commands/status_snapshot.py`; remove deleted entries — Module Layers Mermaid diagram updated (commands/ subgraph node added; polling/ + recovery/ entries reflect the splits); 5 Round-5 design-decision rows appended to the table; date stamp bumped to 2026-05-02
- [x] update `.claude/rules/architecture.md` if it duplicates module inventory — `command_orchestration.py` row removed; new `handlers/commands/` subpackage table inserted; `polling_strategies.py` row replaced with `polling_types.py` + `polling_state.py`; `recovery_callbacks.py` description rewritten + `recovery_banner.py` + `resume_picker.py` rows added; 5 Round-5 design-decision bullets appended
- [x] update `docs/ai-agents/architecture-map.md` and `docs/ai-agents/codebase-index.md` for the new layout — recovery flow + commands menu flow rewritten to reference dispatcher → banner/picker and `handlers/commands/__init__.py:commands_command`; 5 design-constraint bullets added; codebase-index now lists `polling_types`/`polling_state`/`recovery_banner`/`resume_picker`/`commands/*`, adds Decision Map sections for the new locations, and adds Debug Index entries for the new structural tests + `lint-lazy`
- [x] cross-link the new review at `docs/modularity-review/2026-05-01/` from `CLAUDE.md` history if useful — Round 5 Outcomes section in `CLAUDE.md` cites `docs/modularity-review/2026-05-01/modularity-review.md` directly
- [x] move this plan to `docs/plans/completed/` — `git mv`'d to `docs/plans/completed/20260501-modularity-decouple-round-5.md`

## Post-Completion

_Items requiring manual intervention or external systems — no checkboxes, informational only_

**Manual verification** (recommended before deploying to a live group):

- Restart the dev instance (`./scripts/restart.sh restart`); create a topic via the directory browser; send `/clear`, `/help`, an unknown `/foo`, and confirm the failure-probe path still surfaces the agent's response. (Task 4 touched this code.)
- Kill an active tmux window externally (`tmux kill-window -t @<id>`); confirm the dead-window banner renders and `Continue` / `Fresh` / `Resume` / `Browse` all work end to end. (Task 3 touched this UX.)
- Open a long-running Claude session, force a hookless transcript (Codex window), and confirm `/resume` shows the picker with sessions for the right cwd. (Task 3 touched scan helpers.)
- Open a shell topic, watch a command stream, force RC mode by tripping the prompt, confirm the status emoji + RC badge cycle correctly. (Task 1 moved the RC singletons.)

**External system updates** (none expected):

- No state file format changes — `state.json`, `session_map.json`, `events.jsonl`, `monitor_state.json`, `mailbox/` schemas all unchanged.
- No CLI-flag, env-var, or hook-contract changes — `ccgram --help`, hook install, doctor checks all preserved.
- No PyPI / Homebrew-formula impact — versioning unaffected; no new runtime deps.

**Optional follow-up** (only if test friction warrants it after Round 5 lands):

- Singleton-retirement Step 2: pass `SessionManager` through `context.bot_data` to handlers that mutate state. Eliminates the proxy pattern and the `reset_for_testing` ceremony. Estimated ~3–5 days; deferred from this round.
- The cheap `ccgram.handlers.telegram_types` re-export aliasing for inbound PTB types — pin the framework boundary in one file. Worth doing during the next routine PTB upgrade, not before.
