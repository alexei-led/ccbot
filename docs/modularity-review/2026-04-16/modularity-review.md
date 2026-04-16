# Modularity Review

**Scope**: Entire codebase (~100 Python source files, ~34K lines)
**Date**: 2026-04-16 (v6)

## Executive Summary

ccgram is a Telegram bot that manages AI coding agents (Claude Code, Codex, Gemini, Shell) through tmux, mapping each Telegram Forum topic to one tmux window running one agent CLI instance. The overall modularity is **healthy with localized imbalances**. The codebase shows strong architectural instincts — clean provider protocol, well-encapsulated polling state, contract-level message queue APIs, and a recent session_monitor decomposition into focused modules. Two significant issues stand out: `SessionManager` aggregates 7 unrelated responsibilities behind a 39-method facade that 17+ modules import as a one-stop shop ([low cohesion](https://coupling.dev/posts/core-concepts/balance/)), and the provider abstraction leaks shell-specific and Claude-specific knowledge into generic code ([implicit functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)).

### Dimensional Scores

| Dimension                   | Score | Notes                                                                                                                                       |
| --------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Cohesion**                | 6/10  | Most modules are focused. SessionManager aggregates 7 concerns. Handler layer is flat (50+ files, no sub-packages).                         |
| **Abstraction Integrity**   | 7/10  | Provider protocol is clean (no `isinstance` checks). Shell/Claude leaks in 6 files. `window_query` decoupling layer is well-designed.       |
| **Coupling Balance**        | 8/10  | No high-strength + high-distance pairs. All coupling balanced by low distance. Risk is masked by solo-developer context.                    |
| **Knowledge Encapsulation** | 7/10  | Module-level dicts behind getter/setter APIs. SessionManager exposes sub-object dicts via properties. Interactive UI has implicit protocol. |
| **Cognitive Load**          | 6/10  | 50+ handler files in flat namespace. 12+ singletons with deferred imports and callback wiring. Individual modules well-documented.          |
| **Change Resilience**       | 7/10  | New commands: easy. New providers: requires touching generic code. Session management: touches many callers but changes are infrequent.     |

## Coupling Overview

| Integration                                     | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                     | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)                                   |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 17+ modules -> `SessionManager`                 | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (39-method facade)                | Low (same process, same developer)                                      | Medium-high (core domain)                                                   | Yes, but [low cohesion](https://coupling.dev/posts/core-concepts/balance/) within SessionManager |
| `transcript_reader` -> Claude task state        | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (implicit, name-based branch)     | Low (same package)                                                      | Medium (provider-specific logic)                                            | Yes, but undermines designed abstraction                                                         |
| 5 shell handlers -> `providers.shell` internals | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (bypasses protocol)                | Low (adjacent packages)                                                 | Medium (shell UX evolves)                                                   | Yes, but undermines designed abstraction                                                         |
| `interactive_ui` <-> 5 handler callers          | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (implicit state protocol)         | Low (same package)                                                      | High (UI features evolve)                                                   | Yes ([high cohesion](https://coupling.dev/posts/core-concepts/balance/))                         |
| Handlers -> `message_queue` enqueue API         | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (clean public functions)            | Low (same package)                                                      | High (message delivery is core)                                             | Yes                                                                                              |
| Handlers -> `polling_strategies` singletons     | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (shared strategy objects, 30+ methods) | Low (same package)                                                      | Medium-high (polling behavior evolves)                                      | Yes                                                                                              |
| All modules -> `providers/base.py` protocol     | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (protocol + capabilities)           | Low (adjacent packages)                                                 | Low (stable protocol)                                                       | Yes                                                                                              |
| `bot.py` -> all handler modules                 | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (composition root wiring)         | Low (same package)                                                      | High (new features need wiring)                                             | Yes (expected for composition root)                                                              |

## Issue: SessionManager Low Cohesion

**Integration**: Internal structure of `SessionManager` (7 responsibilities, 39 public methods, 17+ direct importers)
**Severity**: Significant

### Knowledge Leakage

`SessionManager` serves as a facade over five dedicated sub-objects: `ThreadRouter`, `WindowStateStore`, `UserPreferences`, `SessionMapSync`, and `SessionResolver`. Of its 39 public methods, **18 are pure one-line delegations** that add no logic — `get_display_name()` delegates to `thread_router`, `load_session_map()` delegates to `session_map_sync`, `get_session_id_for_window()` delegates to `window_store`, etc. Callers importing `session_manager` to call these delegations are [functionally coupled](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to SessionManager's interface when they actually need `thread_router` or `window_store` directly.

The codebase already demonstrates the fix pattern: `window_query.py` provides read-only free functions (`view_window()`, `get_window_provider()`, `get_approval_mode()`) that go directly to `window_store`, letting handlers bypass SessionManager entirely for read operations. But only a subset of the handler files that import `session_manager` use this decoupling layer — the rest still route through the facade.

### Complexity Impact

A developer modifying window state management (e.g., adding a new per-window mode) must touch `SessionManager` to add a getter/setter pair, even though the actual state lives in `WindowStateStore`. The 39-method API surface makes it hard to determine which methods are substantive orchestration (like `resolve_stale_ids()` or `audit_state()`) versus pure pass-throughs. A developer's working memory must hold SessionManager's full API to decide where a change belongs — exceeding the 4+/-1 cognitive capacity limit described by the [complexity model](https://coupling.dev/posts/core-concepts/complexity/).

### Cascading Changes

- **Adding a new per-window setting**: requires adding a method to `WindowStateStore`, then a delegation method to `SessionManager`, then updating `_serialize_state()`. The middle step is pure waste.
- **Splitting persistence**: if `window_store` ever needs its own persistence file (e.g., for performance), `SessionManager._serialize_state()` must change because it currently assembles a single state blob from all sub-objects.
- **New callers**: every new handler defaults to importing `session_manager` because it's the documented entry point, deepening the facade dependency.

### Recommended Improvement

Extend the `window_query.py` pattern: create equivalent read-only free-function modules for `thread_router` and `session_map` operations. Handlers that only read state should import these modules instead of `session_manager`. This reduces SessionManager's role to three things it genuinely owns:

1. **Startup orchestration** (`__post_init__`, `_wire_singletons`, `resolve_stale_ids`)
2. **Write coordination** (methods that must trigger `_save_state` across multiple sub-objects)
3. **Cross-cutting audit** (`audit_state`, `prune_stale_state`)

The 18 pure delegations would be deleted. Callers switch from `session_manager.get_display_name(wid)` to `thread_router.get_display_name(wid)` — a rename, not a redesign. The sub-objects already have clean public APIs; the facade just obscures them.

**Trade-off**: more import paths to learn, less discoverability of "where do I find X." But the `window_query` module already proves this works — handlers that use it don't miss SessionManager.

## Issue: Provider Abstraction Leaks

**Integration**: Handler modules -> concrete provider implementations (bypassing `AgentProvider` protocol)
**Severity**: Significant

### Knowledge Leakage

The `AgentProvider` protocol in `providers/base.py` defines a clean [contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) with 15 methods and a `ProviderCapabilities` capability-flag system. No `isinstance` checks exist anywhere. Yet six files bypass this contract:

**Shell-specific leaks** (5 handler files import shell internals not on the protocol):

- `shell_capture.py` imports `match_prompt` from `providers.shell`
- `shell_commands.py` imports `KNOWN_SHELLS`, `match_prompt` from `providers.shell`
- `shell_context.py` imports `detect_pane_shell` from `providers.shell`
- `shell_prompt_orchestrator.py` imports `has_prompt_marker`, `setup_shell_prompt` from `providers.shell_infra`
- `directory_callbacks.py` imports `KNOWN_SHELLS` from `providers.shell`

**Claude-specific leak** (1 core module branches on provider identity):

- `transcript_reader.py:127,152` checks `provider.capabilities.name == "claude"` to invoke `_seed_claude_task_state()` and `claude_task_state.apply_entries()`. This embeds a business rule — "Claude has a task-state model" — in a component designed to be provider-agnostic.

### Complexity Impact

The `AgentProvider` protocol creates intentional conceptual [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) between generic handling code and provider-specific behavior. When handlers reach past it, they negate that distance. A developer adding a 5th provider (e.g., Cursor, Aider) with its own task-state model would need to modify `transcript_reader.py` — a module that shouldn't know about any specific provider. Similarly, shell-specific prompt matching logic is scattered across 5 handler files instead of being encapsulated within the shell provider.

### Cascading Changes

- **Adding a provider with task state**: `transcript_reader.py` needs another `elif provider.capabilities.name == "newprovider"` branch. The generic module accumulates provider-specific knowledge.
- **Changing shell prompt marker format**: 5 handler files import shell-specific functions (`match_prompt`, `has_prompt_marker`, `KNOWN_SHELLS`). A format change in the shell provider cascades to handler code that should be insulated.
- **Refactoring shell infrastructure**: `providers.shell_infra` is imported by `shell_prompt_orchestrator.py` — an implementation detail of the shell provider leaking into the handler layer.

### Recommended Improvement

**For Claude task state**: add a capability method to the protocol, e.g., `apply_task_state(entries, snapshot) -> None` with a no-op default. `ClaudeProvider` overrides it with the real implementation. `transcript_reader.py` calls `provider.apply_task_state(entries, snapshot)` unconditionally — no name check needed. This converts [implicit functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) through the protocol.

**For shell-specific handler imports**: the shell subsystem (4 handler files) is inherently shell-specific — they only run when the window's provider is `shell`. The architectural risk is not that they know shell internals, but that shell-specific functions like `match_prompt` live in `providers/` instead of being co-located with the handlers that use them. Consider either: (a) moving shell-specific handler utilities (prompt matching, shell detection) into the `handlers/shell_*` modules, or (b) adding relevant capabilities to the protocol (`AgentProvider.match_output_prompt()`, `AgentProvider.detect_shell_variant()`). Option (a) is simpler and keeps the protocol lean.

**Trade-off**: expanding the protocol adds methods that most providers implement as no-ops. But the protocol already has 15 methods — one more for task state doesn't materially increase the surface area.

## Issue: Handler Flat Namespace

**Integration**: 50+ handler modules in `handlers/` package with 25+ cross-imports
**Severity**: Minor

### Knowledge Leakage

No implementation details leak between handlers — cross-imports use public APIs (enqueue functions, strategy methods, callback registration). The issue is structural: related handlers have no grouping signal. The shell subsystem (`shell_commands`, `shell_capture`, `shell_context`, `shell_prompt_orchestrator`) forms a clean internal DAG with no shared state and an explicitly injection-decoupled cross-reference, but a developer must trace imports to discover this structure. Similarly, the messaging subsystem (`msg_broker`, `msg_delivery`, `msg_telegram`, `msg_spawn`) and directory subsystem (`directory_browser`, `directory_callbacks`) are cohesive groups invisible in the flat namespace.

### Complexity Impact

With 50+ modules at the same level, a developer looking at `shell_capture.py` has no structural signal that it's part of a 4-module shell subsystem distinct from the other 46 handler files. Grep and import tracing are required to understand change boundaries. This increases cognitive load when assessing change impact but does not cause cascading changes — the APIs between handlers are clean.

### Cascading Changes

None directly caused by the flat structure. The shell subsystem's internal coupling, for example, is well-managed (clean DAG, callback injection for the `shell_capture` <-> `shell_commands` cycle). The cost is cognitive, not structural.

### Recommended Improvement

Group related handlers into sub-packages: `handlers/shell/`, `handlers/messaging/`, `handlers/directory/`. Each sub-package gets an `__init__.py` that re-exports the public entry points (`handle_shell_message`, `broker_delivery_cycle`, `build_directory_browser`). Internal modules become package-private.

This is a structural change with no behavioral impact — imports update but no logic changes. It makes the cohesive groups discoverable from the directory listing.

**Trade-off**: more directories, slightly deeper import paths. The handler layer already has the natural groupings (shell*\*, msg*\_, directory\_\_) — sub-packages would just formalize what's already there.

## Issue: Interactive UI Implicit State Protocol

**Integration**: `interactive_ui.py` <-> 5 handler callers (`hook_events`, `window_tick`, `text_handler`, `interactive_callbacks`, `message_routing`)
**Severity**: Minor

### Knowledge Leakage

The interactive UI module manages three module-level dicts (`_interactive_msgs`, `_interactive_mode`, `_send_cooldowns`) behind getter/setter functions. Five handler modules coordinate around these to implement a lifecycle: detect interactive UI -> set mode -> update on ticks -> clear when done. The lifecycle transitions are not documented — callers must understand when to use `clear_interactive_mode` (partial clear: mode only) vs. `clear_interactive_msg` (full clear: mode + message + cooldowns + Telegram message deletion). This distinction is load-bearing: `message_routing.py` uses partial clear in one branch and full clear in another, with the choice depending on whether a Telegram message was sent.

### Complexity Impact

The [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) is high but at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) — all five callers are in the same package. The implicit protocol means a developer modifying one transition path (e.g., how `hook_events` sets interactive mode) must mentally simulate all five callers to verify consistency. This is manageable at current scale but fragile to new callers joining the protocol without understanding the partial-vs-full clear contract.

### Cascading Changes

- **Adding a new interactive UI trigger**: must understand both clear variants and choose correctly. No type system or documentation guards against choosing wrong.
- **Changing the clear semantics**: all five callers must be audited. The partial/full distinction is only visible by reading function implementations.

### Recommended Improvement

Document the state machine as comments in `interactive_ui.py` — a lifecycle diagram showing the valid transitions and when to use each clear variant. Alternatively, consolidate the two clear functions into one with an explicit flag (`clear_interactive(*, delete_message: bool)`), making the distinction self-documenting at every call site.

**Trade-off**: minimal. Documentation costs nothing. The flag approach requires updating 6 call sites but makes every caller explicit about intent.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
