# Modularity Improvement Report

**Scope**: Full codebase — `src/ccgram/` (~25,500 LOC, 55 Python modules)
**Date**: 2026-03-29
**Context**: Post-refactoring assessment measuring architectural improvements from the modularity refactoring effort (commits `4358fc5` through `5358808`)

---

## Executive Summary

The modularity refactoring delivered **substantial, measurable improvements** across the codebase. Four of five original issues from the initial review were resolved, with the fifth partially addressed. The refactoring reduced the largest module from 2,018 to 1,050 lines, eliminated a 155-line callback dispatch monolith, decomposed a 1,340-line polling file into strategy classes, moved provider-specific logic behind the provider protocol, and replaced an implicit regex contract with a typed dataclass.

The codebase moved from **3 critical issues to 0 critical issues**. Balanced integrations increased from 2 to 6. One new concern emerged — fragmented per-topic state across 9 modules with 5 cleanup gaps — which is the most likely root cause of the reported feature-addition fragility.

### Improvement Scorecard

| Metric                           | Before           | After            | Change   |
| -------------------------------- | ---------------- | ---------------- | -------- |
| Critical issues                  | 3                | 0                | **-3**   |
| Significant issues               | 2                | 1                | **-1**   |
| Balanced integrations            | 2                | 6                | **+4**   |
| Largest module (lines)           | 2,018            | 1,476            | **-27%** |
| Modules > 1,000 lines            | 3                | 2                | **-1**   |
| Max import count (single module) | 41               | ~20              | **-51%** |
| Callback dispatch complexity     | 155-line if/elif | 15-line registry | **-90%** |

---

## 1. bot.py Decomposition

**Grade: A** — Excellent decomposition with proper separation of concerns

### Metrics

| Metric                  | Before                 | After                     | Change                |
| ----------------------- | ---------------------- | ------------------------- | --------------------- |
| Line count              | 2,018                  | 1,050                     | **-48%**              |
| CB\_\* constant imports | 47                     | 1                         | **-98%**              |
| Extracted modules       | 0                      | 4                         | +4 new modules        |
| Callback dispatch       | 155-line if/elif chain | 15-line registry dispatch | **Self-registration** |

### What Was Extracted

| Module                     | Lines | Responsibility                                                                  |
| -------------------------- | ----- | ------------------------------------------------------------------------------- |
| `callback_registry.py`     | 124   | Self-registration `@register` decorator, longest-prefix dispatch, authorization |
| `command_orchestration.py` | 681   | Provider `/command` forwarding, scoped menu caching, transcript error probing   |
| `topic_orchestration.py`   | 221   | Auto-create Telegram topics for new tmux windows, post-restart adoption         |
| `polling_coordinator.py`   | 941   | Background status polling orchestration, delegates to strategy classes          |

### Architectural Impact

**Before**: Adding a new callback handler required 4 changes in bot.py — import handler, import CB\_\* prefix, add if/elif branch, register command handler. All 47 callback prefix constants were imported at the top of the file.

**After**: Adding a new callback requires only adding a `@register(CB_PREFIX)` decorator to the handler function. Zero changes to bot.py. The registry auto-discovers handlers via `load_handlers()`.

```python
# Before: 155-line cascade in bot.py
async def callback_handler(update, context):
    data = update.callback_query.data
    if data.startswith(CB_HISTORY_PREV):
        return await handle_history_callback(...)
    elif data.startswith(CB_DIR_SELECT):
        return await handle_directory_callback(...)
    # ... 30+ more branches

# After: Self-registration in each handler module
@register(CB_SESSIONS_REFRESH, CB_SESSIONS_KILL, CB_SESSIONS_KILL_CONFIRM)
async def handle_sessions_callback(update, context): ...
```

**Quality**: No leaked responsibilities. Each extracted module has a single, testable concern. The callback registry is the cleanest structural improvement in the entire refactoring — it converts a change amplifier into a self-contained extension point.

---

## 2. Status Polling Decomposition

**Grade: B** — Good structural separation with encapsulation leakage

### Metrics

| Metric                   | Before        | After              | Change                       |
| ------------------------ | ------------- | ------------------ | ---------------------------- |
| Lines (monolith)         | 1,340         | —                  | Eliminated                   |
| Lines (coordinator)      | —             | 941                | New                          |
| Lines (strategies)       | —             | 494                | New                          |
| Total                    | 1,340         | 1,435              | +7% (decomposition overhead) |
| Module-level state dicts | 4 (scattered) | 4 (strategy-owned) | Organized                    |
| Domain concerns mixed    | 5+            | 1 per strategy     | Separated                    |

### Strategy Pattern Implementation

The recommended decomposition was implemented precisely as prescribed in Review #1:

| Strategy                 | State Owned                                               | Interface                                                                   | Domain                                                            |
| ------------------------ | --------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `TerminalStatusStrategy` | `WindowPollState` per window_id                           | `get_state()`, `parse_with_pyte()`, `is_rc_active()`, `get_screen_buffer()` | Terminal parsing, pyte buffers, RC debounce, content-hash caching |
| `InteractiveUIStrategy`  | `_pane_alert_hashes` per pane_id                          | `has_pane_alert()`, `clear_pane_alerts()`                                   | Multi-pane alert deduplication                                    |
| `TopicLifecycleStrategy` | `TopicPollState` per (user, thread), `_dead_notified` set | 17 methods (autoclose, dead tracking, probe failures)                       | Topic lifecycle timers, dead detection                            |
| `ShellRelayStrategy`     | None (stateless)                                          | None                                                                        | Placeholder for shell output relay                                |

**What works well:**

- State clearly belongs to strategy classes, not scattered in module-level dicts
- Each strategy has an explicit public interface
- 37 module-level convenience wrapper functions reduce coordinator verbosity
- Named constants (`_ACTIVITY_THRESHOLD`, `_STARTUP_TIMEOUT`) replace magic numbers

**Encapsulation concerns (8 violations):**

The coordinator directly accesses private strategy attributes in 8+ locations:

```python
# polling_coordinator.py — breaks strategy encapsulation
interactive_strategy._pane_alert_hashes     # line 278
terminal_strategy._states.get(window_id)    # line 383
lifecycle_strategy._dead_notified           # line 525
lifecycle_strategy._states                  # line 591
terminal_strategy._states                   # line 659
```

**Root cause**: The coordinator needs batch/iteration operations ("clear all dead notifications for this window", "find all windows with probe failures") that strategies don't expose via public methods.

**Cross-strategy coupling**: `TopicLifecycleStrategy` directly mutates `_terminal._states[window_id].probe_failures` — a violation of the strategy boundary. This occurs because `probe_failures` is stored on `WindowPollState` (owned by TerminalStatusStrategy) but semantically belongs to topic lifecycle.

**ShellRelayStrategy**: Empty placeholder with no methods and an unused `_terminal` reference — dead code candidate.

---

## 3. Provider Protocol

**Grade: A** — Strongest boundary in the codebase

### Protocol Design

The `AgentProvider` protocol defines **16 methods** across 5 concerns:

| Concern                     | Methods    | Assessment                         |
| --------------------------- | ---------- | ---------------------------------- |
| Capability declaration      | 1 property | Clean, immutable                   |
| Launch & session management | 3 methods  | Tight, single-responsibility       |
| Transcript parsing          | 5 methods  | Well-scoped per format             |
| Terminal interaction        | 3 methods  | Provider-specific status detection |
| Detection & discovery       | 4 methods  | Extensible, optional               |

**Inheritance hierarchy** eliminates duplication:

```
AgentProvider (Protocol)
├── ClaudeProvider (direct, 231 lines — thin adapter)
├── JsonlProvider (abstract base, shared JSONL parsing)
│   ├── CodexProvider (overrides 9/16, 730 lines)
│   ├── GeminiProvider (overrides 6/16, 753 lines)
│   └── ShellProvider (minimal, 336 lines)
```

`JsonlProvider` consolidates **6 shared helper functions**, eliminating ~150-200 lines of duplication across Codex, Gemini, and Shell providers.

### Provider Leakage Elimination

**Before** (Review #1):

- `codex_status.py` at top-level (237 lines) — Codex JSONL parsing outside provider boundary
- `interactive_prompt_formatter.py` at top-level (245 lines) — Codex-only formatting
- `bot.py` had `_codex_status_probe_offset()` and `_maybe_send_codex_status_snapshot()` with `capabilities.name == "codex"` guards

**After**:

- `codex_status.py` → `providers/codex_status.py` (commit `dc9e4b4`)
- `interactive_prompt_formatter.py` → `providers/codex_format.py` (commit `dc9e4b4`)
- Protocol gained `build_status_snapshot()` and `has_output_since()` methods (commit `4a3e96c`)
- `capabilities.name == "codex"` checks in bot.py replaced with `capabilities.supports_status_snapshot`

**Remaining name checks**: 7 instances of `capabilities.name == "shell"` in handlers for shell-specific routing (approval flow, prompt setup). These are justified — Shell is fundamentally different (direct execution, no LLM) — but could be replaced with a `requires_interactive_approval` capability flag.

### Capabilities Gating

`ProviderCapabilities` has **14 flags** that gate UX per-window:

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_hook: bool           # only Claude
    supports_resume: bool         # Claude, Codex, Gemini
    supports_continue: bool       # Claude, Codex, Gemini
    supports_status_snapshot: bool # only Codex (NEW — eliminated name check)
    # ... 10 more flags
```

Consumers check capabilities, not names — recovery keyboards only show Resume when `supports_resume`, hook checks only run when `supports_hook`, status snapshots only trigger when `supports_status_snapshot`.

---

## 4. Session & Thread Router Decomposition

**Grade: B-** — ThreadRouter extraction was clean; SessionManager remains large

### ThreadRouter Extraction

| Aspect           | Assessment                                                                      |
| ---------------- | ------------------------------------------------------------------------------- |
| Independence     | **Perfect** — zero ccgram imports                                               |
| Interface        | 19 methods, well-organized (bindings, routing, display names, serialization)    |
| Data ownership   | Owns `thread_bindings`, `group_chat_ids`, `window_display_names`, reverse index |
| Coupling pattern | Callback injection: `_schedule_save` lambda for persistence trigger             |

ThreadRouter is the **cleanest extraction** in the refactoring. It owns all topic↔window routing with no dependency on sessions, providers, or configuration.

### SessionManager: Still Large

| Metric           | Before (estimated) | After | Change            |
| ---------------- | ------------------ | ----- | ----------------- |
| Lines            | ~1,800-2,000       | 1,476 | ~25% reduction    |
| Public methods   | ~70+               | 57    | ~20% reduction    |
| Responsibilities | 9+                 | 8     | Minor improvement |
| Consumer imports | 24                 | 17    | -29%              |

**Remaining responsibilities** (8 concerns in one class):

| Concern                           | Methods | Could Extract?                    |
| --------------------------------- | ------- | --------------------------------- |
| Window state                      | 4       | As part of centralized state      |
| Display names                     | 3       | Already delegated to ThreadRouter |
| Notification/approval/batch modes | 9       | Yes → `UserPreferencesManager`    |
| Directory favorites               | 4       | Yes → `UserDirectoryManager`      |
| Window offsets                    | 2       | Yes → `OffsetTracker`             |
| Session resolution                | 7       | Yes → `SessionResolver`           |
| Session map sync                  | 6       | Yes → `SessionMapSync`            |
| Cleanup/audit                     | 5       | Tied to above concerns            |

### Protocols: Defined But Unused

`protocols.py` defines 3 narrow Protocol interfaces (`WindowStateStore`, `UserPreferences`, `SessionResolver`) — exactly as recommended in Review #1. However, **zero modules import from `protocols.py`**. All 17 handler modules still use `from ..session import session_manager` directly.

The protocols provide no structural benefit in their current state. Either adopt them (change handler type annotations) or remove to eliminate dead code.

### Supporting Extractions

| Module                 | Lines | Quality                                                    |
| ---------------------- | ----- | ---------------------------------------------------------- |
| `state_persistence.py` | 72    | Excellent — debounced atomic persistence, reusable pattern |
| `window_resolver.py`   | 201   | Clean — zero ccgram imports, handles startup ID recovery   |

---

## 5. Shell Prompt Contract

**Grade: A** — Textbook implicit-to-explicit contract improvement

### Before (Implicit Regex Groups)

```python
# shell_capture.py — fragile positional access
m = match_prompt(line)  # returns re.Match | None
if m:
    exit_code = int(m.group(1))    # What is group 1? Hope regex doesn't change
    trailing = m.group(2)          # What is group 2? Same fragility
```

### After (Typed PromptMatch)

```python
@dataclass(frozen=True)
class PromptMatch:
    sequence_number: int     # Exit code extracted from marker
    trailing_text: str       # Command text after marker
    exit_code: int           # Semantic alias for sequence_number
    raw_line: str            # Original line for debugging

# shell_capture.py — typed field access
m = match_prompt(line)  # returns PromptMatch | None
if m:
    exit_code = m.exit_code         # Self-documenting
    trailing = m.trailing_text      # Safe from regex changes
```

**Impact**: 6 usages across `shell_capture.py` and `shell_commands.py` converted from positional `m.group(N)` to named field access. Adding a new capture group to the regex cannot silently break consumers.

---

## 6. Leaf Module Independence

**Grade: B+** — Good isolation at utilities level; hidden coupling via global state

### Dependency-Free Modules

| Module               | Lines | ccgram Imports         | Role                                   |
| -------------------- | ----- | ---------------------- | -------------------------------------- |
| `thread_router.py`   | 306   | 0                      | Topic↔window routing (extracted)       |
| `protocols.py`       | 57    | 0 (TYPE_CHECKING only) | Protocol contracts                     |
| `window_resolver.py` | 201   | 0                      | Window ID validation, startup recovery |
| `monitor_state.py`   | ~120  | 0                      | Byte offset tracking for JSONL         |
| `telegram_sender.py` | ~50   | 0                      | Message splitting (4096 limit)         |
| `screen_buffer.py`   | ~80   | 0                      | pyte VT100 screen wrapper              |
| `terminal_parser.py` | ~350  | 0 (TYPE_CHECKING only) | Terminal UI detection, status parsing  |

7 modules with zero runtime ccgram dependencies — these can be tested, modified, and understood in complete isolation.

### Dependency Depth

Maximum import chain depth: **4 layers**

```
handler → session → config → utils → [external]
```

Most handlers are 1-2 layers from leaf modules. No dangerously deep chains.

### LLM and Whisper Independence

Both subsystems use factory + protocol with zero cross-coupling:

```
llm/base.py          → CommandGenerator Protocol (0 ccgram imports)
llm/httpx_completer.py → implements Protocol (imports only llm/base.py)
llm/__init__.py       → factory get_completer() (imports config lazily)

whisper/base.py       → WhisperTranscriber Protocol (0 ccgram imports)
whisper/httpx_transcriber.py → implements Protocol (imports only whisper/base.py)
whisper/__init__.py   → factory get_transcriber() (imports config lazily)
```

Adding a new LLM or Whisper provider requires zero changes outside its respective package.

---

## 7. Remaining Issue: Fragmented Per-Topic State

**Grade: D** — The #1 remaining architectural concern

### State Inventory

**23 module-level state dictionaries** across 9 modules, with **13 topic-scoped** dicts representing facets of the same conceptual entity (a topic/window binding):

| Module                 | Dicts                                                   | Key Scheme               | Cleared by cleanup?     |
| ---------------------- | ------------------------------------------------------- | ------------------------ | ----------------------- |
| `message_queue.py`     | `_tool_msg_ids`, `_status_msg_info`, `_active_batches`  | (user_id, thread_id)     | ✅ Yes                  |
| `interactive_ui.py`    | `_interactive_msgs`, `_interactive_mode`                | (user_id, thread_id)     | ✅ Yes                  |
| `interactive_ui.py`    | `_send_cooldowns`                                       | (user_id, thread_id)     | ❌ **No — memory leak** |
| `shell_commands.py`    | `_shell_pending`                                        | **(chat_id, thread_id)** | ✅ Yes                  |
| `shell_commands.py`    | `_generation_counter`                                   | **(chat_id, thread_id)** | ❌ **No — memory leak** |
| `topic_emoji.py`       | `_topic_states`, `_pending_transitions`, `_topic_names` | **(chat_id, thread_id)** | ✅ Yes                  |
| `command_history.py`   | `_history`                                              | (user_id, thread_id)     | ✅ Yes                  |
| `shell_capture.py`     | `_shell_monitor_state`                                  | window_id                | ✅ Yes                  |
| `text_handler.py`      | `_bash_capture_tasks`                                   | (user_id, thread_id)     | ❌ **No — task leak**   |
| `hook_events.py`       | `_active_subagents`                                     | window_id                | ✅ Yes                  |
| `process_detection.py` | `_pgid_cache`                                           | window_id                | ✅ Yes                  |

### 5 Cleanup Gaps

| Dict                        | Risk                                        | Impact                                           |
| --------------------------- | ------------------------------------------- | ------------------------------------------------ |
| `_send_cooldowns`           | Orphaned timestamps accumulate              | Memory growth over time                          |
| `_generation_counter`       | Orphaned counters accumulate                | Memory growth, potential stale counter collision |
| `_bash_capture_tasks`       | Orphaned asyncio tasks may not be cancelled | Resource leak, potential ghost output            |
| `_topic_create_retry_until` | Orphaned retry timestamps                   | Memory growth                                    |
| `_disabled_chats`           | Global set, never cleared                   | Grows unbounded                                  |

### Key Scheme Inconsistency

Two different key schemes for topic-scoped state:

- **Group A**: `(user_id, thread_id)` — message_queue, interactive_ui, command_history, text_handler
- **Group B**: `(chat_id, thread_id)` — shell_commands, topic_emoji

`cleanup.py` must resolve `chat_id` from `(user_id, thread_id)` via `thread_router.resolve_chat_id()`. If the thread binding is already deleted (race condition during cleanup), the resolution may fail or return a wrong chat_id, leaving Group B state orphaned.

### Late Import Cycles

`cleanup.py` has **8 lazy imports** inside its function body to avoid circular dependencies. Across the handlers package, there are **44+ late imports** indicating 4+ structural dependency cycles:

1. `polling_coordinator` ↔ `polling_strategies` (state vs. domain logic)
2. `text_handler` ↔ `polling_strategies` (cleanup vs. status updates)
3. `command_orchestration` ↔ `message_queue` ↔ `polling_strategies` (status coordination)
4. `shell_capture` ↔ `shell_commands` (fix generation feedback)

### No Enforcement Mechanism

When a developer adds new per-topic state to a new module, there is:

- No test verifying cleanup completeness
- No state registry or central store
- No required cleanup interface
- No static analysis rule

Missing a cleanup registration is a **silent failure** — tests pass, code review may miss it, memory leaks gradually in production.

---

## Architecture Diagram: Current State

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WELL-BOUNDED MODULES                        │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ LLM          │  │ Whisper      │  │ Providers                │  │
│  │ Factory +    │  │ Factory +    │  │ AgentProvider Protocol   │  │
│  │ Protocol     │  │ Protocol     │  │ 4 implementations       │  │
│  │ 0 coupling   │  │ 0 coupling   │  │ JsonlProvider base       │  │
│  └──────────────┘  └──────────────┘  │ Capabilities gating      │  │
│                                       └──────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Callback     │  │ ThreadRouter │  │ Leaf Modules             │  │
│  │ Registry     │  │ 0 imports    │  │ terminal_parser          │  │
│  │ @register    │  │ 19 methods   │  │ screen_buffer            │  │
│  │ self-reg     │  │ clean data   │  │ window_resolver          │  │
│  └──────────────┘  └──────────────┘  │ monitor_state, etc.      │  │
│                                       └──────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│                     IMPROVED BUT IMPERFECT                          │
│                                                                     │
│  ┌──────────────────────────────┐  ┌─────────────────────────────┐ │
│  │ Polling Coordinator (941 ln) │  │ SessionManager (1,476 ln)   │ │
│  │ + Strategies (494 ln)        │  │ 57 methods, 8 concerns      │ │
│  │ Good state ownership         │  │ ThreadRouter extracted ✅    │ │
│  │ 8 encapsulation violations ⚠ │  │ Protocols unused ⚠          │ │
│  └──────────────────────────────┘  └─────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                     PRIMARY REMAINING CONCERN                       │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Fragmented Per-Topic State                                  │    │
│  │ 23 module-level dicts across 9 modules                      │    │
│  │ 5 cleanup gaps (memory/task leaks)                          │    │
│  │ 2 key schemes: (user_id, thread_id) vs (chat_id, thread_id)│    │
│  │ 44+ late imports indicating circular dependencies           │    │
│  │ No enforcement mechanism for new state registration         │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Priority Recommendations

### P0: Fix Cleanup Gaps (Immediate)

Add missing cleanup calls for the 5 identified gaps. Each is a 1-2 line fix in `cleanup.py`:

1. `_send_cooldowns` in `interactive_ui.py`
2. `_generation_counter` in `shell_commands.py`
3. `_bash_capture_tasks` in `text_handler.py` (also cancel the asyncio task)
4. `_topic_create_retry_until` in `topic_orchestration.py`
5. `_disabled_chats` in `topic_emoji.py`

### P1: Consolidate Per-Topic State (Next Refactoring)

Replace 13 independent state dicts with a single `TopicRuntimeState` dataclass:

```python
@dataclass
class TopicRuntimeState:
    status_msg_info: StatusMsgInfo | None = None
    tool_msg_ids: dict[str, int] = field(default_factory=dict)
    interactive_mode: str | None = None
    shell_pending: tuple[str, int] | None = None
    command_history: deque[str] = field(default_factory=deque)
    emoji_state: EmojiState | None = None
    # ... all topic-scoped state in one place
```

One dict, one key scheme, one `del topics[key]` for cleanup. Modules receive their slice as a parameter instead of owning private dicts.

### P2: Fix Polling Strategy Encapsulation

1. Add batch/iteration methods to strategies (eliminate 8 direct `._states` accesses)
2. Move `probe_failures` from `WindowPollState` to `TopicLifecycleStrategy` (eliminate cross-strategy mutation)
3. Remove empty `ShellRelayStrategy` (dead code)

### P3: Resolve Protocols

Either adopt `protocols.py` (wire into handler type annotations) or delete it.

---

## Conclusion

The modularity refactoring was **successful and well-executed**. The improvements are structural, not cosmetic — the callback registry, provider protocol, ThreadRouter extraction, and PromptMatch dataclass all represent genuine reductions in coupling strength and change amplification.

The remaining fragmented state issue is a different class of problem from the original review's concerns. The originals were about **knowledge sprawl** (modules knowing too much about too many domains). The remaining issue is about **state sprawl** (the same conceptual entity scattered across too many dictionaries). Consolidating per-topic state would complete the modularity improvement and directly address the reported feature-addition fragility.

---

_Analysis performed using the [Balanced Coupling](https://coupling.dev) model. Code review based on architectural patterns, git history, and static analysis of imports and state ownership._
