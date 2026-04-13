# Modularity Review — Evening Update

**Scope**: Entire ccgram codebase (incremental review)
**Date**: 2026-04-12 (20:15 GMT+3)
**Context**: Follow-up to the morning review (`modularity-review.md`) after a series of refactors committed today.

## Context and Status of Prior Review

Several issues flagged in the morning review have been partially or fully resolved today. This update tracks the delta and surfaces what remains.

| Prior Issue                                   | Status             | What changed                                                                                                                                                                                                                                         |
| --------------------------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `screenshot_callbacks` — four concerns in one | Partially resolved | Toolbar handlers extracted to `toolbar_callbacks.py`. Screenshot/status/live still live together. Dispatcher cleaned up.                                                                                                                             |
| `/send` intrusive import from `screenshot_cb` | Resolved           | `send_command.open_file_browser()` is now a public API (commit `c9a87a3`).                                                                                                                                                                           |
| SessionManager boundary violations            | Resolved           | `session_resolver.py` now calls `window_store.update_cwd()` / `clear_session_fields()`; `session_map.py` uses `thread_router.set_display_name`.                                                                                                      |
| Business logic in `bot.py`                    | Partially resolved | `handle_new_message` extracted to `message_routing.py`. Topic lifecycle handlers moved to `topic_lifecycle.py`. Screenshot/panes/recall still in bot.py until recently — now in `screenshot_callbacks.py` / `command_history.py` (commit `e676b9d`). |
| Scattered per-window singleton dicts          | Still open         | No change — prior recommendation (`WindowContext` aggregation) stands as a long-term direction.                                                                                                                                                      |
| SessionManager god-object (39 methods)        | Still open         | Surface is stable but handler call counts now quantified (see below).                                                                                                                                                                                |
| Providers ↔ session circular import           | Still open         | Lazy import still in `providers/__init__.py:get_provider_for_window()`.                                                                                                                                                                              |

The prior review remains accurate for anything not touched above. This update focuses on the issues the user explicitly flagged as painful — **adding a provider**, **changing state shape**, and **polling/status code** — and on new cohesion issues surfaced by today's refactors.

## Coupling Overview (delta)

| Integration                                                         | Strength                  | Distance | Volatility | Balanced?                                                   |
| ------------------------------------------------------------------- | ------------------------- | -------- | ---------- | ----------------------------------------------------------- |
| Handlers → `session_manager` (25 handlers, 62 direct calls)         | Functional + Model        | Low      | High       | Borderline — read-heavy but no projection type              |
| `polling_coordinator.status_poll_loop` → 9 handler modules          | Functional + temporal     | Low      | High       | Balanced by the rule, **low cohesion** inside the module    |
| Provider abstraction leaks (`base.py`, `shell.py`, `summarizer.py`) | Model + Intrusive         | Low      | High       | **No** — handlers bypass the protocol in several paths      |
| `hook_events` ↔ `message_queue` (circular)                          | Functional                | Low      | Moderate   | Yes mechanically, **No** logically — signals misplaced code |
| `shell_commands` ↔ `shell_capture` (mutual)                         | Functional                | Low      | Moderate   | Yes mechanically, **No** logically — same signal            |
| `message_queue.py` (1184 lines, 6 concerns)                         | Internal (mixed)          | —        | Moderate   | Cohesion problem, not cross-module coupling                 |
| Module-level singletons + deferred `_schedule_save` wiring          | Implicit (globals)        | Low      | Low        | Yes — but blocks isolated testing                           |
| Duplicated `session_map` logic (`session.py` ↔ `session_map.py`)    | N/A — literal duplication | —        | Low        | N/A — incomplete refactor, not a design issue               |

## Issue 1: Provider Abstraction Leaks (adding providers hurts)

**User pain**: "Adding a provider is painful — it touches too many places."
**Severity**: Significant
**Why**: The provider protocol is correct in principle but leaks in four specific places. Each leak means a new provider has to be plumbed into code that should be provider-agnostic.

### Knowledge leakage

1. **`providers/base.py` contains Telegram-specific constants.** `EXPANDABLE_QUOTE_START`, `EXPANDABLE_QUOTE_END`, and `format_expandable_quote()` are Telegram blockquote syntax. The docstring admits this. A pure protocol layer should know nothing about Telegram formatting.

2. **`providers/shell.py` exports module-level infrastructure, not just the provider class.** `match_prompt`, `setup_shell_prompt`, `detect_pane_shell`, `KNOWN_SHELLS`, `PromptMatch` are consumed directly by handlers (`shell_commands`, `transcript_discovery`, `window_callbacks`, `directory_callbacks`). `ShellProvider` the class is 42 lines; the surrounding module is ~300 lines of infrastructure that bypasses the provider abstraction. A future Aider or Cursor provider with similar per-provider setup logic will have no blueprint to follow.

3. **`llm/summarizer.py` hardcodes Claude JSONL format.** It parses `type=assistant/user`, `message.content[]` blocks with `type=tool_use/tool_result/text` directly — not through `AgentProvider.parse_transcript_entries()`. This means completion summaries only work for Claude. If Codex/Gemini ever need summaries, this becomes a copy-paste fork.

4. **`providers/claude.py` imports `ccgram.hook.UUID_RE`.** Session-id validation regex lives in the hook module, not in `base.py`. `RESUME_ID_RE` _is_ in `base.py` — `UUID_RE` should be too (or the same pattern should be reused).

5. **Handlers check provider names as strings.** `transcript_discovery`, `recovery_callbacks`, and `window_callbacks` branch on `provider_name == "shell"` / `"claude"`. This is model coupling that capability flags were meant to eliminate.

### Complexity impact

Adding a new provider requires touching: (a) the registry, (b) a new file in `providers/`, and in the current code also (c) the shell-infrastructure pattern if the provider needs any launch-time setup, (d) summarizer if summaries are wanted, (e) handlers that string-match provider names, and (f) base.py if the protocol needs new capability flags. That is a wider surface than the protocol suggests.

### Cascading changes

A change to how any provider reports status propagates into handler code that expected Claude-specific semantics. The capability matrix partly insulates this (`supports_hook`, `supports_status_snapshot`), but some handlers still assume Claude-shaped behavior silently.

### Recommended improvement

Practical, in order of ratio of payoff to cost:

1. **Move `EXPANDABLE_QUOTE_*` and `format_expandable_quote()` out of `providers/base.py`** into a new `telegram_formatting.py` (or into existing `handlers/message_sender.py`). Thirty-minute change. Removes one protocol boundary violation.
2. **Move `UUID_RE` into `providers/base.py`** alongside `RESUME_ID_RE`. Fifteen-minute change. Removes `claude.py → hook` dependency.
3. **Grep for `provider_name ==` and `== "shell"` / `== "claude"` across handlers.** Each hit is either a capability-flag miss or a handler that should delegate to the provider. Add capability flags as needed and replace string checks.
4. **Extract `providers/shell_infra.py`** (or rename current `shell.py` to `shell_infra.py` and create a slim `shell.py` for just `ShellProvider`). Makes the handler surface clear: handlers import from `shell_infra`, provider registry imports from `shell`. Establishes a pattern for future providers with launch-time setup.
5. **Route `summarizer.py` through the provider** — add `AgentProvider.summarize_recent(entries) -> list[str]` (returning the compact lines summarizer builds now). Only Claude needs to implement it initially; others can return `[]`. This removes one of the two remaining hardcoded-Claude paths.

Don't attempt all five at once. The first two are cheap wins; the others can happen opportunistically when you next add a provider.

## Issue 2: polling_coordinator is a God Loop

**User pain**: "Polling/status code is hard to follow."
**Severity**: Significant
**Why**: `status_poll_loop` is a 1-second loop that orchestrates ten concerns in sequence: terminal status update, pane scanning, passive shell output capture, RC debounce, unbound TTL, dead detection, autoclose, periodic broker delivery, live view ticking, transcript discovery, topic emoji sync. The coordinator imports nine other handler modules to do this.

### Knowledge leakage

The coordinator knows what order things must happen in, what arguments each strategy needs, and how to mix per-tick strategies with time-gated tasks (`run_periodic_tasks`, `run_lifecycle_tasks`). Adding a new concern means editing the coordinator — and knowing where in the loop to insert it, because ordering matters (e.g., transcript discovery must precede status scanning).

By the Balance Rule, "high strength + low distance" is _nominally_ balanced: everything is in the same package, so co-location handles the tight coupling. But the coordinator's internal cohesion is low — ten unrelated concerns share one function scope. The pain the user feels isn't a cross-module issue; it's an **internal low-cohesion** issue masquerading as organization.

### Complexity impact

A developer trying to understand "when does interactive UI get refreshed?" must read the coordinator's main loop and trace through four handler imports to find the real logic. A bug in pane scanning (say, missing probe failures on transient tmux errors) requires loading the full 598-line coordinator into working memory because its error handling is woven through every section.

### Cascading changes

Any new per-window concern (new subagent tracking, new external event source) either (a) gets bolted into `status_poll_loop` at the "right" place, further growing the god function, or (b) gets its own async task started in `post_init`, which fragments the polling architecture. The current refactor path (extracting strategy classes into `polling_strategies.py`) is correct but stops halfway: state was extracted, but orchestration wasn't.

### Recommended improvement

Invert control without introducing a framework. Concrete steps:

1. Give each strategy a `tick(tick_ctx)` async method. `TerminalStatusStrategy.tick()` does today's terminal work; `InteractiveUIStrategy.tick()` handles interactive refresh; `TopicLifecycleStrategy.tick()` handles autoclose and TTL.
2. Replace the inlined per-binding loop in `status_poll_loop` with a list of registered strategies and a dispatcher that calls `strategy.tick(ctx)` for each. Each strategy decides for itself whether this tick is relevant (time-gated or always).
3. Move `run_periodic_tasks` / `run_lifecycle_tasks` contents into strategy `tick()` methods where they belong.

This doesn't change the 1-second cadence. It doesn't introduce dependency injection or a scheduler library. It makes `polling_coordinator.py` shrink to ~100 lines (the loop, error handling, cancellation) and moves the actual work into the strategy classes that already exist. Adding a new polling concern becomes "add a new strategy class, register it" instead of "edit the god loop."

The tradeoff: strategies need a common `tick_ctx` type (bot, timestamps, maybe active binding). That type already partially exists implicitly in the local variables of `status_poll_loop`. Making it explicit is a small cost for a large cohesion win.

## Issue 3: `message_queue.py` mixes six concerns (1184 lines)

**Severity**: Significant
**Why**: This file owns per-user FIFO queues, the worker task, message merging / batching, the pinned status-bubble rendering, tool_use↔tool_result pairing, and the status inline keyboard builder. Any one of these would be a fine module.

### Knowledge leakage

`build_status_keyboard(...)` — a UI concern — lives in the same module as queue management, a state concern. `live_view.py` imports `screenshot_callbacks.build_screenshot_keyboard`, and now `screenshot_callbacks` imports `message_queue.build_status_keyboard`. Keyboard builders are scattered across three modules with no unifying location.

The circular import `hook_events ↔ message_queue` exists because `message_queue` needs `build_subagent_label` and `get_subagent_names` from `hook_events`, and `hook_events` needs `enqueue_status_update` from `message_queue`. Neither function belongs where it lives: subagent labels are metadata about `claude_task_state`, not hook events; `enqueue_status_update` is a queue primitive used from every handler.

### Recommended improvement

1. **Extract `status_bubble.py`** with `build_status_keyboard`, status-bubble edit/send logic, and text rendering. Import it from `message_queue` and from `polling_strategies`/`hook_events`.
2. **Move `build_subagent_label` and `get_subagent_names` into `claude_task_state.py`** (or into `status_bubble.py`). Both functions are about presenting task-tracking state; they don't belong in the hook-event dispatcher. This breaks the circular import.
3. **Leave queue primitives in `message_queue.py`** — the FIFO, worker, merge, and rate-limit logic is naturally cohesive. After extraction it should be ~400–500 lines instead of 1184.

Not every separation is worth pursuing. Keep message merging and tool_use/tool_result pairing inside `message_queue` — they're tightly bound to queue ordering. The goal is to pull out the two concerns (status bubble UI, subagent metadata) that don't belong.

## Issue 4: Circular Dependencies Signal Misplaced Code

**Severity**: Minor (mechanical) / Moderate (as signal)
**Why**: Python's module cache makes circular imports work at runtime, but each circle is a hint that the logical decomposition is wrong.

Two circles exist:

1. `handlers/hook_events.py` ↔ `handlers/message_queue.py`. Addressed by Issue 3's subagent label extraction.
2. `handlers/shell_commands.py` ↔ `handlers/shell_capture.py`. `shell_commands` owns command approval / LLM generation / redaction; `shell_capture` owns passive output monitoring and prompt-match parsing. They mutually import: `shell_commands` calls `mark_telegram_command`; `shell_capture` calls `gather_llm_context`, `redact_for_llm`, and `show_command_approval`.

The second circle is structurally sound — these two modules are effectively one subsystem (the shell-provider UX layer) that was split for file-size reasons. The mutual imports make the pretend-separation visible.

### Recommended improvement

For the shell pair: extract a shared `shell_context.py` with `gather_llm_context`, `redact_for_llm`, `mark_telegram_command`, and the pending-command tracking dicts. Both `shell_commands` (approval flow) and `shell_capture` (output relay) depend on `shell_context` but not on each other. This breaks the circle and makes the split meaningful.

For the hook_events pair: handled by Issue 3.

## Issue 5: SessionManager — Write Surface Is Wider Than It Needs To Be

**User pain**: "State shape changes cascade to 25+ handlers."
**Severity**: Significant (re-scoped from morning review's "Minor")
**Why**: The morning review called this Minor because at solo-dev distance, IDE refactoring tools handle the ripple. The user's pain report suggests the real issue is not the number of call sites but the **shape of what handlers touch**.

### Knowledge leakage

Quantified: 25 handlers, 62 direct calls. The widest consumers are `sync_command` (10), `transcript_discovery` (7), `recovery_callbacks` (6), `resume_command` (5), `polling_coordinator` (5), `restore_command` (5). These are all legitimate — they're the handlers that actually manage window lifecycle.

But many consumers have exactly one call that returns a `WindowState` and reads a single field:

- `file_handler` — reads `cwd`
- `history` — reads `transcript_path` (via `get_recent_messages`)
- `shell_commands` — reads `cwd`
- `text_handler` — reads `cwd`
- `send_command` — reads `cwd`
- `screenshot_callbacks` — reads `notification_mode` (via `cycle_notification_mode`)
- `topic_emoji` — reads `approval_mode`

These handlers import `session_manager` for a one-field read, which means they depend on the whole facade shape for no reason.

### Complexity impact

Changing `WindowState` shape — renaming `cwd` to `working_dir`, splitting `approval_mode` into a tuple, making `provider_name` an enum — cascades to every handler that happened to read that field, even if they only consume one value. The handlers don't actually depend on `SessionManager`; they depend on a specific scalar.

### Recommended improvement

Don't split `SessionManager`. Instead, introduce a read-only **window view** type:

```python
@dataclass(frozen=True)
class WindowView:
    window_id: str
    cwd: str
    provider_name: str
    approval_mode: str
    notification_mode: str
    transcript_path: Path | None
```

Add `session_manager.view_window(wid) -> WindowView | None` that returns a snapshot at call time. Handlers that need read-only access migrate from `get_window_state` to `view_window`. This gives:

- **An explicit projection contract.** Changing `WindowState` internals (renaming `cwd`) doesn't cascade if the view's field name is preserved via a computed property.
- **A testability win.** Tests can construct `WindowView` literals instead of wiring `WindowStateStore`.
- **No behavior change.** `get_window_state` stays for the handlers that actually need to mutate.

This is an incremental refactor — migrate one handler at a time. It addresses the cascade-change pain without a full DI rewrite. It is not overengineering because the type captures what handlers already read today.

## Issue 6: Duplicated `session_map` Logic

**Severity**: Minor (technical debt, not a design issue)
**Why**: `session.py` still contains full copies of `load_session_map`, `register_hookless_session`, `write_hookless_session_map`, `prune_session_map` that also exist in `session_map.py`. The extraction was incomplete.

### Recommended improvement

Delete the copies in `session.py`. `SessionManager` methods should be thin delegators to `session_map.session_map_sync.<method>()`. The risk is zero — both implementations should behave identically today; if they diverge, one is a bug. Verify with tests, then delete.

## Issue 7: Deferred `_schedule_save` Wiring Is a Silent-Failure Trap

**Severity**: Minor
**Why**: Four module-level singletons (`window_store`, `thread_router`, `user_preferences`, `session_map_sync`) initialize with `_schedule_save = lambda: None`. `SessionManager.__post_init__()` replaces them. Tests that mutate state without first instantiating `SessionManager` silently lose the save path — the mutation happens in memory but the wiring-to-persistence is a no-op.

This isn't a coupling issue in the Balanced Coupling sense, but it compounds the testability pain the user flagged. A test that wants to verify `window_store.update_cwd()` triggers a save must remember to create a `SessionManager` first.

### Recommended improvement

Two cheap changes:

1. **Replace `_schedule_save = lambda: None` with `_schedule_save: Callable | None = None`** and raise `RuntimeError("SessionManager not initialized")` on call. Tests that forget wiring fail loudly instead of silently.
2. **Document the wiring in a single place** — a comment at the top of `session.py`'s `__post_init__` listing all wiring, or a `wire_singletons(sm)` helper function called from `__post_init__`. Currently the wiring is spread across six `self.X._schedule_save = ...` lines that are easy to miss when adding a new singleton.

No DI framework. No test-scoped resets. Just fail-loud defaults and visible wiring.

## Priority Ranking (Practical)

**Do first — high payoff, low cost** (1–2 days of focused work each):

1. Move `EXPANDABLE_QUOTE_*` and `UUID_RE` out of `providers/base.py` / `providers/claude.py`. Cheap wins, removes two protocol violations.
2. Delete `session_map` duplicates from `session.py`. Pure cleanup.
3. Extract `status_bubble.py` and move subagent label helpers out of `hook_events`. Breaks one circular import, shrinks `message_queue.py`.
4. Fail-loud `_schedule_save` defaults. Ten-line change that prevents a whole class of silent test bugs.

**Do when touching the affected code**:

5. Introduce `WindowView` and migrate handlers opportunistically. Start with the seven one-call-read handlers; don't attempt full migration.
6. Extract `shell_context.py` and break the shell circular import.
7. Replace handler `provider_name ==` string checks with capability flags as they're encountered.

**Do before the next big feature in that area**:

8. Invert `polling_coordinator` into strategy-owned `tick()` methods. Worth it before adding any new polling concern.
9. Extract `providers/shell_infra.py` before adding the next provider that needs launch-time setup.

**Don't do**:

- Splitting `SessionManager` into multiple classes. The god-object pattern is tolerable at solo-dev distance; the fix (WindowView) addresses the real pain without structural upheaval.
- Full dependency injection framework. The deferred-wiring pattern is awkward but not broken, and DI would add ceremony that doesn't pay back for a single maintainer.
- A full `WindowContext` aggregation for scattered per-window state (morning review's primary recommendation). It remains a real issue but is a multi-week refactor; address the higher-payoff issues above first.
- Decomposing into separate services or packages. Single process, single machine, single maintainer.

## Summary

Today's refactors (toolbar extraction, message_routing extraction, public `open_file_browser`, window-state encapsulation, `IDLE_STATUS_TEXT` relocation) resolved or partially resolved five of the six issues from the morning review. The remaining work concentrates in three specific places:

- **Provider abstraction leakage** — the protocol is sound; the leaks are small and fixable individually.
- **Polling coordination** — internal low cohesion, not cross-module coupling. Invert without ceremony.
- **SessionManager write surface** — not a god-object problem, a projection-type problem. WindowView solves it.

None of these require large structural rewrites. All are incremental refactors that improve testability and cohesion without increasing effective distance. The morning review's recommendation to aggregate scattered per-window state into `WindowContext` is still valid but lower-priority than the three items above.

---

_This analysis uses the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com). See the morning review (`modularity-review.md`) for integration tables and the prior baseline analysis._
