# Modularity Fixes Round 3

## Overview

Implement two design changes from the 2026-04-16 modularity review to improve cohesion and close abstraction leaks:

1. **SessionManager facade dissolution** — remove 15 pure delegation methods, migrate callers to direct sub-object imports or existing query modules. Reduces SessionManager's public API from 39 to ~20 methods.
2. **Provider task-state abstraction** — add `supports_task_tracking` capability flag and `seed_task_state()`/`apply_task_entries()` protocol methods so `transcript_reader.py` never checks provider names.

Design docs: `docs/design/2026-04-16/`

## Context (from discovery)

- Files/components involved:
  - `src/ccgram/session.py` (799L) — SessionManager, primary target
  - `src/ccgram/window_query.py` (85L) — existing read-only query module
  - `src/ccgram/session_resolver.py` (274L) — session resolution singleton
  - `src/ccgram/transcript_reader.py` (385L) — has Claude name checks
  - `src/ccgram/providers/base.py` (308L) — AgentProvider protocol
  - `src/ccgram/providers/claude.py` (325L) — ClaudeProvider
  - 17+ handler files importing `session_manager`
- Related patterns: `window_query.py` already decouples read-only callers from SessionManager
- Dependencies: `session_map_sync`, `thread_router`, `window_store`, `user_preferences` singletons

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run `make check` after each task
- Maintain backward compatibility throughout

## Testing Strategy

- **Unit tests**: verify deleted methods are gone, new modules work, protocol methods dispatch correctly
- **Integration tests**: verify message routing and history flows work with new import paths
- **Grep-based invariant tests**: verify zero `session_manager.get_window_provider` calls remain, zero `capabilities.name == "claude"` checks remain in transcript_reader

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope

## Solution Overview

**SessionManager dissolution** proceeds in 4 phases:

1. Delete 4 dead delegation methods (zero external callers)
2. Migrate 7 callers from `session_manager.get_window_provider()` to existing `window_query.get_window_provider()`
3. Create `session_query.py` and migrate 4 session-resolution callers
4. Migrate 9 `session_map_sync` callers to direct imports, delete remaining passthroughs

**Provider task-state abstraction**:

1. Add `supports_task_tracking` flag to `ProviderCapabilities`
2. Add `seed_task_state()`/`apply_task_entries()` with default no-ops to `AgentProvider`
3. Implement in `ClaudeProvider`
4. Update `transcript_reader.py` to use capability flag + protocol methods
5. Remove `claude_task_state` import from `transcript_reader.py`

## Implementation Steps

### Task 1: Delete dead SessionManager delegation methods

**Files:**

- Modify: `src/ccgram/session.py`

These methods have zero external callers (verified by grep):

- [ ] delete `get_display_name()` — all 30+ callers already use `thread_router.get_display_name()` directly
- [ ] delete `get_window_for_chat_thread()` — all callers already use `thread_router.get_window_for_chat_thread()` directly
- [ ] delete `get_window_state()` — callers use `window_query.view_window()` or `window_store` directly
- [ ] delete `prune_stale_offsets()` — only called from `prune_stale_state()` which is on SessionManager itself (inline the call)
- [ ] verify no internal callers within `session.py` reference deleted methods (except `prune_stale_offsets` in `prune_stale_state`)
- [ ] update existing tests that reference deleted methods
- [ ] run `make check` — must pass before task 2

### Task 2: Migrate `get_window_provider` callers to `window_query`

**Files:**

- Modify: `src/ccgram/bot.py` (3 call sites)
- Modify: `src/ccgram/handlers/status_bar_actions.py` (1 call site)
- Modify: `src/ccgram/handlers/toolbar_keyboard.py` (1 call site)
- Modify: `src/ccgram/handlers/resume_command.py` (1 call site)
- Modify: `src/ccgram/handlers/recovery_callbacks.py` (2 call sites)
- Modify: `src/ccgram/session.py`

- [ ] in each file above, replace `session_manager.get_window_provider(wid)` with `window_query.get_window_provider(wid)` (or use existing `window_query` import if present)
- [ ] remove `session_manager` import from files that no longer use it after this change
- [ ] delete `get_window_provider()` from SessionManager
- [ ] migrate `clear_window_session` callers (2 sites: `command_orchestration.py`, `session_lifecycle.py`) to import `window_store.clear_window_session` directly
- [ ] delete `clear_window_session()` from SessionManager
- [ ] delete `get_session_id_for_window()` from SessionManager (already in `window_query`)
- [ ] grep to verify zero remaining `session_manager.get_window_provider` or `session_manager.clear_window_session` calls
- [ ] update tests referencing deleted methods
- [ ] run `make check` — must pass before task 3

### Task 3: Create `session_query.py` and migrate callers

**Files:**

- Create: `src/ccgram/session_query.py`
- Modify: `src/ccgram/handlers/message_routing.py`
- Modify: `src/ccgram/handlers/history.py`
- Modify: `src/ccgram/session.py`
- Create: `tests/ccgram/test_session_query.py`

- [ ] create `src/ccgram/session_query.py` with 3 free functions: `resolve_session_for_window`, `find_users_for_session`, `get_recent_messages` — each wrapping `session_resolver` with deferred import
- [ ] migrate `message_routing.py` (3 call sites) to import from `session_query`
- [ ] migrate `history.py` (1 call site) to import from `session_query`
- [ ] remove `session_manager` import from files that no longer use it
- [ ] delete `resolve_session_for_window`, `find_users_for_session`, `get_recent_messages`, `_get_session_direct` from SessionManager
- [ ] write tests for `session_query` functions (success + missing window/session cases)
- [ ] run `make check` — must pass before task 4

### Task 4: Migrate `session_map_sync` callers to direct imports

**Files:**

- Modify: `src/ccgram/session_monitor.py` (2 call sites: `load_session_map`, `prune_session_map`)
- Modify: `src/ccgram/handlers/directory_callbacks.py` (1 call site: `wait_for_session_map_entry`)
- Modify: `src/ccgram/handlers/sync_command.py` (1 call site: `prune_session_map`)
- Modify: `src/ccgram/handlers/transcript_discovery.py` (2 call sites: `register_hookless_session`, `write_hookless_session_map`)
- Modify: `src/ccgram/handlers/restore_command.py` (1 call site: `wait_for_session_map_entry`)
- Modify: `src/ccgram/handlers/resume_command.py` (1 call site: `wait_for_session_map_entry`)
- Modify: `src/ccgram/handlers/recovery_callbacks.py` (1 call site: `wait_for_session_map_entry`)
- Modify: `src/ccgram/session.py`

- [ ] in each handler/module file, replace `session_manager.<method>` with `session_map_sync.<method>` from `from ..session_map import session_map_sync`
- [ ] remove `session_manager` import from files that no longer use it
- [ ] delete `wait_for_session_map_entry`, `prune_session_map`, `load_session_map`, `register_hookless_session`, `write_hookless_session_map` from SessionManager
- [ ] grep to verify zero remaining `session_manager.load_session_map`, `session_manager.prune_session_map`, etc.
- [ ] update tests referencing deleted methods
- [ ] run `make check` — must pass before task 5

### Task 5: Add `supports_task_tracking` to provider protocol

**Files:**

- Modify: `src/ccgram/providers/base.py`
- Modify: `src/ccgram/providers/claude.py`

- [ ] add `supports_task_tracking: bool = False` field to `ProviderCapabilities` dataclass in `base.py`
- [ ] add `seed_task_state(self, window_id, session_id, transcript_path) -> None` method to `AgentProvider` protocol with default no-op body
- [ ] add `apply_task_entries(self, window_id, session_id, entries) -> None` method to `AgentProvider` protocol with default no-op body
- [ ] set `supports_task_tracking=True` in `ClaudeProvider.capabilities`
- [ ] implement `seed_task_state()` in `ClaudeProvider` — delegate to `claude_task_state.seed_from_transcript()` via deferred import
- [ ] implement `apply_task_entries()` in `ClaudeProvider` — delegate to `claude_task_state.apply_entries()` via deferred import
- [ ] write tests: capability flag defaults False, Claude has True, others have False
- [ ] write tests: default no-op methods don't raise on CodexProvider/GeminiProvider
- [ ] write tests: ClaudeProvider delegates to claude_task_state correctly (mock)
- [ ] run `make check` — must pass before task 6

### Task 6: Close the leak in `transcript_reader.py`

**Files:**

- Modify: `src/ccgram/transcript_reader.py`

- [ ] replace L127-128 `if provider.capabilities.name == "claude"` with `if provider.capabilities.supports_task_tracking` and call `await provider.seed_task_state(window_id, session_id, file_path)` instead of `self._seed_claude_task_state(...)`
- [ ] replace L152-153 `if provider.capabilities.name == "claude"` with `if provider.capabilities.supports_task_tracking` and call `provider.apply_task_entries(window_id, session_id, new_entries)` instead of `claude_task_state.apply_entries(...)`
- [ ] remove `_seed_claude_task_state` method from `TranscriptReader` (logic now in `ClaudeProvider.seed_task_state`)
- [ ] remove `from .claude_task_state import claude_task_state` import from `transcript_reader.py`
- [ ] grep `transcript_reader.py` for `claude_task_state` — zero matches expected
- [ ] grep `transcript_reader.py` for `capabilities.name` — zero matches expected
- [ ] update existing `transcript_reader` tests to use capability flag instead of provider name
- [ ] run `make check` — must pass before task 7

### Task 7: Verify acceptance criteria

- [ ] verify SessionManager public API is ~20 methods (down from 39)
- [ ] grep entire codebase: zero `session_manager.get_window_provider` calls
- [ ] grep entire codebase: zero `session_manager.get_display_name` calls
- [ ] grep entire codebase: zero `session_manager.load_session_map` calls
- [ ] grep `transcript_reader.py`: zero `capabilities.name` checks
- [ ] grep `transcript_reader.py`: zero `claude_task_state` imports
- [ ] verify all requirements from design docs are implemented
- [ ] run full test suite: `make check`

### Task 8: [Final] Update documentation

- [ ] update `CLAUDE.md` architecture module inventory if needed
- [ ] update `.claude/rules/architecture.md` module table with `session_query.py`
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification:**

- Run the bot locally (`./scripts/restart.sh start`) and verify message routing, history display, and status updates work
- Verify Claude topic shows task list in status bubble (task-state tracking via protocol)
- Verify Codex/Gemini topics don't show task list (no-op path)
