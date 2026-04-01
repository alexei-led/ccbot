# Modularity Review

**Scope**: Entire ccgram-swarm codebase — `src/ccgram/`, `src/ccgram/handlers/`, `src/ccgram/providers/`, `src/ccgram/llm/`, `src/ccgram/whisper/`
**Date**: 2026-04-01

## Executive Summary

ccgram is a Telegram-to-tmux bridge that enables remote monitoring and control of AI coding agent CLI processes (Claude Code, Codex, Gemini, Shell). The codebase has gone through four rounds of modularity improvement — most recently decomposing a `SessionManager` god object and extracting dedicated modules for window state, topic lifecycle, and inter-agent messaging. The overall architecture is healthy: the providers abstraction is clean, the messaging subsystem is well-bounded, and the polling strategy layer is focused. Four remaining imbalances are identified, all within the `bot.py` / `handlers/` area — the highest-[volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) surface of the codebase. The most important finding is that `bot.py` has accumulated substantial business logic that belongs in handler modules, coupling wiring concerns with domain rules and slowing down feature work.

## Coupling Overview Table

| Integration                                                      | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                      | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `bot.py` → `session_manager` / `thread_router` / `tmux_manager`  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                    | Low                                                                     | High                                                                        | ⚠️ No                                                          |
| `handlers/*` (22 files) → `SessionManager`                       | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                    | Low                                                                     | Moderate–High                                                               | ⚠️ No                                                          |
| `message_queue.py` + `polling_coordinator.py` → `hook_events.py` | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                         | Low                                                                     | Low                                                                         | ✅ Yes (smell)                                                 |
| `polling_coordinator.py` → `recovery_callbacks.py`               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                    | Low                                                                     | High                                                                        | ⚠️ No                                                          |
| `providers/*` → `handlers/*`                                     | None                                                                                                     | —                                                                       | —                                                                           | ✅ Clean                                                       |
| `msg_broker.py` → `mailbox.py` / `TmuxManager`                   | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (TYPE_CHECKING only) | Low                                                                     | Low                                                                         | ✅ Clean                                                       |

---

## Issue: bot.py doubles as composition root and domain orchestrator

**Integration**: `bot.py` → `session_manager` / `thread_router` / `tmux_manager`
**Severity**: Significant

### Knowledge Leakage

`bot.py` is the application's composition root — it registers PTB handlers, starts the session monitor, wires the poll loop, and performs startup tasks. But it has also accumulated substantive domain logic. `handle_new_message` (~110 lines) implements the complete inbound message routing pipeline inline: notification mode filtering with `_ERROR_KEYWORDS_RE`, interactive mode transitions (`set_interactive_mode` / `clear_interactive_mode`), async queue flush with `asyncio.sleep(0.3)`, and read-offset tracking via `user_preferences.update_user_window_offset`. The teardown sequence (`clear_topic_state` + `thread_router.unbind_thread`) is duplicated verbatim in both `topic_closed_handler` and `unbind_command`. The `topic_edited_handler` contains a five-step rename pipeline (strip emoji → compare → rename tmux window → `session_manager.set_display_name` → `update_stored_topic_name`) that belongs in `topic_orchestration.py`.

`bot.py` simultaneously holds two distinct concerns: _which handlers are registered_ (wiring) and _how messages are dispatched and processed_ (domain). Changes to either concern touch the same file.

### Complexity Impact

Every time notification filtering logic changes — a new mode, a new keyword pattern, a new provider behaviour — a developer must navigate bot.py, mentally separate domain logic from PTB registration boilerplate, and locate the edit point. Because `handle_new_message` is ~110 lines (longer than most dedicated handler modules it calls), it exceeds the 4±1 units of working memory needed to hold its state machine in mind. The teardown duplication means that changing "what happens when a topic closes" requires finding and updating two independent code paths with no static guard against divergence.

### Cascading Changes

- Adding a new notification mode → changes `session_manager`, `window_state_store`, _and_ `bot.py::handle_new_message`'s filtering logic
- Changing the topic-close teardown order → must update both `topic_closed_handler` and `unbind_command`
- Adding a new PTB command → requires reading all of bot.py to understand wiring pattern and avoid conflicts with inline logic
- Changing interactive mode transition timing → buried in `handle_new_message` alongside unrelated offset-tracking code

### Recommended Improvement

Extract `handle_new_message` into `handlers/message_dispatcher.py`. Consolidate the teardown sequence into a single `teardown_topic(window_id, thread_id, user_id, bot)` function in `handlers/topic_orchestration.py`, called from both `topic_closed_handler` and `unbind_command`. Move the rename pipeline from `topic_edited_handler` into `handlers/topic_orchestration.py`.

The trade-off is adding one new module and new imports in bot.py. The benefit is that bot.py becomes a pure wiring file — short enough to read in full in one sitting — and domain rule changes no longer require touching the composition root.

---

## Issue: SessionManager as a 34-method universal façade

**Integration**: `handlers/*` (22 files) → `session.py::SessionManager`
**Severity**: Significant

### Knowledge Leakage

After the fourth modularity refactoring, `SessionManager` successfully extracted its underlying data to dedicated sub-objects: `thread_router` (routing), `window_store` (window state), `user_preferences` (read offsets), `session_resolver` (Claude session files), `state_persistence` (JSON I/O). However, `SessionManager` retained the façade role, exposing 34 public methods spanning nine responsibility areas: window state CRUD, notification modes, batch modes, approval modes, session map sync, state audit, display name management (delegated to `thread_router`), session resolution (delegated to `session_resolver`), and mailbox pruning.

Any handler that needs any one of these capabilities imports `session_manager`. A handler that only calls `get_notification_mode` is still statically coupled to the full 34-method surface. The backward-compat property pass-throughs (`thread_bindings`, `group_chat_ids`, `window_display_names`) actively discourage handlers from importing `thread_router` directly, even though `thread_router` holds the authoritative data.

### Complexity Impact

22 of 37 handler files import `session_manager`. The effective blast radius of any interface change — a renamed method, a changed signature — is up to 22 files. Developers tracing a handler's behaviour must track which of 34 methods it uses and what each delegates to, adding one indirection hop without reducing the caller's need to understand the underlying concept. The nine responsibility areas mean low cohesion: reading `prune_stale_state` requires simultaneously holding window state, mailbox pruning, session map, and offset concepts in mind.

### Cascading Changes

- Adding a new window mode → new method on SessionManager, and potentially new imports in all affected handlers
- Renaming any SessionManager method → up to 22 edit points
- Refactoring notification mode storage → must audit all 22 handler files for call sites
- Extracting SessionManager to an injected dependency → 22 handler files need constructor/parameter changes

### Recommended Improvement

Remove the backward-compat property pass-throughs and allow handlers to import `thread_router` and `window_store` directly for read-only queries. Reserve `session_manager` for operations that span multiple sub-objects: initial thread binding, full teardown, state audit, and session map sync. This reduces the session_manager surface to roughly 15 methods and shrinks its import count from 22 toward only the handlers that need cross-cutting writes.

The trade-off is a short migration: handlers currently using `session_manager.thread_bindings` or `session_manager.window_display_names` must be updated to use `thread_router` directly. The benefit is that read-only queries go directly to the authoritative source, and interface changes to notification or batch modes only affect the handlers that actually use those modes.

---

## Issue: Subagent formatting utilities misplaced in hook_events.py

**Integration**: `message_queue.py` + `polling_coordinator.py` → `hook_events.py`
**Severity**: Minor

### Knowledge Leakage

`hook_events.py` is the handler for Claude Code hook events (Stop, StopFailure, SessionEnd, Notification, SubagentStart, SubagentStop, TeammateIdle, TaskCompleted). It owns the boundary between external hook events and internal handler state. But it also defines `build_subagent_label()` and `get_subagent_names()` — pure formatting utilities that read `claude_task_state` and produce display strings. These functions have no dependency on hook-event dispatching; they are consumed by `message_queue.py` (status label assembly) and `polling_coordinator.py` (subagent count display).

Both consumers import these functions using deferred inside-function imports:

```python
# message_queue.py lines 472, 508
from .hook_events import build_subagent_label, get_subagent_names
```

The deferred pattern is the symptom: `hook_events` imports from `message_queue` at module level (for `enqueue_status_update`), and `message_queue` imports from `hook_events` inside functions (for label building) — a logical cycle resolved only at runtime.

### Complexity Impact

Deferred imports are invisible to static analysis and IDE navigation. A developer reading `message_queue.py` sees no import from `hook_events` at the top of the file; the dependency is hidden at line 472. The cycle means that converting a deferred import to a module-level import will cause an `ImportError` at startup — a failure mode that is easy to trigger accidentally and non-obvious to diagnose.

### Cascading Changes

- Changing `build_subagent_label` output format → must find it inside `hook_events`, understand why it lives there, and trace callers through deferred imports
- Adding a third consumer of subagent label building → must use a deferred import or fully resolve the cycle first
- Extracting `hook_events.py` for isolated testing → cycle risk must be analysed before any import is moved to module level

### Recommended Improvement

Extract `build_subagent_label`, `get_subagent_names`, and any formatting helpers they depend on into `handlers/subagent_format.py`. This module has no dependencies on the rest of handlers/ — it only reads from `claude_task_state` in core. Both `hook_events.py` and `message_queue.py`/`polling_coordinator.py` import from `subagent_format.py` at module level. No deferred imports. No cycle.

The trade-off is one additional module. The benefit is an acyclic dependency graph, top-level imports throughout, and a self-describing home for subagent formatting logic.

---

## Issue: Polling infrastructure knows about recovery keyboard layout

**Integration**: `polling_coordinator.py` → `recovery_callbacks.py`
**Severity**: Minor

### Knowledge Leakage

`polling_coordinator.py` runs the 1-second background status poll for all active windows. When it detects a dead tmux window mid-poll, it directly calls `recovery_callbacks.build_recovery_keyboard(window_id, bot)` to construct and dispatch a Telegram inline keyboard to the affected user. The polling loop (infrastructure) encodes knowledge of which keyboard builder to invoke and what parameters it takes (presentation). `polling_coordinator` knows that a dead window should produce a specific Telegram UI affordance, rather than emitting a signal and letting the presentation layer decide.

### Complexity Impact

`polling_coordinator.py` already imports 16 modules (7 core + 9 handler siblings). Each presentation concern added increases the cognitive load of reading the file and makes it harder to locate the infrastructure logic. A developer changing how dead-window recovery works must look in two files: `recovery_callbacks.py` (keyboard builder) and `polling_coordinator.py` (the call site that decided to show the keyboard). The two halves of "what happens when a window dies" are separated across an infrastructure/presentation boundary.

### Cascading Changes

- Adding a provider-specific recovery action (e.g., "Restart Codex") → changes `recovery_callbacks.build_recovery_keyboard` AND the call site in `polling_coordinator`
- Changing when the recovery keyboard is shown (timing, retries) → must change `polling_coordinator`'s dead-window branch
- Making recovery keyboard dispatch asynchronous or deferred → must refactor the polling coordinator call site

### Recommended Improvement

Introduce a `show_dead_window_recovery(window_id, bot, user_id, thread_id)` function in `handlers/topic_orchestration.py` or `recovery_callbacks.py` itself. `polling_coordinator` calls this single function — it no longer imports `build_recovery_keyboard`. The function encapsulates both which keyboard to build and how to send it, keeping the presentation decision inside the presentation layer.

The trade-off is a thin delegation wrapper. The benefit is that `polling_coordinator`'s imports no longer include keyboard builders, and the full dead-window recovery flow is readable in one place.

---

## What Is Working Well

The following integrations are well-[balanced](https://coupling.dev/posts/core-concepts/balance/) and worth preserving:

- **`providers/` abstraction**: Protocol-based with clean capability gating via `ProviderCapabilities`. Handlers call `get_provider_for_window(window_id)` — zero implementation detail from Claude, Codex, Gemini, or Shell leaks into the handler layer.
- **Inter-agent messaging subsystem**: `msg_broker.py` has zero runtime core imports (`Mailbox` and `TmuxManager` are `TYPE_CHECKING`-only). `msg_delivery.py` has one core dependency. The four `msg_*` modules are cleanly decoupled from each other with no cross-imports.
- **`polling_strategies.py`**: Only two core dependencies (`providers.base`, `topic_state_registry`). No sibling handler imports. Strategy objects own per-window poll state without routing it through `session_manager`.
- **`topic_state_registry.py`**: Correctly placed in core with zero UI dependencies. Self-registering cleanup callbacks implement a clean observer pattern.
- **`llm/` and `whisper/` subpackages**: Well-bounded with protocol-based interfaces and factory functions. Zero coupling to the handler layer.
- **`thread_router` and `window_state_store`**: Clean extractions from the prior refactoring. The data lives in the right place; the remaining issue (Finding 2) is that the SessionManager façade has not yet been trimmed to reflect it.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
