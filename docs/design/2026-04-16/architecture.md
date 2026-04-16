# Architecture Overview

## Functional Requirements Summary

This design addresses two significant modularity imbalances identified in the 2026-04-16 modularity review:

1. **SessionManager Low Cohesion** — 39-method facade with 15 pure delegation methods, imported by 17+ modules as a one-stop shop. Goal: reduce to startup orchestration + write coordination only.
2. **Provider Abstraction Leaks** — `transcript_reader.py` branches on `provider.capabilities.name == "claude"` for task-state tracking, embedding provider-specific knowledge in generic code. Goal: close the leak via protocol extension.

## Module Map

| Module                        | Description                                                                                                                                                           |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `session.py` (SessionManager) | **Modified** — startup orchestration, write coordination, cross-cutting audit. 15 pure delegation methods removed.                                                    |
| `window_query.py`             | **Existing** — read-only free functions for window state. No changes, but more callers migrate to it.                                                                 |
| `session_query.py`            | **New** — read-only free functions for session resolution (3 functions wrapping `session_resolver`).                                                                  |
| `providers/base.py`           | **Modified** — `ProviderCapabilities` gains `supports_task_tracking: bool`. `AgentProvider` gains `seed_task_state()` and `apply_task_entries()` with default no-ops. |
| `providers/claude.py`         | **Modified** — implements `seed_task_state()` and `apply_task_entries()`, delegating to `claude_task_state`.                                                          |
| `transcript_reader.py`        | **Modified** — replaces `name == "claude"` checks with `supports_task_tracking` flag + protocol method calls. Removes `claude_task_state` import.                     |

## How the Modules Work Together

### Flow 1: Handler reads window state (after dissolution)

```
handler module
  -> window_query.get_window_provider(wid)    # read-only, no SessionManager
  -> window_store.window_states[wid]          # direct dict access inside window_query
```

Previously: `handler -> session_manager.get_window_provider(wid) -> window_store`. The middle hop is removed.

### Flow 2: Handler reads session/message history (after dissolution)

```
message_routing.py / history.py
  -> session_query.resolve_session_for_window(wid)
  -> session_resolver.resolve_session_for_window(wid)   # lazy import inside session_query
```

Previously: `handler -> session_manager.resolve_session_for_window(wid) -> session_resolver`. The SessionManager hop is removed.

### Flow 3: Transcript reader processes entries (after provider fix)

```
transcript_reader.py
  -> if provider.capabilities.supports_task_tracking:        # capability flag, not name check
  ->     await provider.seed_task_state(wid, sid, path)      # protocol method
  ->     provider.apply_task_entries(wid, sid, entries)       # protocol method

ClaudeProvider.seed_task_state()
  -> claude_task_state.seed_from_transcript(wid, sid, path)  # Claude-specific, encapsulated

CodexProvider / GeminiProvider / ShellProvider
  -> no-op (default implementation)
```

Previously: `transcript_reader` imported `claude_task_state` directly and checked `name == "claude"`.

### Flow 4: SessionManager write operations (unchanged)

```
handler
  -> session_manager.set_window_provider(wid, "codex")
  -> window_store.set_window_provider(wid, "codex")    # delegates
  -> session_manager._save_state()                      # triggers persistence
```

Write operations stay on SessionManager because they must trigger `_save_state` across the unified persistence blob.

## Coupling Assessment

| Integration                             | Strength                            | Distance           | Volatility         | Balanced?               | Decision                               |
| --------------------------------------- | ----------------------------------- | ------------------ | ------------------ | ----------------------- | -------------------------------------- |
| Handlers -> `window_query`              | Contract (read-only functions)      | Low (same package) | Medium-high (core) | Yes                     | Extend existing pattern                |
| Handlers -> `session_query`             | Contract (read-only functions)      | Low (same package) | Medium (core)      | Yes                     | New module, same pattern               |
| Handlers -> `session_map_sync` (direct) | Model (shared session map model)    | Low (same package) | Medium (core)      | Yes                     | Callers import directly                |
| `transcript_reader` -> `AgentProvider`  | Contract (protocol methods)         | Low (same package) | Medium-high (core) | Yes                     | Closes leak                            |
| `ClaudeProvider` -> `claude_task_state` | Functional (knows task-state model) | Low (same package) | Low (supporting)   | Yes (high cohesion)     | Encapsulated within provider           |
| Shell handlers -> `providers.shell`     | Intrusive (bypasses protocol)       | Low (adjacent)     | Low (supporting)   | Yes (by low volatility) | Accepted                               |
| Handlers -> `SessionManager` (writes)   | Functional (mutation + persistence) | Low (same package) | Medium-high (core) | Yes (high cohesion)     | Essential — SM owns write coordination |

## Design Decisions and Trade-offs

### Decision 1: Delete dead delegations rather than deprecate

**Chosen**: Delete the 4 SessionManager methods with zero external callers immediately.
**Alternative**: Deprecate with warnings, remove later.
**Rationale**: Zero external callers means zero migration cost. Deprecation adds complexity for no benefit. The methods exist only because SessionManager was historically the entry point — callers have already migrated organically.

### Decision 2: Create `session_query.py` rather than exposing `session_resolver` directly

**Chosen**: Thin wrapper module (`session_query.py`) with 3 free functions.
**Alternative**: Have callers import `session_resolver` directly.
**Rationale**: `session_resolver` uses a lazy-import singleton pattern that callers shouldn't need to know about. `session_query` encapsulates this, matching the established `window_query` pattern. Consistency across the codebase reduces cognitive load.
**Trade-off**: One more module to maintain. But it's ~20 lines.

### Decision 3: Protocol methods with default no-ops rather than capability-gated abstract methods

**Chosen**: `seed_task_state` and `apply_task_entries` have default no-op implementations on the Protocol.
**Alternative**: Make them abstract; require all providers to implement.
**Rationale**: Only Claude has task tracking today. Forcing 3 other providers to write explicit no-ops adds noise. The existing `scrape_current_mode` method already uses this default-implementation pattern, so it's consistent.
**Trade-off**: A provider that should implement these methods but forgets will silently no-op. Mitigated by `supports_task_tracking` flag — if a provider sets the flag, it's signaling intent and will notice the missing implementation during testing.

### Decision 4: Accept shell handler abstraction leaks

**Chosen**: Shell handlers continue importing `match_prompt`, `KNOWN_SHELLS`, etc. from `providers.shell`.
**Alternative**: Move shell utilities to handlers or add to protocol.
**Rationale**: Shell prompt detection is a supporting subdomain with low volatility. The balance rule (`BALANCE = NOT VOLATILITY`) is satisfied. Moving utilities would split the shell provider's cohesion. Adding to the protocol would pollute it with shell-specific concepts.
**Trade-off**: Adding a new shell-like provider (unlikely) would need to replicate these utilities or refactor at that time. YAGNI applies.

### Decision 5: `session_map_sync` callers import directly rather than through a query module

**Chosen**: Lifecycle handlers (`directory_callbacks`, `transcript_discovery`, `sync_command`, `session_monitor`) import `session_map_sync` directly.
**Alternative**: Create `session_map_query.py`.
**Rationale**: Session map operations are mostly writes (`register_hookless_session`, `write_hookless_session_map`, `load_session_map`). Only `wait_for_session_map_entry` is a read/poll, and it's called from 4 specific lifecycle points — not broadly. A query module would have low fan-in and add a layer for no coupling reduction.

## Unresolved Risks

### Minor: `window_states` property still exposed

`SessionManager.window_states` is a property exposing `window_store.window_states` dict. Some callers (e.g., `periodic_tasks.py`) iterate it directly. This is model coupling — callers know the dict structure. Acceptable because it's low distance and the dict structure is stable, but it leaks `WindowState` internals.

### Minor: `thread_bindings` property still exposed

`SessionManager.thread_bindings` is used by `polling_coordinator.py` for iterating all bound windows. Same model coupling pattern. Could be replaced with an iterator method but the current usage is simple and stable.

### Minor: Interactive UI implicit state protocol

The 5-caller coordination around `_interactive_msgs` / `_interactive_mode` / `_send_cooldowns` in `interactive_ui.py` remains undocumented. This is orthogonal to the two issues addressed here but was flagged in the review. Recommendation: document the state machine or consolidate clear functions in a future pass.
