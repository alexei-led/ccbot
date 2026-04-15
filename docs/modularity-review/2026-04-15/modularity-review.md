# Modularity Review

**Scope**: Entire codebase — all components (handlers, providers, core modules, LLM, messaging)
**Date**: 2026-04-15

---

## Executive Summary

ccgram is a Telegram-to-tmux bridge that lets users control AI coding agent CLIs (Claude Code, Codex, Gemini, Shell) from Telegram Forum topics. Each topic binds to one tmux window; the bot routes messages, captures terminal output, and surfaces agent status in real time. The overall modularity status **needs attention**: the infrastructure and provider abstraction layers are well-designed and exhibit low [coupling](https://coupling.dev/posts/core-concepts/coupling/), but the session management and polling subsystems have evolved into high-complexity coordination hubs whose coupling surface creates the two confirmed pain points — cascading changes on any `session_manager` touch, and fragility in the polling cycle. One confirmed architectural layer violation (provider layer reaching up to session layer) and three modules sharing write authority over the same mutable singleton represent the most urgent issues to address.

### Scores

| Dimension                                                                                           | Score      | Notes                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Cohesion**                                                                                        | 5 / 10     | `session_manager` (46 methods, 804 lines) and `session_monitor.py` (5 responsibilities, 891 lines) are low-cohesion hubs. `window_tick.py` 30-import fan-out is a secondary symptom.                                                              |
| **[Integration Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)** | 6 / 10     | Most handler→session coupling is functional (appropriate for same-service). Infrastructure singletons (config, thread_router, state_persistence) exhibit clean contract coupling. The layer violation in providers is the critical outlier.       |
| **Layer Integrity**                                                                                 | 5 / 10     | One confirmed inversion (`providers/__init__` → `session_manager`); one directional mismatch (`window_state_store` → `providers.registry`). The `WindowView` projection exists as a decoupling mechanism but is adopted in only 8% of call sites. |
| **State Encapsulation**                                                                             | 4 / 10     | Three module-level singletons with distributed write authority (`claude_task_state`). `session_manager` accessed directly at 103 call sites across 27 handler files rather than through a bounded interface.                                      |
| **[Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/)-adjusted coupling**   | 6 / 10     | High-volatility core subsystems (hook events, polling) have tolerable coupling individually; the god object accumulates the cost. Infrastructure and LLM layers are well-isolated at appropriate volatility levels.                               |
| **[Modularity](https://coupling.dev/posts/core-concepts/modularity/) overall**                      | **5 / 10** | Structurally sound at the macro level (handlers / providers / core / infra separation). Critical coupling debt concentrated in session management and the polling loop — the two areas confirmed as active pain points.                           |

---

## Coupling Overview

| Integration                                                                 | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)               | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)               |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 27 handler files → `session_manager` (103 call sites)                       | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | Low (same service)                                                      | **High**                                                                    | ⚠ Technically balanced per model; low cohesion drives unbounded accumulation |
| `providers/__init__` → `session.session_manager` (lazy)                     | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | **High** (wrong layer direction)                                        | **High**                                                                    | ❌ Unbalanced — layer violation                                              |
| `window_state_store` → `providers.registry`                                 | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)               | Low (same service)                                                      | Low                                                                         | ⚠ Direction inverted; tolerable due to low volatility                        |
| `session_monitor` (file watcher + 4 other roles)                            | Internal — low-cohesion module                                                                    | —                                                                       | **High**                                                                    | ❌ High-volatility responsibilities co-located without separation            |
| `hook_events` → 10+ sibling handlers (lazy imports)                         | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | Low (same layer)                                                        | **High**                                                                    | ✅ Balanced; lazy imports mask true fan-out                                  |
| `claude_task_state` ← `session_monitor` + `hook_events` + `topic_lifecycle` | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (3 writers) | Low                                                                     | **High**                                                                    | ❌ Unbalanced — shared authority, no coordinator                             |
| `window_tick` → 30 imports                                                  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | Low                                                                     | **High**                                                                    | ⚠ Balanced individually; excessive fan-out signals low cohesion              |
| `hook_events` → `llm.summarizer`                                            | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | Low (same service)                                                      | High                                                                        | ✅ Balanced; synchronous concern noted separately                            |
| `config` → (nothing internal)                                               | —                                                                                                 | —                                                                       | Low                                                                         | ✅ Exemplary                                                                 |
| `providers/base` + `providers/registry` → (nothing internal)                | —                                                                                                 | —                                                                       | Medium                                                                      | ✅ Clean foundation                                                          |
| `status_bubble` ← `message_queue` + `tool_batch`                            | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | Low                                                                     | High                                                                        | ⚠ Triangular dependency; `tool_batch` → `status_bubble` unplanned            |

---

<div class="issue">

## Issue 1: Provider Layer Reaches Up to Session Layer

**Integration**: `providers/__init__.get_provider_for_window()` → `session.session_manager`
**Severity**: Critical

### Knowledge Leakage

`get_provider_for_window(window_id)` — the canonical provider resolution function — lazily imports `session_manager` from `session.py` and reads `session_manager.window_states[window_id].provider_name` to decide which provider to instantiate. This means the [provider layer](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (infrastructure, stable) has [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to the session layer (business state, volatile). The provider layer now knows about: the `WindowState` data structure, the `window_states` dict key format, and the meaning of `provider_name` as a session concept. These are session-layer implementation details leaking downward into a layer that should only know about its own provider protocol.

### Complexity Impact

This creates a latent circular dependency held apart only by Python's lazy import mechanism. `session.py` imports `window_state_store`, which imports `providers.registry`. `providers/__init__` imports `session_manager`. The cycle exists at runtime; a future eager import — or any module restructuring — will surface it as an `ImportError`. Developers working on either `session.py` or `providers/` cannot reason about their module boundary in isolation: the provider resolution function's behavior depends on session state that is mutated from 27 other places.

### Cascading Changes

- Adding a new per-window state field to `WindowState` for provider selection (e.g., model variant, provider config override) requires editing both `session.py` and `providers/__init__`, which live at different conceptual layers.
- Refactoring provider instantiation (e.g., lazy singletons → per-call instances) must account for session state read patterns.
- Testing `get_provider_for_window()` in isolation requires constructing a real or mocked `session_manager` — the unit test boundary is broken.

### Recommended Improvement

Invert the dependency: pass `provider_name` into the resolution function as an explicit parameter instead of having it read from `session_manager`. The call sites in handlers already know the window context; they can pass the provider name obtained from `session_manager.get_window_provider(window_id)` directly:

```python
# Before (providers/__init__.py reading session layer)
def get_provider_for_window(window_id: str) -> AgentProvider:
    from ccgram.session import session_manager  # layer violation
    provider_name = session_manager.window_states[window_id].provider_name
    return registry.get(provider_name)

# After (caller supplies provider_name — session layer stays at the call site)
def get_provider(provider_name: str | None) -> AgentProvider:
    return registry.get(provider_name or config.default_provider)
```

The trade-off is minor: call sites become `get_provider(session_manager.get_window_provider(window_id))` instead of `get_provider_for_window(window_id)`. This makes the session dependency visible at each call site — which is the correct place for it, since the call site is already in the handler layer where `session_manager` belongs. It also makes `providers/__init__` independently testable.

</div>

<div class="issue">

## Issue 2: `session_manager` as an Unbounded God Object

**Integration**: 27 handler files → `session.session_manager` (103 call sites, 46 methods)
**Severity**: Critical

### Knowledge Leakage

`session_manager` (804 lines, 46 public methods) accumulates every per-window and per-user state operation: approval mode, notification mode, batch mode, display names, thread bindings, session map sync, history retrieval, state auditing, orphan pruning, group ID management. Every handler that needs anything about a window calls `session_manager` directly — there is no interface boundary, no projection, and no ownership model. The 103 call sites share knowledge of the full method surface across 27 files. A `WindowView` frozen projection was introduced as a decoupling mechanism but adopted in only 6 of 77 eligible call sites (8%).

### Complexity Impact

[Functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) at this scale exceeds the [cognitive capacity](https://coupling.dev/posts/core-concepts/complexity/) a developer can hold in working memory. When modifying `session_manager`, the developer must mentally trace 27 import sites and 103 call patterns to understand impact. Conversely, when modifying a handler, the developer must know which of the 46 `session_manager` methods are appropriate for the operation — there is no scoped interface to constrain the choice. This is confirmed as an active pain point: any `session_manager` touch cascades through many handler files.

### Cascading Changes

- Renaming or splitting any `session_manager` method (e.g., extracting `get_window_display_name` from the combined `window_display_names` dict access) requires updating all 103 call sites.
- Adding a new per-window state field — inevitable as new provider capabilities are added — means adding it to `WindowState`, adding a getter/setter to `WindowStateStore`, adding a delegation method to `session_manager`, and updating every handler that needs the new field.
- The `WindowState` dataclass field names are the true shared data model: 27 files depend on them by name. A field rename is a 27-file change.

### Recommended Improvement

Apply progressive encapsulation in two phases, without a big-bang rewrite:

**Phase 1 — increase `WindowView` adoption.** The `WindowView` frozen projection already exists. Enforce its use in read-only handlers: audit the 71 call sites that access `session_manager.get_window_state()` instead of `session_manager.view_window()`, and migrate read-only access. This constrains the shared knowledge surface to `WindowView`'s 6 fields for most handlers.

**Phase 2 — introduce scoped facades.** Group the 46 methods by domain:

- `WindowStateManager` — approval/notification/batch mode, provider assignment
- `SessionBindingManager` — thread bindings, window display names, session map sync
- `HistoryManager` — per-window message history

Each facade exposes a narrow, named interface. `bot.py` wires them together; handlers import only the facade they need. The god object becomes a coordinator of typed sub-managers rather than a single unbounded surface.

The trade-off: Phase 1 is low-risk and can be done incrementally per-handler. Phase 2 requires a cohesive refactor of `session.py` and `bot.py` wiring. Both phases reduce the blast radius of future changes to the session layer significantly.

</div>

<div class="issue">

## Issue 3: `session_monitor.py` — Five Responsibilities in One Module

**Integration**: `session_monitor` (internal low-cohesion) — file watching + hook event parsing + session mapping + idle timing + window lifecycle detection
**Severity**: Significant

### Knowledge Leakage

At 891 lines, `session_monitor.py` is the largest file in the project and conflates five distinct responsibilities:

1. **File watching** — polling JSONL transcript files for new lines (byte-offset tracking)
2. **Hook event parsing** — reading `events.jsonl` and deserializing `HookEvent` objects
3. **Session map management** — reading `session_map.json` and reconciling window state
4. **Idle timer management** — tracking per-session inactivity and emitting idle events
5. **Window lifecycle detection** — detecting new windows, replaced sessions, deleted windows

Each responsibility leaks its internals into the others through shared instance variables (`self._tracked_sessions`, `self._last_mtime`, `self._idle_timers`), making it impossible to reason about or test them independently. Changes to hook event parsing affect the idle timer cadence because they share the same poll loop.

### Complexity Impact

Because the file watcher, event parser, and lifecycle detector are co-located, [accidental volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) accumulates: a change to support a new hook event type (e.g., adding `TeammateIdle` handling) requires navigating 891 lines and understanding how idle timers interact with the event dispatch path. The module also acts as a second cleanup controller alongside `hook_events.py` and `topic_lifecycle.py` — three modules share write authority over `claude_task_state` with no single coordinator, creating a distributed state management problem.

### Cascading Changes

- Adding a new Claude Code hook event type requires editing `session_monitor.py` (to parse the new event from `events.jsonl`) and `hook_events.py` (to dispatch it) — split responsibility across two files.
- The idle timer logic is interleaved with the transcript-reading loop. Changing the poll interval or the idle threshold requires understanding both systems simultaneously.
- The three-writer pattern on `claude_task_state` means any change to task state lifecycle must be traced through three files: `session_monitor.py`, `hook_events.py` (`SessionEnd`), and `topic_lifecycle.py`.

### Recommended Improvement

Extract the five responsibilities into three focused classes/modules, keeping `session_monitor.py` as a thin coordinator:

1. **`event_reader.py`** — reads `events.jsonl` incrementally by byte offset, deserializes `HookEvent` objects, emits raw events to a callback. Pure I/O; no state.
2. **`session_lifecycle.py`** — reconciles `session_map.json` against live tmux windows; detects new/replaced/deleted sessions; emits lifecycle events. Owns the single authoritative cleanup path for `claude_task_state`.
3. **`idle_tracker.py`** — per-session idle timer with configurable threshold; receives "activity" signals from event_reader; emits idle callbacks. No I/O.
4. **`session_monitor.py`** (coordinator, ~100 lines) — wires the three above, owns the poll loop, exposes the existing `NewMessage` / `NewWindowEvent` / `HookEvent` callback API unchanged.

This refactor eliminates the three-writer problem: `session_lifecycle.py` becomes the single authority for `claude_task_state` cleanup, with `hook_events.py` and `topic_lifecycle.py` delegating to it.

</div>

<div class="issue">

## Issue 4: `window_tick.py` as Secondary Coordination Hub

**Integration**: `window_tick` → 30 imports (session, providers, session_monitor, message_queue, message_sender, polling_strategies, interactive_ui, cleanup, topic_emoji, recovery_callbacks, transcript_discovery, ...)
**Severity**: Significant

### Knowledge Leakage

`window_tick.py` (535 lines) is the per-window poll cycle — conceptually a single function that decides what to do for one window on each tick. In practice it has become a coordination hub that touches every subsystem: it reads terminal state via pyte/tmux, checks session monitor activity timestamps via `get_active_monitor()`, dispatches interactive UI prompts, queues status updates, updates topic emoji, triggers transcript discovery, and builds recovery keyboards. Each of these is a separate concern imported as a direct dependency. The module knows the internal timing model of `session_monitor` (accessing `get_last_activity()` on the singleton) — a cross-subsystem runtime coupling.

### Complexity Impact

With 30 imports, any change to how any of those 30 dependencies behaves — a new argument, a renamed function, a changed return type — has a chance of requiring a `window_tick.py` edit. Because `window_tick` is on the hot path (runs every 1 second per active window), it is also the most common site for performance regressions. Adding a new status indicator or new provider behavior requires understanding the full 30-dependency graph to know where to insert the new logic without breaking existing paths.

### Cascading Changes

- Changing the `polling_strategies` API (e.g., changing `TerminalPollState` to a dataclass instead of a class) requires updating `window_tick`'s 7 call sites to those strategies.
- Adding multi-pane support for a new provider requires editing `window_tick` to know about the new pane scanning pattern — even though pane scanning belongs to the provider abstraction.
- The `get_active_monitor().get_last_activity(session_id)` call couples the tick cycle to `session_monitor`'s internal data model. If the monitor's tracking changes (e.g., tracking activity per-pane rather than per-session), `window_tick` must change too.

### Recommended Improvement

Decompose the tick into a coordinator with scoped delegates:

1. **Terminal state capture** — already partially in `polling_strategies.py`. Complete the extraction: `TerminalStateCapture` returns a snapshot (clean lines, spinner state, interactive prompt detected). No decisions, just observation.
2. **Status decision** — given current snapshot and last-known state, decide: emit status update? trigger idle transition? open recovery keyboard? This is pure logic — no I/O — and can be unit-tested without mocks.
3. **Effect dispatch** — apply the decision: enqueue the right message, call the right UI function. This thin layer is the only one that needs 30 imports.

This pattern (observe → decide → act) reduces `window_tick`'s I/O surface and makes the decision logic testable. The `get_active_monitor()` coupling can be resolved by passing activity timestamps into the tick function as a parameter — `polling_coordinator.py` already polls the monitor and can supply the value.

</div>

<div class="issue">

## Issue 5: `window_state_store` Depends on `providers.registry`

**Integration**: `window_state_store.set_window_provider()` → `providers.registry.is_known()`
**Severity**: Minor

### Knowledge Leakage

`WindowStateStore` imports `from .providers import registry` to validate `provider_name` strings before persisting them. The state persistence layer exercises domain validation logic from the provider registry: if the registry doesn't know a provider name, the setter refuses the value. This couples a persistence concern (write a validated string to a dict and save) to a business concern (what provider names are valid). The direction is wrong: the provider registry should not be a dependency of the state store.

### Complexity Impact

Adding a new provider requires: registering it in `providers/registry.py`, and ensuring the registry import in `window_state_store.py` resolves correctly. While the coupling is low-strength ([contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) — only `is_known()` is called), the architectural direction creates a latent circular dependency path: `session.py` → `window_state_store` → `providers.registry` → `providers.__init__` → (lazy) `session.session_manager`. Any eager resolution along this chain surfaces as an import cycle.

### Cascading Changes

This issue is low-[volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) in practice — provider names rarely change. The risk is structural: the coupling makes the import graph harder to reason about and contributes to the circular dependency path described in Issue 1.

### Recommended Improvement

Remove the provider registry dependency from `window_state_store`. Validate `provider_name` at the call site in `session.py` (the layer that already imports both `window_state_store` and `providers`), or use a simple allowlist of known provider name strings passed in as a constructor argument to `WindowStateStore`. This keeps the state layer unaware of the provider domain:

```python
# session.py constructs WindowStateStore with known provider names
store = WindowStateStore(known_providers=set(registry.list_names()))

# window_state_store.py — no providers import needed
def set_window_provider(self, window_id: str, provider_name: str | None) -> None:
    if provider_name and provider_name not in self._known_providers:
        raise ValueError(f"Unknown provider: {provider_name}")
    ...
```

The trade-off is minimal: the validation is pushed one layer up where both dependencies already exist, and the state store becomes independently instantiable for testing.

</div>

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
