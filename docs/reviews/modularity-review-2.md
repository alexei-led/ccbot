# Modularity Review #2

**Scope**: Full codebase — `src/ccgram/` (~25,500 LOC across 55 Python modules)
**Date**: 2026-03-29
**Context**: Post-refactoring assessment. Review #1 (2026-03-28) identified 5 issues; this review measures resolution and identifies new concerns.

## Executive Summary

The modularity refactoring resolved 4 of 5 original issues convincingly. `bot.py` dropped from 2,018 to 1,050 lines via a self-registering callback dispatch registry. `status_polling.py` was decomposed into a coordinator + 4 strategy classes. Provider-specific logic was moved behind the provider protocol. The shell prompt implicit contract was replaced with a typed `PromptMatch` dataclass. These are genuine structural improvements that reduced [integration strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) and eliminated [change amplifiers](https://coupling.dev/posts/core-concepts/complexity/).

One original issue remains partially resolved: `SessionManager` still has 17 direct consumers despite `protocols.py` defining the narrow interfaces recommended in Review #1. Two new concerns have emerged: fragmented per-topic state forcing coordinated cleanup across 10+ modules, and `polling_coordinator.py` inheriting much of the multi-domain knowledge from the decomposed `status_polling.py`.

**Overall assessment**: The codebase's modularity improved materially. The provider subsystem, LLM/Whisper packages, and callback dispatch are well-bounded. The remaining issues are less severe than the originals — the system is no longer dominated by 2,000-line monoliths — but the fragmented state pattern is the most likely root cause of the reported "adding a feature breaks others" fragility.

---

## Previous Issues: Resolution Status

| #   | Issue (Review #1)                 | Severity    | Status          | Evidence                                                                                                                                                      |
| --- | --------------------------------- | ----------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Status Polling Knowledge Sprawl   | CRITICAL    | **✅ Resolved** | Decomposed into `polling_coordinator.py` (941 lines) + `polling_strategies.py` (494 lines) with 4 strategy classes                                            |
| 2   | SessionManager State Accumulation | CRITICAL    | **⚠️ Partial**  | `ThreadRouter` extracted; `protocols.py` defined but 0 consumers use it; 17 handlers still import `session_manager` directly                                  |
| 3   | bot.py Dispatch Monolith          | CRITICAL    | **✅ Resolved** | 2,018 → 1,050 lines; `callback_registry.py` with `@register` decorator; handler modules self-register                                                         |
| 4   | Provider Abstraction Leakage      | SIGNIFICANT | **✅ Resolved** | `codex_status.py` → `providers/codex_status.py`; `interactive_prompt_formatter.py` → `providers/codex_format.py`; `build_status_snapshot()` added to protocol |
| 5   | Shell Prompt Implicit Contract    | SIGNIFICANT | **✅ Resolved** | `PromptMatch(sequence_number, trailing_text, exit_code, raw_line)` dataclass replaces raw `re.Match`                                                          |

### Resolution Details

**Issue #1 — Status Polling**: The recommended decomposition into Terminal Status, Interactive UI, Topic Lifecycle, and Shell Relay strategies was implemented precisely. Each strategy class in `polling_strategies.py` owns its module-level state and presents a focused interface. The coordinator delegates without interpreting strategy internals. This is a textbook application of the [Strategy pattern](https://coupling.dev/posts/core-concepts/modularity/) to reduce knowledge sprawl.

**Issue #3 — bot.py**: The callback dispatch is now a 10-line `dispatch()` function in `callback_registry.py`. Handler modules use `@register(CB_PREFIX)` decorators to self-register. Adding a new callback requires zero changes to bot.py. Orchestration logic was extracted to `command_orchestration.py` and `topic_orchestration.py`. The import count dropped from 41 to ~20.

**Issue #4 — Provider Leakage**: The `AgentProvider` protocol now includes `build_status_snapshot()` and `has_output_since()`. The `capabilities.name == "codex"` checks in bot.py are gone. Consumers interact with providers exclusively through the protocol. This is the cleanest boundary in the codebase.

**Issue #5 — Shell Contract**: `match_prompt()` now returns `PromptMatch | None` with named fields. `shell_capture.py` accesses `.exit_code` and `.sequence_number` instead of positional regex groups. Adding a new marker field cannot silently break consumers.

---

## Coupling Overview (Current State)

| Integration                      | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| -------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Hook System → Monitoring         | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | High (separate processes)                                               | Low                                                                         | ✅ Yes                                                         |
| Provider Protocol → Consumers    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | Low (same package)                                                      | Low-Medium                                                                  | ✅ Yes                                                         |
| LLM/Whisper → Consumers          | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | Low (same package)                                                      | Low                                                                         | ✅ Yes                                                         |
| Callback Registry → Handlers     | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | Low (same package)                                                      | Medium                                                                      | ✅ Yes                                                         |
| Polling Strategies → Coordinator | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)      | Low (same package)                                                      | Medium                                                                      | ✅ Yes                                                         |
| Shell PromptMatch → Consumers    | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)   | Low (same package)                                                      | High                                                                        | ✅ Yes                                                         |
| cleanup.py → 10+ handler modules | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)  | Low (same package)                                                      | High                                                                        | **❌ No**                                                      |
| SessionManager → 17 handlers     | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Low (same package)                                                      | Medium                                                                      | **❌ No**                                                      |
| polling_coordinator → 5+ domains | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Low (same package)                                                      | Medium-High                                                                 | **⚠️ Borderline**                                              |

---

## Issue: Fragmented Per-Topic State

**Integration**: 8+ handler modules ↔ `cleanup.py` coordination hub
**Severity**: SIGNIFICANT
**New in this review**: Yes — emerged as a consequence of decomposing the polling monolith

### Knowledge Leakage

Each handler module that tracks per-topic or per-window runtime state maintains its own module-level dictionary:

| Module                  | State Dicts                                                               | Keyed By                                |
| ----------------------- | ------------------------------------------------------------------------- | --------------------------------------- |
| `message_queue.py`      | `_tool_msg_ids`, `_status_msg_info`, `_active_batches`                    | `(user_id, thread_id)`                  |
| `polling_strategies.py` | `_topic_states`, `_window_states`, `_dead_notified`, `_pane_alert_hashes` | mixed: `(user, thread)` and `window_id` |
| `interactive_ui.py`     | `_interactive_msgs`, `_interactive_mode`, `_send_cooldowns`               | `(user_id, thread_id)`                  |
| `shell_commands.py`     | `_shell_pending`, `_generation_counter`                                   | `(chat_id, thread_id)`                  |
| `shell_capture.py`      | `_shell_monitor_state`                                                    | `window_id`                             |
| `command_history.py`    | `_history`                                                                | `(user_id, thread_id)`                  |
| `topic_emoji.py`        | `_topic_states`, `_pending_transitions`, `_topic_names`                   | `(chat_id, thread_id)`                  |
| `hook_events.py`        | `_active_subagents`                                                       | `window_key`                            |
| `process_detection.py`  | `_pgid_cache`                                                             | `window_id`                             |

This is 20+ independent dictionaries across 9 modules, all representing facets of the same conceptual entity: **the runtime state of a topic/window binding**.

`cleanup.py` serves as the coordination point. Its `clear_topic_state()` function (116 lines) calls cleanup functions from each module via **7 lazy imports** to avoid circular dependencies:

```python
# cleanup.py lazy imports (circular dep avoidance)
from .polling_strategies import clear_dead_notification, clear_pane_alerts, ...
from ..tmux_manager import clear_vim_state
from .hook_events import clear_subagents
from ..thread_router import thread_router
from .command_history import clear_history
from .shell_capture import clear_shell_monitor_state
from .shell_commands import clear_shell_pending
from ..providers.process_detection import clear_detection_cache
```

This is [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/): `cleanup.py` reaches into the internal state of 10+ modules to purge their private dictionaries. It must know which modules have state, what their cleanup functions are named, and which key type each uses (`window_id` vs `(user_id, thread_id)` vs `(chat_id, thread_id)`).

### Cascading Changes

This is the most likely root cause of the reported fragility ("adding a simple feature breaks others"):

1. **Adding a new stateful handler feature** (e.g., per-topic auto-screenshot tracking) requires: (a) add module-level dict, (b) add `clear_*()` function, (c) add lazy import + call in `cleanup.py`. **Missing step (c) causes a state leak** — the dict accumulates entries for deleted topics, potentially causing ghost messages, stale UI, or memory growth.

2. **Inconsistent key types**: Some modules key by `(user_id, thread_id)`, others by `(chat_id, thread_id)`, others by `window_id`. A cleanup call with the wrong key type silently misses entries. There is no compile-time or test-time check that all state dicts were cleared.

3. **Late imports mask dependency direction**: The 7 lazy imports in `cleanup.py` exist because top-level imports would create circular dependencies. This signals that the dependency graph has structural cycles — `cleanup.py` depends on modules that (transitively) depend on modules that import from `cleanup.py`.

### Why It's Unbalanced

- **Strength**: Intrusive — cleanup reaches into private module state
- **Distance**: Low (same package, same developer)
- **Volatility**: HIGH — every new feature that tracks per-topic state must update the coordination hub

The [balance rule](https://coupling.dev/posts/core-concepts/balance/) flags this: high integration strength in a volatile area creates rigidity. Each new feature carries the hidden cost of cleanup coordination.

### Recommended Improvement

Consolidate per-topic runtime state into a single `TopicRuntimeState` aggregate:

```python
@dataclass
class TopicRuntimeState:
    """All ephemeral per-topic state, owned by one dict, cleared atomically."""
    status_msg_info: StatusMsgInfo | None = None
    tool_msg_ids: dict[str, int] = field(default_factory=dict)
    active_batch: ToolBatch | None = None
    interactive_mode: str | None = None
    interactive_msg_id: int | None = None
    shell_pending: ShellPending | None = None
    shell_monitor: ShellMonitorState | None = None
    command_history: deque[str] = field(default_factory=deque)
    topic_emoji_state: EmojiState | None = None
    subagent_names: list[str] = field(default_factory=list)
    poll_state: TopicPollState | None = None
    window_poll_state: WindowPollState | None = None
```

One dict (`dict[tuple[int, int], TopicRuntimeState]`), one `clear()` call. Modules receive their slice of state as a parameter rather than looking it up in their own global dict. `cleanup.py` becomes a 5-line function that pops one key.

**Trade-off**: Requires each module to accept state as a parameter instead of owning it privately. This is a moderate refactoring effort but eliminates the entire class of "forgot to add cleanup" bugs and removes 7 circular dependency workarounds.

---

## Issue: Unused Protocol Interfaces

**Integration**: `protocols.py` (defined) → 17 handler modules (not consumed)
**Severity**: MODERATE
**Carried from Review #1**: SessionManager state accumulation (partially resolved)

### Current State

Review #1 recommended narrow `Protocol` interfaces so handlers depend on specific slices of `SessionManager`. The protocols were implemented:

- `WindowStateStore` — 4 methods (get/clear window state, display names, session IDs)
- `UserPreferences` — 7 methods (notification/approval/batch mode)
- `SessionResolver` — 2 methods (session resolution, message history)

However, **zero modules import from `protocols.py`**. All 17 handler modules still use:

```python
from ..session import session_manager  # direct singleton access
```

The protocols exist as documentation but provide no structural benefit. `SessionManager` (1,476 lines) remains the single state attractor with its full 40+ method API surface available to every consumer.

### Why It Matters Less Now

This is downgraded from CRITICAL to MODERATE for two reasons:

1. **`ThreadRouter` extraction was effective.** The routing core (`bind_thread`, `unbind_thread`, `get_window_for_thread`, display names) moved to `thread_router.py` with zero ccgram imports — a genuinely independent module. This removed the highest-traffic concern from `SessionManager`.

2. **Single-developer context.** With one developer, the "someone accidentally calls the wrong method" risk is lower than in a team setting. The [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) is uniformly low.

### Recommended Improvement

Either adopt the protocols (change handler imports to use protocol-typed parameters or annotations) or remove `protocols.py` to eliminate dead code. The middle state — defined but unused — adds confusion without benefit.

If adopting: the simplest path is adding type annotations to handler function signatures:

```python
# Before
from ..session import session_manager
def handle_foo(update, context):
    state = session_manager.get_window_state(window_id)

# After
from ..protocols import WindowStateStore
def handle_foo(update, context, *, store: WindowStateStore = session_manager):
    state = store.get_window_state(window_id)
```

This makes dependencies explicit at type-check time without changing runtime behavior.

---

## Issue: polling_coordinator Multi-Domain Knowledge

**Integration**: `polling_coordinator.py` → providers, sessions, tmux, interactive UI, shell, topic lifecycle, recovery, message queue
**Severity**: MODERATE
**Evolution of Review #1 Issue #1**: The 1,339-line monolith was decomposed, but the coordinator retained significant orchestration knowledge

### Current State

`polling_coordinator.py` (941 lines) imports from 15+ modules:

- Core: `config`, `session_manager`, `thread_router`, `tmux_manager`
- Providers: `detect_provider_from_pane`, `get_provider_for_window`, `StatusUpdate`, + 3 more
- Strategies: `TopicPollState`, `WindowPollState`, `terminal_strategy`, `interactive_strategy`, `lifecycle_strategy`, + 6 constants
- Handlers: `cleanup`, `interactive_ui` (5 functions), `message_queue` (3 functions), `recovery_callbacks`, `topic_emoji`
- Utilities: `window_resolver`, `log_throttle_sweep`

The strategy decomposition successfully isolated **state ownership** — each strategy owns its dicts and exposes clear/query functions. However, the **orchestration logic** in the coordinator still has [model-level knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of how strategies interact:

- It knows that interactive UI checks must run _before_ terminal status parsing
- It knows that provider transitions require shell prompt setup
- It knows that dead window detection must consider transcript discovery
- It imports private constants (`_ACTIVITY_THRESHOLD`, `_MAX_PROBE_FAILURES`, `_STARTUP_TIMEOUT`) from strategies

### Why It's Borderline

- **Strength**: Functional — calls strategy APIs but also imports private constants
- **Distance**: Low
- **Volatility**: Medium-High — polling behavior changes with each new provider or UI feature

The coordinator is doing legitimate orchestration work — someone has to sequence the strategies. But importing private constants (`_ACTIVITY_THRESHOLD`) from strategies breaks the encapsulation the decomposition was meant to create.

### Recommended Improvement

1. **Stop importing private constants.** Strategy classes should expose them as properties or accept them as configuration, not export underscored module-level variables.

2. **Consider a `PollResult` return type** from each strategy's poll method, so the coordinator routes results without interpreting strategy internals:

```python
@dataclass
class PollResult:
    status_text: str | None = None
    is_interactive: bool = False
    should_cleanup: bool = False
    emoji_state: str | None = None
```

This would make the coordinator a pure dispatcher (~300 lines) rather than an interpreter of strategy semantics.

---

## Well-Balanced Integrations

These integrations demonstrate good modularity and should be preserved:

### Provider Protocol

The `AgentProvider` protocol with `ProviderCapabilities` is the strongest boundary in the codebase. Four providers (Claude, Codex, Gemini, Shell) implement 15+ methods behind a uniform interface. Consumers never check `capabilities.name`. The `JsonlProvider` base class shares JSONL parsing logic between Codex and Gemini without coupling them. Provider-specific helpers (`codex_status.py`, `codex_format.py`) live inside `providers/` where they belong.

### LLM and Whisper Subsystems

Both use the factory + protocol pattern: `get_completer() → CommandGenerator`, `get_transcriber() → WhisperTranscriber`. Zero imports from other ccgram modules in the base protocols. Implementation modules (`httpx_completer.py`, `httpx_transcriber.py`) depend only on their own base types. Adding a new LLM provider requires zero changes outside `llm/`.

### Callback Registry

Self-registration via `@register(CB_PREFIX)` decorators. Adding a new callback handler is a 1-step operation (add the decorator). The dispatch function is 15 lines. This replaced a 100+ line cascading if-elif chain.

### ThreadRouter

Extracted from `SessionManager` with zero ccgram imports. Owns all topic ↔ window bindings, display names, group chat IDs. Clean data ownership with `to_dict()`/`from_dict()` serialization. No knowledge of providers, sessions, or polling.

### Leaf Modules

`terminal_parser.py`, `screen_buffer.py`, `screenshot.py`, `telegram_sender.py`, `window_resolver.py`, `monitor_state.py` — all have zero or near-zero ccgram imports. Pure utilities that can be tested, modified, and understood in isolation.

---

## Modularity Scorecard

| Dimension                        | Review #1 (2026-03-28)                          | Review #2 (2026-03-29)                                                 | Trend                       |
| -------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------- | --------------------------- |
| Largest module                   | `bot.py` (2,018 lines)                          | `session.py` (1,476 lines)                                             | ⬆️ Improved                 |
| Modules > 1,000 lines            | 3 (`bot.py`, `session.py`, `status_polling.py`) | 2 (`session.py`, `bot.py` at 1,050)                                    | ⬆️ Improved                 |
| Max import count (single module) | 41 (`bot.py`)                                   | ~20 (`bot.py`)                                                         | ⬆️ Improved                 |
| Critical issues                  | 3                                               | 0                                                                      | ⬆️ Improved                 |
| Significant issues               | 2                                               | 1                                                                      | ⬆️ Improved                 |
| Moderate issues                  | 0                                               | 2                                                                      | ⬇️ New issues surfaced      |
| Balanced integrations            | 2 (hook, provider protocol)                     | 6 (hook, provider, LLM/whisper, callbacks, strategies, shell contract) | ⬆️ Improved                 |
| Late import workarounds          | Not measured                                    | 7 (in cleanup.py alone)                                                | 🔍 Newly measured           |
| Protocols defined                | 0                                               | 3 (unused)                                                             | ➡️ Structural but not wired |

---

## Priority Recommendations

1. **Consolidate per-topic runtime state** (addresses Issue #1 — fragmented state). This directly fixes the "adding a feature breaks others" fragility by making state cleanup atomic and making the dependency on state explicit in function signatures.

2. **Either adopt or remove `protocols.py`** (addresses Issue #2). Dead abstractions add confusion. If the protocols stay, wire them; if not, delete the file.

3. **Stop exporting private constants from `polling_strategies.py`** (addresses Issue #3). Rename or encapsulate `_ACTIVITY_THRESHOLD` etc. as strategy class attributes or configuration parameters.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
