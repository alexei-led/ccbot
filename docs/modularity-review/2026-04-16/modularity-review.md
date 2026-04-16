# Modularity Review

**Scope**: Entire ccgram codebase — all 120 Python source files across bot, handlers, session monitoring, providers, tmux infrastructure, and CLI  
**Date**: 2026-04-16

## Executive Summary

ccgram is a single-process Python bot (~47k lines) that routes Telegram messages to AI coding agent CLIs (Claude Code, Codex, Gemini, Shell) running in tmux panes. The codebase has undergone meaningful modularity improvements — notably, the extraction of `IdleTracker`, `SessionLifecycle`, `EventReader`, and `TranscriptReader` from a prior monolith — and the result shows good instincts: stable data contracts (`HookEvent`, `StatusUpdate`, `WindowView`), clean infrastructure boundaries at the bottom of the stack, and a working provider abstraction.

The overall modularity health is **needs attention**. The system's weakest seam is the `SessionManager` god-object: it is accessed directly by over 20 modules, many of them handler modules that sit at the presentation layer, making the session state model the hidden driver of most change costs across the codebase. Two confirmed layer violations compound this — `tmux_manager` imports from the provider domain layer (inverted dependency), and command handlers reach directly into polling strategy internals to reset state — both in areas with high [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/). Four circular import cycles, currently suppressed with deferred imports, mask the true shape of the dependency graph and indicate that module boundaries do not yet match domain boundaries.

## Dimension Scores

| Dimension                                                                             | Score      | Notes                                                                                                                                                                       |
| ------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Encapsulation / Information Hiding                                                    | 4/10       | `SessionManager` internals accessed from 20+ modules; `claude_task_state` mutated from 6 sites; polling state reached by command handlers                                   |
| Cohesion                                                                              | 5/10       | Most modules focused; `command_orchestration` (683 lines), `window_tick` (610 lines), `transcript_reader` have multiple distinct concerns                                   |
| [Coupling](https://coupling.dev/posts/core-concepts/coupling/) Discipline             | 4/10       | `tmux_manager`→`providers` (infrastructure→domain); `claude.py`→`tmux_manager`; handlers→polling internals; 4+ deferred-import cycles                                       |
| Contract Stability                                                                    | 6/10       | `AgentProvider` Protocol, `WindowView`, `HookEvent`, `StatusUpdate` are solid; window-key string format implicit; protocol surface is 18 methods wide                       |
| Testability                                                                           | 5/10       | `shell_infra` and `claude.py` hardwire `tmux_manager`; `SessionManager` singleton wiring; deferred imports mask test patch targets; test-infra import in production code    |
| [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) Alignment | 4/10       | Tightest couplings concentrated in the most volatile areas; most isolated modules (`event_reader`, `IdleTracker`, `base.py`) are also the most stable — pattern is inverted |
| Module Size Distribution                                                              | 6/10       | `tmux_manager.py` (1175 lines), `session.py` (789), `transcript_parser.py` (765) are large; many small, focused modules balance the score                                   |
| Dependency Direction                                                                  | 4/10       | Infrastructure→domain, provider→infrastructure, and presentation→infrastructure-internals violations confirmed                                                              |
| **Overall**                                                                           | **4.8/10** | Functional system with solid core contracts; session-state coupling and layer violations are the primary drag                                                               |

## Coupling Overview

| Integration                                              | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)              |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 20+ modules → `SessionManager`                           | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — scope of dependents amplifies every state model change                 |
| `tmux_manager` → `providers`                             | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service, wrong layer direction                                     | High                                                                        | No — infrastructure importing domain logic                                  |
| Command handlers → `polling_strategies` internals        | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service, wrong layer direction                                     | High                                                                        | No — presentation directly mutating infrastructure state                    |
| `claude_task_state` ← 6 mutation sites                   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | High                                                                        | No — no single write authority; state consistency unenforceable             |
| Deferred-import cycles (4+)                              | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bidirectional) | Same service                                                            | High                                                                        | No — masks true dependency graph                                            |
| `shell_infra` / `claude.py` → `tmux_manager` (hardwired) | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service                                                            | Moderate                                                                    | No — providers cannot be unit-tested without tmux                           |
| `AgentProvider` Protocol (18 methods)                    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service (provider subsystem)                                       | Moderate                                                                    | Mostly — contract coupling at low distance is acceptable; surface area risk |
| `hook.py` ↔ `session_map.py` file-lock protocol          | Behavioral                                                                                            | Cross-process                                                           | Low                                                                         | Yes — low volatility makes unbalanced strength tolerable                    |
| `tool_batch` → `status_bubble` (lazy import)             | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | Same service (sibling handlers)                                         | Moderate                                                                    | Borderline — low distance mitigates; acknowledged by codebase itself        |
| `IdleTracker`, `event_reader`, `providers/base.py`       | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                   | Same service                                                            | Low/Moderate                                                                | Yes — correctly isolated; these are the design exemplars                    |

---

## Issue 1: SessionManager as a Dependency Hub

<div class="issue">

**Integration**: 20+ handler, monitor, and provider modules → `session.py:SessionManager`  
**Severity**: Significant

### Knowledge Leakage

Every module that calls `session_manager.get_notification_mode(window_id)`, `.view_window()`, `.get_window_provider()`, `.cycle_batch_mode()`, or `.resolve_session_for_window()` is acquiring [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to the session state model's internal structure. Callers know that windows have `notification_mode`, `batch_mode`, `provider_name`, `cwd`, `transcript_path`, `session_id`, and `startup_time` as first-class fields — not because a published contract declares them, but because the methods expose them directly. The `WindowView` read-only projection partially helps, but it only seals the write path, not the read path: seven handler modules still import `session_manager` directly to read state.

The `_wire_singletons()` initialization pattern leaks a further piece of hidden knowledge: every sub-singleton (`window_store`, `thread_router`, `user_preferences`, `session_map_sync`) ships with an `unwired_save` sentinel that raises `RuntimeError` if called before `SessionManager.__post_init__` runs. The correct initialization order exists only in a comment. Any new sub-singleton added to the system silently inherits this ordering constraint.

### Complexity Impact

When the session state model changes — adding a field, renaming a mode, changing how session IDs are resolved — the developer must find and update every one of the 20+ call sites. Because these call sites are spread across the handler layer, the monitoring layer, and the provider layer, no static boundary prevents a partial update. The risk is a change that is correct in `session.py` but inconsistent across callers until all are found. This is [accidental volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) amplified by breadth: the state model does not change more often, but the cost of changing it grows linearly with the number of direct dependents.

The `_wire_singletons()` ordering constraint adds a second axis of complexity: any developer who instantiates a sub-singleton in a test or CLI context without first constructing `SessionManager` will encounter a `RuntimeError` at call time, not at import time. The error surfaces far from its cause.

### Cascading Changes

- Adding a new per-window mode (e.g., `verbosity_mode`) requires: (1) a new field in `WindowState`, (2) a getter and setter in `SessionManager`, (3) updates in `window_state_store` and `session.py` serialization, and (4) additions in every handler that needs the mode — currently `hook_events`, `window_tick`, `status_bubble`, and `command_orchestration` all have independent mode-read logic.
- Changing the `window_key` string format (`"tmux_session:window_id"`) requires updating not just `session_map.py` but `hook_events.py` (which parses it with `rsplit(":", 1)`) and `window_resolver.py`.
- Adding a seventh sub-singleton to `SessionManager` requires adding another `_wire_singletons()` injection line — an invisible requirement new contributors will miss.

### Recommended Improvement

The `WindowView` projection is the right instinct — extend it. Move all per-window read paths that are currently on `session_manager` to `WindowView` so that callers never import `session_manager` directly for reads. For writes, introduce a narrow `WindowStateCommands` interface (or extend the existing `SessionManager` surface into clearly separated read and command facets). This reduces [integration strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) from functional to contract without requiring an architecture restructure.

For `_wire_singletons()`: replace the sentinel pattern with lazy property initialization on each sub-singleton. A sub-singleton that self-resolves its persistence callback on first use is simpler and imposes no ordering constraint.

The trade-off: extending `WindowView` and separating read/command facets requires touching all 20+ call sites once — a one-time cost that reduces the ongoing cost of every future state model change.

</div>

---

## Issue 2: tmux_manager Imports from the Provider Domain Layer

<div class="issue">

**Integration**: `tmux_manager.py` → `providers/__init__.py:detect_provider_from_command`  
**Severity**: Significant

### Knowledge Leakage

`tmux_manager.py` is the infrastructure layer: it owns subprocess lifecycle, terminal capture, and session/window/pane management. Its import of `detect_provider_from_command` from `providers/__init__.py` means the infrastructure layer has acquired knowledge of the domain classification logic — which process names map to which provider types. This is an [inverted dependency](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/): domain logic has leaked downward into infrastructure.

The leak is compounded by `providers/__init__.py` itself: it contains Gemini-specific branching (`if provider == "gemini"`) inside the generic `resolve_launch_command` routing function, hardcodes provider-name strings in `_YOLO_FLAGS` and `detect_provider_from_command`, and re-exports `EXPANDABLE_QUOTE_*` constants that have no semantic connection to provider routing. The module carries three different concerns in one namespace.

### Complexity Impact

Every time a new provider is added — a pattern that has already happened three times (Codex, Gemini, Shell) — `detect_provider_from_command` must be updated, and `tmux_manager.py` is a transitive consumer of that change. A developer adding a fourth CLI provider must trace the dependency chain from `providers/__init__.py` through `tmux_manager.py` to understand all affected modules. The chain is not visible from a naïve import graph because `tmux_manager` is universally perceived as infrastructure with no domain logic.

### Cascading Changes

- Adding a new provider requires updating `detect_provider_from_command` (domain), which is imported by `tmux_manager` (infrastructure), which is imported by nearly every handler and monitor module. A domain change propagates to infrastructure and then radiates outward.
- Renaming a provider (e.g., `"claude"` → `"claude-code"`) requires tracing the string literal through `tmux_manager.py`, `providers/__init__.py`, `_YOLO_FLAGS`, `session_map.py`, `hook.py`, and test fixtures — none of which are co-located.

### Recommended Improvement

Remove `detect_provider_from_command` from `tmux_manager`'s imports. The single call site that uses it in `tmux_manager.py` (inside window-creation logic, line ~1160 based on the deferred import pattern visible in the code) should receive the provider name as a parameter from its caller — which already knows the provider context. This converts functional coupling to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/): the caller passes a string, `tmux_manager` stores it, no domain classification needed inside infrastructure.

For `providers/__init__.py`: split into three files — `routing.py` (launch command resolution, detection logic), `detection.py` (pane/process/transcript detection), and retain `__init__.py` as a thin re-export facade. The Gemini-specific branch in `resolve_launch_command` should be pushed into `GeminiProvider.make_launch_args()`, where provider-specific launch logic belongs.

The trade-off: passing provider name as a parameter requires updating callers of the affected `tmux_manager` function — a small, localized change. The benefit is that `tmux_manager` becomes importable in test and tooling contexts without pulling in the entire provider graph.

</div>

---

## Issue 3: Command Handlers Directly Mutate Polling Strategy State

<div class="issue">

**Integration**: `command_orchestration.py`, `hook_events.py`, `recovery_callbacks.py` → `polling_strategies` singletons (`terminal_poll_state`, `lifecycle_strategy`, `terminal_screen_buffer`)  
**Severity**: Significant

### Knowledge Leakage

`polling_strategies.py` owns the per-window and per-topic poll-loop state machines: startup timers, dead-notification flags, probe failure counters, screen buffer caches, RC-mode detection, and typing throttle state. This is infrastructure — it serves the background polling loop. When `command_orchestration.py` calls `lifecycle_strategy.clear_probe_failures(window_id)` after forwarding a `/clear` command, and when `hook_events.py` calls `terminal_poll_state.clear_seen_status(window_id)` after a Stop event, the presentation layer is acquiring [functional knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of polling state machine internals: it knows which state cells to reset and in which combination.

The coupling is currently distributed across at least four sites: `command_orchestration` resets two different strategy objects on `/clear`, `hook_events` resets seen-status on Stop, `recovery_callbacks` clears dead-notification flags, and `window_tick` reads and writes all four strategy objects throughout its 610-line body. There is no single operation that says "reset all polling state for this window."

### Complexity Impact

The polling state machine has been refactored heavily (as evidenced by the recent extraction of `TerminalScreenBuffer`, `TerminalPollState`, `InteractiveUIStrategy`, and `TopicLifecycleStrategy`). Each time a new state cell is added to the polling system — a common occurrence given ongoing feature work — every handler that performs a "reset on event" must be audited and potentially updated. Because the reset logic is not co-located with the state definition, this audit requires grepping the entire codebase.

The `status_bubble` module compounds this: it uses a module-level injectable function pointer (`register_rc_active_provider`) to query `terminal_screen_buffer.is_rc_active()` without importing `polling_strategies` directly — a documented workaround for an acknowledged layer violation. The workaround works but adds indirection that new contributors must understand before tracing the RC state path.

### Cascading Changes

- Adding a new per-window polling state cell (e.g., a "vim mode" flag, which `tmux_manager` already has as a separate state store) requires: (1) adding it to `polling_strategies`, (2) wiring a reset into every command handler that performs window resets, (3) testing that no handler was missed.
- Renaming or splitting `lifecycle_strategy` (as has already been done twice in the recent refactoring) requires finding and updating all caller sites across the handler layer.

### Recommended Improvement

Introduce a single `reset_window_state(window_id)` method on a `PollingStateCoordinator` — either on `TerminalPollState` or as a thin facade module. All external callers (command handlers, hook events, recovery callbacks) call this one method. The internals of which cells to reset remain inside `polling_strategies`. This converts the current multi-step [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to a single [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) call, reducing the impact of any future polling state refactoring to one update site.

For `status_bubble`'s RC-state read: remove `register_rc_active_provider` and instead add `is_rc_active(window_id)` to the same facade. The injectable function pointer was the right instinct (avoid the layer violation) but a facade method is cleaner than runtime injection.

The trade-off: creating the facade requires one new function and updating ~4 call sites. The benefit compounds with each subsequent polling state refactoring.

</div>

---

## Issue 4: claude_task_state Has Six Mutation Authorities

<div class="issue">

**Integration**: `session_lifecycle.py`, `transcript_reader.py`, `hook_events.py`, `window_tick.py`, `status_bubble.py`, `tool_batch.py` → `claude_task_state`  
**Severity**: Significant

### Knowledge Leakage

`claude_task_state.py` is a centralized, mutable task-snapshot store: it tracks `TaskCreate`/`TaskUpdate`/`TaskList` operations from Claude transcripts and subagent registrations from hooks. Its state is read by `status_bubble` to render the live task list in Telegram and by `tool_batch` for subagent label rendering. The problem is not the reads — those are legitimate consumers. The problem is the writes: six distinct modules call mutating functions (`add_subagent`, `remove_subagent`, `clear_subagents`, transcript-driven snapshot updates) with no coordination.

The [knowledge shared](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) is implicit: each writing module has learned the mutation API in isolation and calls it based on its own event trigger. There is no published protocol that specifies which module is authoritative for which mutation under which conditions. If a SubagentStop hook event fires at the same time as a transcript-based subagent removal, both `hook_events` and `transcript_reader` may attempt the removal — with no ordering guarantee.

### Complexity Impact

Six mutation sites with no declared authority means the task state consistency model lives in the collective assumptions of six modules rather than in any single place. When the state model changes — adding fields to `ClaudeTaskSnapshot`, changing how subagent lifecycle events are mapped — every mutation site must be updated and the interactions between them re-validated. This exceeds the cognitive capacity a single developer can hold while making a change: the state is both central (everything reads it) and diffuse (everything writes it).

### Cascading Changes

- Adding a new task state field requires updating `claude_task_state.py` plus all six writing modules that might set or clear the field.
- Adding a new event source (e.g., a new hook event type) that should update task state requires choosing which existing module to put the mutation in — a non-obvious decision with no architectural guidance.
- Changing how subagents are tracked (e.g., moving from name-based to ID-based) requires a coordinated update across all six writing modules.

### Recommended Improvement

Consolidate write authority. The natural owner is `session_lifecycle.py` — its existing role is already "single choke-point for session-end cleanup." Extend that role: make `session_lifecycle` (or a new `task_state_coordinator.py`) the only module that mutates `claude_task_state`. Other modules that currently mutate it directly should instead emit events or call into the coordinator. `transcript_reader`'s `_seed_claude_task_state` method is the clearest offender: seeding task state from a transcript file is a lifecycle concern, not a transcript I/O concern, and should be extracted into the coordinator.

For subagent tracking specifically: `hook_events` and `session_lifecycle` already have a relationship (the former calls `session_lifecycle.handle_session_end()`). Routing subagent mutations through `session_lifecycle` would centralize two related lifecycle concerns.

The trade-off: the coordinator becomes a new dependency for four modules that currently write directly. The gain is a single module to audit for state consistency, a single test target for mutation logic, and a clear answer to "where does task state change?"

</div>

---

## Issue 5: Circular Dependencies Suppressed by Deferred Imports

<div class="issue">

**Integration**: `session.py` ↔ `session_resolver.py`, `session_monitor.py` ↔ `session.py`, `session_map.py` ↔ `window_state_store.py` / `thread_router.py`, `transcript_reader.py` ↔ `tmux_manager.py`  
**Severity**: Minor

### Knowledge Leakage

At least four bidirectional dependency cycles exist in the codebase, each suppressed with a `from .module import symbol` statement inside a function body rather than at module level. The cycles are:

- `session.py` defers `session_resolver` and `providers.registry`
- `session_monitor.py` defers `session_manager` and `thread_router`
- `session_map.py` defers `window_store` and `thread_router` inside nearly every method
- `transcript_reader.py` defers `window_store` and `tmux_manager`

In every case, the deferred import is not a performance optimization — it is a workaround for an `ImportError` that would occur if the import were moved to the top of the file. The workaround works at runtime, but it means that static analysis tools, type checkers, and IDE navigation cannot fully resolve the dependency graph. The [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) between these modules is real; the deferred imports just hide it.

### Complexity Impact

A deferred import inside a method body means the dependency is invisible to `mypy`, `pyright`, and import-cycle detectors. A developer refactoring `session_map.py` to extract a new module must discover at runtime — not statically — that the new module has inherited the cycle. The error (`ImportError: cannot import name X`) will surface only when the affected code path is exercised, not at startup.

Each additional deferred import also adds a small per-call overhead (Python's import machinery still runs the `sys.modules` lookup even on cached imports), but the real cost is cognitive: a reader of `session_map.py` cannot understand its full dependency set from the top of the file.

### Cascading Changes

- Extracting any sub-module from `session.py`, `session_monitor.py`, or `session_map.py` risks inheriting cycles from the parent module unless the extraction is done with full knowledge of all deferred imports.
- Adding a new import to any cycle-participating module requires checking whether it creates a new cycle — a check that can only be done by running the code, not reading it.

### Recommended Improvement

Resolve cycles structurally rather than suppressing them at call time. The most common root cause here is that several modules serve as both state owners and state consumers — they both define data structures and import other modules that depend on those structures. The standard fix is to extract shared data types into a dependency-free `types.py` or `events.py` module. In this codebase: `NewMessage`, `NewWindowEvent`, and `SessionInfo` are defined in `transcript_reader.py` and re-exported by `session_monitor.py`, but they have no internal ccgram dependencies — they belong in a `monitor_events.py` alongside `HookEvent`.

Once shared types are extracted, most deferred imports become top-level imports, and the remaining cycles indicate genuine bidirectional dependencies that should be resolved by introducing a [contract boundary](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (Protocol or facade) between the two modules.

The trade-off: the extraction is mechanical but touches ~8 modules. The benefit is a statically resolvable import graph and accurate IDE navigation.

</div>

---

## Issue 6: Providers Hard-Wire tmux_manager Instead of Accepting Injected Capture Functions

<div class="issue">

**Integration**: `providers/shell_infra.py` and `providers/claude.py` → `tmux_manager` (lazy imports inside async methods)  
**Severity**: Minor

### Knowledge Leakage

`shell_infra.py`'s async functions (`has_prompt_marker`, `detect_pane_shell`, `setup_shell_prompt`) and `claude.py`'s `scrape_current_mode` each lazy-import `tmux_manager` at call time rather than accepting capture/send-keys functions as parameters. This means every provider that needs to read terminal state has acquired a hard runtime dependency on the tmux infrastructure layer. The knowledge leaked is structural: the provider knows it is running inside a tmux environment, and knows the specific API of `tmux_manager` rather than an abstract "capture terminal" interface.

### Complexity Impact

Any test that exercises `shell_infra.setup_shell_prompt()` or `ClaudeProvider.scrape_current_mode()` must either mock the entire `tmux_manager` module or run with a real tmux session. There is no lightweight alternative because the dependency is unconditional at call time. The 146 test files and the integration test suite already reflect this constraint — tests that exercise shell prompt setup are segregated to integration tests, not unit tests.

### Cascading Changes

- Adding a new provider that needs terminal capture must either import `tmux_manager` directly (perpetuating the pattern) or invent its own injection mechanism.
- Porting ccgram to a different terminal multiplexer (e.g., `zellij`) would require modifying the provider layer, not just the infrastructure layer.

### Recommended Improvement

Add `capture_fn: Callable[[str], str]` and `send_keys_fn: Callable[[str, str], None]` parameters to the affected provider methods, with defaults of `tmux_manager.capture_pane` and `tmux_manager.send_keys` respectively. This is a small change (default parameters preserve backward compatibility) that makes the tmux dependency explicit and injectable for tests. The pattern is already used correctly elsewhere — `IdleTracker` accepts `session_id → timestamp` resolution from the caller rather than importing a session resolver — this simply extends it to terminal capture.

The trade-off: adding parameters to provider methods increases the `AgentProvider` Protocol's surface area or requires the defaults to live outside the Protocol definition. Given the Protocol is already 18 methods wide, consider whether `scrape_current_mode` belongs there or whether it is a capability that only some providers implement and should be part of a narrower `TerminalProvider` sub-protocol.

</div>

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
