# Modularity Review

**Scope**: ccgram (`src/ccgram/`) — post-Round-4 design audit. Branch `modularity-decouple-round-4`. ~42 KLOC, 14 handler subpackages, 5 agent providers, 2 LLM providers, optional Mini App.
**Date**: 2026-05-01

ccgram is a Telegram bot that drives AI coding agents (Claude Code, Codex, Gemini, Pi, plain shell) inside tmux windows; each Forum topic binds to one window and one agent session. Round 4 (the 6-phase refactor that just landed on this branch) addressed every finding from the 2026-04-29 review (F1–F6: handler subpackages, constructor DI for stores, `bot.py` split, `window_tick` decide/observe/apply, `TelegramClient` Protocol, lazy-import audit). The result is **good bones, narrower context per task, but four residual hot spots** that account for most of the remaining cross-module churn: a stateful "polling strategies" hub that doubles as the canonical home for pure decision types, two oversized handler files (`command_orchestration.py` 775 LOC, `recovery_callbacks.py` 890 LOC), the surviving module-level singleton pattern (now wrapped in proxies but still global), and a residual lazy-import gap (~89 in-function imports without the Round-4 documentation comment).

## What Round 4 Already Bought You

These are no longer issues; do not re-litigate them.

- `bot.py` is 172 lines (factory + lifecycle delegates). Command/message/callback registration moved to `handlers/registry.py`. Post-init wiring lives in `bootstrap.py` with named, individually testable steps and an explicit ordering invariant (`wire_runtime_callbacks` must precede `start_session_monitor`).
- The 50+ flat `handlers/` peers became 14 cohesive feature subpackages (interactive, live, messaging, messaging_pipeline, polling, recovery, send, shell, status, text, toolbar, topics, voice) plus 17 documented top-level handlers. Each subpackage `__init__.py` is a small re-export surface (19–104 lines).
- `WindowStateStore`, `ThreadRouter`, `UserPreferences`, and `SessionMapSync` are constructed by `SessionManager` with explicit `schedule_save` callbacks. The `_wire_singletons` monkey-patch is gone; unwired callee defaults raise `RuntimeError("not wired")`; `register_*_callback` helpers fail loud on double registration.
- `window_tick` is now a four-file subpackage: `decide.py` (70 LOC, pure kernel, zero deps on tmux/PTB/singletons), `observe.py` (126 LOC, pure inputs in / `TickContext` out), `apply.py` (554 LOC, the only side-effect file), `__init__.py` (133 LOC orchestration shim).
- `TelegramClient` Protocol covers exactly the 18 grep-verified bot API methods used by handlers. `PTBTelegramClient(bot)` adapts a real PTB Bot in production; `FakeTelegramClient` records calls as `(method, kwargs)` tuples for tests; `unwrap_bot(client)` is the documented escape hatch for PTB-only helpers (`do_api_request` for `DraftStream`).
- A new integration test (`tests/integration/test_import_no_cycles.py`) parametrizes `python -c "import {module}"` over 29 modules from a clean interpreter, catching circular-import regressions before they break runtime.

## Domain Classification

Largely unchanged from the prior review; the deltas worth noting are that messaging and Mini App have settled into supporting/core respectively, and that polling has emerged as a [core subdomain](https://coupling.dev/posts/dimensions-of-coupling/volatility/) in its own right (every UX iteration touches it).

| Subsystem                            | Type       | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | Comment                                                                                  |
| ------------------------------------ | ---------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Telegram UX (`handlers/`)            | Core       | High                                                                        | Where competitive value lives. Topic emoji, status bubble, recovery, voice still moving. |
| Provider abstraction (`providers/`)  | Core       | High                                                                        | 5 providers in 6 months; capability matrix continues to grow.                            |
| Polling / status detection           | Core       | High                                                                        | Hook + scrape + lifecycle interleaved; touched by every recent UX overhaul.              |
| Inter-agent messaging (`mailbox/`)   | Core       | Medium                                                                      | Stabilising; new spawn flow + idle detection.                                            |
| Mini App (`miniapp/`)                | Core       | High                                                                        | New in v3.0; HTTP/WS surfaces still expanding.                                           |
| Session monitoring                   | Supporting | Medium                                                                      | Hooks vs hookless variants; events.jsonl surface stable.                                 |
| State persistence                    | Supporting | Low                                                                         | `state.json` schema is stable; forward-compat by design.                                 |
| tmux integration (`tmux_manager.py`) | Generic    | Low                                                                         | tmux + libtmux APIs are static.                                                          |
| Telegram client (PTB)                | Generic    | Low                                                                         | API stable; F5 reduced exposure to outbound surface only.                                |
| LLM / Whisper                        | Generic    | Low (functional)                                                            | OpenAI-compatible HTTP shape; pluggable via Protocol.                                    |

## Coupling Overview

The integrations below are the hot edges in the post-Round-4 graph — pairs where a change in one component is likeliest to ripple. [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) levels in the cells are linked to the relevant chapter.

| Integration                                                                                                             | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)              | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `polling_strategies.py` 5 module-level singletons → 12+ call sites                                                      | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | sibling (mostly via lazy import)                                        | medium                                                                      | ❌ singleton hub                                               |
| `decide.py` (pure) → `polling_strategies.py` for `TickContext`/`STARTUP_TIMEOUT`/`is_shell_prompt`                      | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | sibling                                                                 | low                                                                         | ⚠ pure kernel still drags 1 073-line stateful module           |
| `command_orchestration.py` — 4 jobs in one 775-LOC file (forward + menu sync + failure probe + status snapshot)         | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)            | same module                                                             | medium                                                                      | ❌ low cohesion                                                |
| `recovery_callbacks.py` — dispatcher + 6 handlers + 3 keyboard builders + 2 scan helpers (890 LOC)                      | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)            | same module                                                             | medium                                                                      | ❌ low cohesion                                                |
| handlers/\* → `session_manager` (44 sites) vs `window_query`/`session_query` (30 sites)                                 | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (mixed)    | sibling                                                                 | medium                                                                      | ⚠ two access patterns coexist                                  |
| handlers/\* → `window_store`/`thread_router`/`user_preferences` (proxy globals)                                         | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | sibling                                                                 | medium                                                                      | ⚠ proxy hides "wired vs unwired" failure mode                  |
| Tests → `bootstrap.reset_for_testing()` + 3 separate `_reset_*_for_testing` hooks                                       | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)             | external (test → src)                                                   | medium                                                                      | ❌ singleton-reset ceremony                                    |
| Lazy-import sites (~89 undocumented out of 222 total)                                                                   | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (latent)    | sibling                                                                 | medium                                                                      | ❌ hidden cycles                                               |
| `bot.py` `__all__` re-exports of 19 moved symbols (test-patch targets)                                                  | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | same module                                                             | medium                                                                      | ⚠ load-bearing for legacy `unittest.mock.patch`                |
| Handlers → `telegram.{Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, MessageEntity}` (inbound + UI) | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                 | 3rd-party                                                               | low                                                                         | ✅ tolerable per balance rule                                  |
| `TelegramClient` Protocol → 18 outbound bot API methods                                                                 | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)              | sub-package                                                             | low                                                                         | ✅ exemplary                                                   |
| `miniapp/` → rest of ccgram (only via its own `auth` module)                                                            | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)              | sub-package                                                             | high                                                                        | ✅ best-isolated subsystem in the codebase                     |
| `AgentProvider` Protocol → 5 implementations + capability flags                                                         | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)              | sub-package                                                             | high                                                                        | ✅ unchanged from prior review; remains the gold standard      |
| `bootstrap.py` post_init → 7 wiring steps with ordering invariant                                                       | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (necessary) | sibling                                                                 | high                                                                        | ✅ now named + asserted (`_callbacks_wired` flag)              |

## Issues

The four critical ones below are unbalanced **and** sit in volatile parts of the codebase. The two significant ones are unbalanced in medium-volatility areas. The minors are tolerable per the [balance rule](https://coupling.dev/posts/core-concepts/balance/) — listed for completeness, not for immediate work.

## Issue: `polling_strategies.py` is a hidden singleton hub

**Integration**: `handlers/polling/polling_strategies.py` -> 12+ lazy importers across `recovery/`, `shell/`, `topics/`, `status/`, `live/`, `text/`, `window_tick/decide.py`
**Severity**: <span class="severity severity-critical">Critical</span>

### Knowledge Leakage

`polling_strategies.py` is 1 073 lines and contains **two unrelated kinds of thing in one module**: (a) the pure data types `TickContext`, `TickDecision`, `PaneTransition`, the constant `STARTUP_TIMEOUT`, and the pure function `is_shell_prompt` — i.e. the contract that the F4 decision kernel was meant to be pure with respect to — and (b) five stateful module-level singletons: `terminal_poll_state`, `terminal_screen_buffer`, `interactive_strategy`, `lifecycle_strategy`, `pane_status_strategy`.

The F4 win in `window_tick/decide.py` ("zero deps on tmux/PTB/singletons") is accurate at the _decision-function_ level — `decide_tick(ctx) -> TickDecision` is a deterministic mapping. But the import graph tells a different story: `decide.py` does `from ..polling_strategies import STARTUP_TIMEOUT, TickContext, TickDecision, is_shell_prompt`, which _executes_ `polling_strategies.py` top-level at import time — instantiating all five singletons (pyte screen, RC debounce dict, pane-count cache, autoclose-timer dict, dead-notification set). The pure kernel is only pure once it's loaded; loading it is not.

This is [model coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) where it should be [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/). Twelve other call sites compound the problem: most of them use `from ..polling.polling_strategies import lifecycle_strategy` (or `terminal_screen_buffer`, or `interactive_strategy`) **inside function bodies** as the documented workaround for the cycle this would otherwise create. That's eight `# Lazy:` comments admitting the same architectural fact.

### Complexity Impact

Any change inside `polling_strategies.py` — adding a debounce field, renaming a method on `TerminalScreenBuffer`, tweaking `STARTUP_TIMEOUT` — has potential ripple into ≥12 sibling modules, most of which discovered the dependency _late at import time_. Cognitive load on a developer reading `decide.py`: small ✓. Cognitive load on a developer reading `polling_strategies.py`: 8 classes, 5 instances, 2 distinct-concept clusters, 1 073 lines — well past the 4 ± 1 working-memory budget.

The "lazy import everywhere" pattern means the static module graph lies: tooling sees `decide.py → polling_strategies` only, while the runtime graph fans out through every consumer of the singletons. That's the "hidden cycles" half of the problem the F6 audit was supposed to surface; it's still there, just better-commented.

### Cascading Changes

Concrete recent triggers (from `git log` of this file):

- "Pane lifecycle transition notifications distinguish creation from state changes" — a UX tweak that touched `PaneStatusStrategy` _and_ `recovery_callbacks.py` _and_ `live/screenshot_callbacks.py` because all three lazy-import a singleton from this file.
- The F4 split itself documented two cycle paths through `polling_strategies` (`window_tick → recovery → polling_strategies → window_tick` and a sibling); they were "fixed" by _forcing_ the import order in `handlers/registry.py` (the `from . import polling as _polling  # noqa: F401` line). That comment-bound import-ordering invariant is unbalanced coupling: a refactor of `polling/__init__.py` can break recovery loading without any local edit.

### Recommended Improvement

Split the file into two siblings inside `handlers/polling/`:

- `polling_types.py` — pure types and constants only: `TickContext`, `TickDecision`, `PaneTransition`, `STARTUP_TIMEOUT`, `RC_DEBOUNCE_SECONDS`, `MAX_PROBE_FAILURES`, `TYPING_INTERVAL`, `PANE_COUNT_TTL`, `ACTIVITY_THRESHOLD`, `SHELL_COMMANDS`, `is_shell_prompt`, `WindowPollState` and `TopicPollState` dataclasses (they are state holders but have no I/O). Total target: ~150 LOC.
- `polling_state.py` — the five stateful classes (`TerminalPollState`, `TerminalScreenBuffer`, `InteractiveUIStrategy`, `TopicLifecycleStrategy`, `PaneStatusStrategy`) and the five singletons. Constructor-inject the dependencies they share (most already do internally).

Then `decide.py` imports only from `polling_types.py`, eliminating the load-side effect for the pure kernel and making the F4 purity claim true at the import level too. The 12 lazy-import sites for the singletons stay lazy if they still need to (or, better, pass the strategy in via `apply.py`-style DI), but they no longer share a file with the contract.

**Trade-off**: ~1 day of mechanical work, ~30 import sites updated, no behaviour change. Risk is low; cycle-detection test will catch regressions. The payoff is that the F4 architecture finally pays its full dividend — `decide.py` becomes truly leaf-level and unit-testable without instantiating pyte buffers.

## Issue: `command_orchestration.py` packs four unrelated jobs into 775 LOC

**Integration**: internal cohesion of `handlers/command_orchestration.py`
**Severity**: <span class="severity severity-critical">Critical</span>

### Knowledge Leakage

The module name suggests one job (orchestrating slash-command forwarding); the file does four:

1. **Forward unknown `/commands` to the agent session** (`forward_command_handler`, ~110 LOC). The actual orchestration.
2. **Per-user / per-chat / global menu sync** (`sync_scoped_provider_menu`, `sync_scoped_menu_for_text_context`, `get_global_provider_menu`, `set_global_provider_menu`, `setup_menu_refresh_job`). State management for `BotCommandScope*`.
3. **Post-send command-failure probing** (`_capture_command_probe_context`, `_probe_transcript_command_error`, `_maybe_send_command_failure_message`, `_spawn_command_failure_probe`, `_extract_pane_delta`, `_extract_probe_error_line`, `_command_known_in_other_provider`). A separate concern — verifying that the agent actually accepted the command — that runs _after_ forwarding.
4. **Status / stats snapshot fallback** (`_status_snapshot_probe_offset`, `_maybe_send_status_snapshot`). A different feature entirely (showing `/status` output even when the agent doesn't understand the command).

These four jobs share file scope but not domain knowledge: changing menu-scope cache keys does not affect failure-probe extraction logic, and vice versa. This is low cohesion in the [classic-coupling](https://coupling.dev/posts/related-topics/module-coupling/) sense — coincidental grouping by surface ("things that involve `/commands`") rather than by reason-to-change.

### Complexity Impact

Two specific costs visible in the recent git history:

- The bounded-cache helpers `_set_bounded_cache_entry` and `_get_lru_cache_entry` were added at the top of the file _for menu sync_, but anyone reading the file top-to-bottom encounters 200 LOC of generic OrderedDict utilities before reaching the actual command-forwarding logic at line 564.
- The probe-spawn pattern (`_spawn_command_failure_probe` + `_status_snapshot_probe_offset`) creates `asyncio.Task`s inside the forward path. Cancellation, ordering, and status-bubble-edit interactions are non-obvious and require the reader to hold all four jobs in working memory simultaneously.

### Cascading Changes

- A change to "what counts as a failed command" (e.g. detecting Codex's "command not recognized" string vs Claude's silent ignore) currently touches the probe code, the menu-sync code (because the menu may need to be re-fetched), and forward_command_handler (to orchestrate). Three concerns, one file.
- Adding a new provider whose menu requires a different scope mechanism forces the menu-sync code to grow — but the menu-sync helpers live next to the probe code, so the diff is wider than the change deserves.

### Recommended Improvement

Split into a sibling subpackage `handlers/commands/`:

- `commands/forward.py` — `forward_command_handler` and its small helpers. The actual entry point. ~150 LOC.
- `commands/menu_sync.py` — `sync_scoped_provider_menu`, scope cache, `setup_menu_refresh_job`. ~250 LOC.
- `commands/failure_probe.py` — pane-delta and transcript-based failure detection. ~200 LOC.
- `commands/status_snapshot.py` — `/status` and `/stats` snapshot fallback. ~120 LOC.
- `commands/__init__.py` — re-export public symbols (`forward_command_handler`, `commands_command`, `toolbar_command`, `setup_menu_refresh_job`, `get_global_provider_menu`, `set_global_provider_menu`).

This is the same shape as the existing `shell/` subpackage (`shell_commands` + `shell_capture` + `shell_context` + `shell_prompt_orchestrator`), where the cohesion-by-feature pattern already works.

**Trade-off**: ~half a day of mechanical work; one git-history-aware reviewer to make sure each split file's docstring is accurate. Behaviour unchanged. Payoff: the menu-sync logic and failure-probe logic become independently reviewable, and the next provider that demands a different command surface only touches `forward.py`.

## Issue: `recovery_callbacks.py` is the largest handler at 890 LOC and conflates two unrelated UX flows

**Integration**: internal cohesion of `handlers/recovery/recovery_callbacks.py`
**Severity**: <span class="severity severity-critical">Critical</span>

### Knowledge Leakage

The file pairs two distinct UX surfaces:

1. **Dead-window recovery banner** — `RecoveryBanner` dataclass, `render_banner`, `_recovery_help_text`, `build_recovery_keyboard`, `_handle_back`, `_handle_fresh`, `_handle_continue`, `_handle_resume`, `_handle_browse`, `_handle_cancel`. Triggered when a window dies and the topic is orphaned.
2. **Resume picker** — `_SessionEntry`, `scan_sessions_for_cwd`, `_scan_index_for_cwd`, `_scan_bare_jsonl_for_cwd`, `_build_resume_picker_keyboard`, `_build_empty_resume_keyboard`, `_send_empty_state`, `_handle_resume_pick`. Triggered from `/resume` _or_ from the recovery banner's "Resume" button.

The two share a callback-data namespace and a `_validate_recovery_state` helper, but they have different state machines, different keyboard layouts, and different test surfaces. The shared dispatcher (`_dispatch`, `handle_recovery_callback`) is what justifies co-location, and it's ~50 LOC. The remaining ~840 LOC are the two flows.

This is [low-cohesion / model coupling](https://coupling.dev/posts/related-topics/module-coupling/) — the file groups by callback-prefix (`rc:`) rather than by reason-to-change. A change to how the resume picker paginates does not affect the banner; a change to what the banner offers when no transcript exists does not affect the picker.

### Complexity Impact

- New contributors lose ~5 minutes finding which `_handle_*` belongs to which flow. Reviewer cognitive load is roughly doubled vs two ~450-LOC files.
- Test files are correspondingly large; mocking `scan_sessions_for_cwd` in a banner test is non-obviously unnecessary (banner code never calls it).

### Cascading Changes

- The Round-4 follow-up that added the empty-state UX to the resume picker (`_send_empty_state`, `_build_empty_resume_keyboard`) was a banner-side innovation that bled into picker code because the two share `_dispatch`. Three call sites needed adjustment when the banner gained the "Browse" affordance — none of which were in resume-picker code, but all of which had to be edited in the same file.

### Recommended Improvement

Split into two siblings inside `handlers/recovery/`:

- `recovery_banner.py` — `RecoveryBanner`, `render_banner`, `build_recovery_keyboard`, `_handle_back/_fresh/_continue/_resume/_browse/_cancel`. ~450 LOC.
- `resume_picker.py` — `_SessionEntry`, scan helpers, `_build_resume_picker_keyboard`, `_send_empty_state`, `_handle_resume_pick`. ~400 LOC.
- `recovery_callbacks.py` shrinks to ~80 LOC: the dispatcher (`_dispatch`, `handle_recovery_callback`), `_validate_recovery_state`, and `_clear_recovery_state` — the genuinely shared state machine.

The `recovery/` `__init__.py` re-exports stay the same, so external call sites are unaffected.

**Trade-off**: ~half a day. The picker scan helpers (`scan_sessions_for_cwd`, `_scan_index_for_cwd`, `_scan_bare_jsonl_for_cwd`) are imported by `resume_command.py` already — moving them into `resume_picker.py` keeps the import path inside the subpackage. Behaviour unchanged. Payoff: the resume-picker pagination work that's already on the backlog (per CLAUDE.md UX overhaul history) lands in one ~400-LOC file instead of touching the largest handler in the codebase.

## Issue: Module-level singletons survived as proxies, with a 3-step test-reset ceremony

**Integration**: `WindowStateStore` / `ThreadRouter` / `UserPreferences` / `SessionMapSync` (proxies) ↔ `bootstrap.reset_for_testing()` + 3 separate `_reset_*_for_testing` hooks
**Severity**: <span class="severity severity-significant">Significant</span>

### Knowledge Leakage

F2 successfully replaced `_wire_singletons()` monkey-patching with constructor injection inside `SessionManager`, and it added the loud-failing `register_*_callback` helpers. But the module-level globals `window_store`, `thread_router`, `user_preferences`, and `session_map_sync` did not go away — they became proxy objects (`_WindowStoreProxy`, `_ThreadRouterProxy`, etc.) that forward attribute access to the wired instance:

```python
# window_state_store.py
_active_store: WindowStateStore | None = None
window_store: WindowStateStore = cast("WindowStateStore", _WindowStoreProxy())
```

Every handler that previously did `from .session import session_manager` and then accessed `session_manager.window_states` continues to work because the proxy intercepts attribute access and re-routes to `_active_store`. This is _better_ than monkey-patching — the failure mode is now an explicit `RuntimeError("not wired")` from the proxy — but it still expresses dependency injection as **lookup of a global variable**, not as parameter passing.

Concretely:

- 27 modules import `window_store` directly.
- 46 import `thread_router`.
- 16 import `session_manager` directly.
- 44 handler call sites use `session_manager.*` directly; 30 use the read-only `window_query` / `session_query` free-function layer. The two patterns coexist without enforcement of which to use when.
- Tests need `bootstrap.reset_for_testing()`, which itself calls _three more_ `_reset_*_for_testing` hooks (`hook_events._reset_stop_callback_for_testing`, `status_bubble._reset_rc_active_provider_for_testing`, `shell_capture._reset_approval_callback_for_testing`). Twelve test files import these.

### Complexity Impact

The proxy preserves call sites at the cost of:

1. **Lookup-time failure**: a handler that touches `window_store` before `SessionManager` is constructed gets `RuntimeError("not wired")` at the call site, not at import time. Tests that import handlers and then forget to install a `WindowStateStore` get a misleading stack trace pointing at the handler, not at the test setup.
2. **Test parallelism is brittle**: any test that mutates `window_store` mutates a process-wide global. `pytest-xdist` would require per-worker isolation that doesn't exist.
3. **Two overlapping APIs**: a handler that needs to read window state can use either the `window_query` free functions or `session_manager.window_states[...]` directly. The query layer was meant to be the only read path; ~44 sites disagree.

This is the [tight-coupling smell](https://coupling.dev/posts/core-concepts/balance/) at the singleton boundary — strength is high (handlers know the singleton's name and method shape), distance is low (sibling), and volatility is medium (every UX feature touches at least one of these stores).

### Cascading Changes

- Splitting `WindowStateStore` into per-feature views (already discussed in the prior review's "Other Observations") forces every one of the 27 importers to update — even the 22 that only need read access.
- Adding a fifth wired store (e.g. for the new mailbox sweep state) requires: declare proxy → install function → wire in `SessionManager.__post_init__` → remember to add it to `bootstrap.reset_for_testing()`. Four edits, none of them caught by the type checker if forgotten.

### Recommended Improvement

Two-step migration, in order:

**Step 1 — enforce one read path.** Adopt a project rule: handlers read window/session state through `window_query` and `session_query` only. Migrate the 44 direct-`session_manager.*` call sites in handlers to the query layer. Leave bootstrap-time and admin paths (e.g. `sync_command.py`, `sessions_dashboard.py`) on the direct API. This is mechanical and removes the "two ways to do it" ambiguity without touching the singletons. ~1 day.

**Step 2 — pass the wired SessionManager into handlers that need write access.** The handlers that genuinely need to mutate stores (topic creation, dead-window cleanup, provider switch) should receive the manager as a parameter — either through `context.bot_data["session_manager"]` (PTB-native) or via a small request-scoped context object. Once writes go through a passed dependency, the proxies become read-only re-exports, and `reset_for_testing` collapses to one call (or disappears entirely if tests use a fresh `SessionManager()` per test). ~3–5 days.

**Trade-off**: Step 1 is pure mechanical refactor with measurable benefit (one access pattern, fewer importers). Step 2 is the bigger commitment but is what actually retires the singleton-as-proxy pattern. Skip Step 2 if the test friction is tolerable; do Step 1 either way.

## Issue: Lazy-import gap — 222 in-function imports vs 124 documented `# Lazy:` comments

**Integration**: latent cycles in `src/ccgram/`
**Severity**: <span class="severity severity-significant">Significant</span>

### Knowledge Leakage

Round 4's F6 phase claimed "160 intentional lazy imports documented" out of 251 originally inventoried, with 25 hoisted and ~25 redundant ones removed during the sweep. Reality, post-Round-4, on this branch:

- **222** in-function relative imports (`grep -rn '^[[:space:]]\+from \.' src/ccgram --include='*.py'`).
- **124** lines marked `# Lazy:`.
- **9** in-function relative imports inside `if TYPE_CHECKING:` blocks (legitimately not concerning).

That leaves **~89 in-function imports without an explicit reason comment**. Some of those are inside test-reset hooks (legitimate; they're test-only code paths) and inside functions that take a `provider_name` parameter (legitimate; they import per-provider format modules). But the F6 invariant — "every remaining lazy import is documented with `# Lazy: <reason>` citing the cycle path or wiring contract" — does not hold across the whole tree.

This is [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of the latent kind: a deferred import is a runtime-only dependency edge that the static module graph misses. Each undocumented one is a place where a future refactor can change behaviour silently — the graph won't break, but cold-import timing or test-order dependence might.

### Complexity Impact

Two practical costs:

1. **The `test_import_no_cycles.py` integration test parametrizes 29 modules**. The remaining 90+ modules with lazy imports are not covered. A new cycle introduced through a deferred import will only show up if a test happens to be the first caller.
2. **Reviewers cannot tell, at a glance, whether a deferred import is intentional (cycle break) or accidental (someone forgot to hoist).** The F6 comments were a contract; an undocumented deferred import silently breaks that contract.

### Cascading Changes

- A future "extract a shared utility" refactor reads the explicit imports to see the dependency graph, then makes a decision that doesn't account for the lazy edges. Re-introducing a cycle is the most likely class of regression here.

### Recommended Improvement

One mechanical pass:

1. Add a CI check (`make lint` or a pre-commit hook) that greps for `^[[:space:]]+from \.` and asserts each match is preceded by `# Lazy:`, `if TYPE_CHECKING`, or appears inside a `_reset_*_for_testing` function. The first prototype is ~40 lines of Python.
2. Walk the 89 currently-undocumented sites: hoist the ones that don't actually break a cycle (the F6 phase already removed the obvious ones, so this should be a small minority), and add `# Lazy:` to the rest with the cycle path or contract reason.
3. Expand `test_import_no_cycles.py` to cover the full set of 50 top-level modules + the 14 handler subpackages. Currently 29; the other ~35 are equally likely to host a regression.

**Trade-off**: 2–3 hours of work for the lint check; ~1 day for the audit + test expansion. Behaviour unchanged. Payoff: the F6 contract becomes self-enforcing, and the cycle test becomes a real safety net rather than a sample.

## Issue: `bot.py` `__all__` re-exports 19 moved symbols for `unittest.mock.patch` compatibility

**Integration**: legacy tests (and possibly external users of `from ccgram.bot import *`) -> `ccgram.bot`
**Severity**: <span class="severity severity-minor">Minor</span>

### Knowledge Leakage

`bot.py` declares `__all__ = ["clear_browse_state", "commands_command", "handle_text_message", "history_command", "inline_query_handler", "is_user_allowed", "new_command", "post_init", "post_shutdown", "post_stop", "safe_reply", "session_manager", "text_handler", "thread_router", "toolbar_command", "toolcalls_command", "unsupported_content_handler", "verbose_command", "create_bot"]`. The accompanying comment is candid: "Re-export the moved handler callables and supporting singletons so existing tests and integration suites that import them from `ccgram.bot` keep working without churn. Canonical homes are the feature subpackages — these names are retained for `patch` targets."

This is a compatibility shim for `unittest.mock.patch("ccgram.bot.session_manager", ...)`-style test code. It's working as designed and the prior review didn't flag it. But it's [model coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) on the _test_ side: the tests know that `session_manager` lives at `ccgram.bot.session_manager` — which it doesn't anymore.

### Complexity Impact

Low. The shim is documented; new code uses canonical paths; the symbols listed are stable.

### Cascading Changes

If `session_manager` ever moves out of `ccgram.session` (Step 2 of the singleton-retirement work above), the `bot.py` re-export silently keeps working, masking what should be a noisy test-update prompt.

### Recommended Improvement

Opportunistic, low priority:

- When migrating tests to `FakeTelegramClient` and direct `SessionManager` construction (the F5 + F2 follow-ups), update each test's `patch` target to the canonical module. When `__all__` shrinks to zero, delete the re-export block.
- Until then: leave it. The cost of churning 50+ test files for an aesthetic win is not justified.

**Trade-off**: zero risk; defer until the tests get touched for other reasons.

## Issue: Inbound PTB types still pervade handler signatures

**Integration**: 38+ handler modules → `telegram.{Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, MessageEntity}` and `telegram.ext.ContextTypes`
**Severity**: <span class="severity severity-minor">Minor</span>

### Knowledge Leakage

F5 isolated the _outbound_ bot API behind a 18-method `TelegramClient` Protocol — that work is done and excellent. But the _inbound_ surface is essentially unchanged: PTB calls handlers with `Update` and `ContextTypes.DEFAULT_TYPE` as positional arguments, so every handler signature still spells those types. Inline-keyboard construction also uses `InlineKeyboardButton` / `InlineKeyboardMarkup` directly — there's no facade.

Per the [balance rule](https://coupling.dev/posts/core-concepts/balance/), this is tolerable: PTB's inbound API is a stable, low-volatility 3rd-party contract, so high-strength coupling against a low-distance-but-low-volatility external is balanced. The previous review acknowledged this trade-off explicitly.

### Complexity Impact

Cognitive load for new contributors: medium. A new contributor reading any handler still has to know what `Update`, `CallbackQuery`, and `ContextTypes` look like. Because the outbound API is now hidden, the _asymmetry_ is jarring: the handler reads `Update.callback_query.data` (PTB) and then calls `client.edit_message_text(...)` (the Protocol). Half the file uses one mental model, half uses another.

### Cascading Changes

Effectively zero. PTB has not had a breaking change to the inbound types in the lifetime of this project.

### Recommended Improvement

Do not invest. The cost is high (30+ files, custom `IncomingUpdate` / `Keyboard` types, `KeyboardButton` factory functions) and the volatility is genuinely low. If the project ever migrates to a different Telegram framework (e.g. aiogram), this becomes a real cost — but that's a hypothetical that doesn't justify pre-paying.

The one cheap win available: a `ccgram.handlers.telegram_types` re-export module that aliases the PTB types under project-local names (`Update as IncomingUpdate`, etc.). It costs nothing, makes the framework boundary visible in one file, and gives a single edit point if the situation ever changes. Worth doing during the next routine PTB upgrade.

## Scoring (0–10)

The previous review scored 6.3 weighted; this review scores **7.1**. The deltas are concentrated where Round 4 invested: subsystem locality, lifecycle clarity, abstraction quality, testability of pure logic. The two new entries (#21, #22) reflect what Round 4 didn't reach.

| #   | Design POV                                | 04-29 | 05-01   | Comment                                                                                            |
| --- | ----------------------------------------- | ----- | ------- | -------------------------------------------------------------------------------------------------- |
| 1   | Module cohesion (single-responsibility)   | 6     | 7       | Subpackages cohesive; `command_orchestration`, `recovery_callbacks`, `polling_strategies` outliers |
| 2   | Coupling — overall (Balanced Coupling)    | 6     | 7       | F2/F5 reduced strength; singleton hub remains                                                      |
| 3   | Separation of concerns (UI vs domain)     | 5     | 7       | `decide.py` pure; `TelegramClient` Protocol; UI primitives still inline                            |
| 4   | Abstraction quality                       | 7     | 8       | + `TelegramClient` Protocol; `WindowView` / `decide_tick` / `CommandResult` strong                 |
| 5   | Dependency direction (acyclic)            | 6     | 7       | Cycle-detection test added; lazy-import gap of ~89 sites remains                                   |
| 6   | Testability of pure logic                 | 7     | 8       | `decide_tick` unit-tested without mocks; `FakeTelegramClient` enables cheap handler tests          |
| 7   | Testability of integration logic          | 5     | 7       | `FakeTelegramClient` is a real win; `reset_for_testing` ceremony still hurts                       |
| 8   | Boundary discipline (3rd-party isolation) | 4     | 6       | Outbound PTB hidden behind Protocol; inbound types still leak (acknowledged trade-off)             |
| 9   | Provider extension cost                   | 9     | 9       | Unchanged — gold standard                                                                          |
| 10  | New Telegram command extension cost       | 6     | 8       | `handlers/registry.py` `CommandSpec` table is the one edit point                                   |
| 11  | Lifecycle clarity                         | 6     | 8       | `bootstrap.py` named steps + ordering invariant + `_callbacks_wired` guard                         |
| 12  | Configuration coupling                    | 5     | 5       | `config` singleton imported by 58 modules; no narrow `Settings` injection                          |
| 13  | State management                          | 7     | 7       | `window_query` / `session_query` still mixed with direct `session_manager.*` (44 vs 30)            |
| 14  | Implicit-coupling risk (singletons)       | 4     | 5       | Proxy pattern formalises the global; not eliminated                                                |
| 15  | Code duplication                          | 8     | 8       | Unchanged — `_jsonl`, `expandable_quote`, `message_task` continue to factor                        |
| 16  | Subsystem locality (AI-agent context)     | 5     | 8       | Big win — 14 cohesive subpackages, ~5–8× fewer files per task                                      |
| 17  | Documentation density                     | 9     | 9       | + 124 `# Lazy:` comments document deferred imports                                                 |
| 18  | Domain model purity                       | 6     | 7       | `WindowView` + `decide.py` + `TelegramClient` raise the bar; UI primitives still inline            |
| 19  | Cyclic risk                               | 6     | 7       | `test_import_no_cycles.py` covers 29 modules; needs to cover the rest                              |
| 20  | Build / refactor velocity                 | 7     | 8       | Round 4 demonstrated capacity to ship a 6-phase refactor + 2 review iterations                     |
| 21  | Test-infra debt (NEW)                     | —     | 6       | `reset_for_testing` + 3 `_reset_*_for_testing` hooks + 12 test-files import them                   |
| 22  | Hidden coupling hubs (NEW)                | —     | 5       | `polling_strategies` (5 singletons + pure types in 1 073 LOC); `command_orchestration` (4 jobs)    |
|     | **Weighted average**                      | 6.3   | **7.1** |                                                                                                    |

7.1 reads as "good architecture, four hot spots left." The four critical findings (`polling_strategies` split, `command_orchestration` split, `recovery_callbacks` split, singleton-retirement Step 1) account for almost all the residual friction; together they are 2.5–3 days of mechanical work.

## Recommended Order of Work

Pick by leverage. All five preserve behaviour.

1. **`polling_strategies.py` → `polling_types.py` + `polling_state.py`.** ~1 day. Eliminates the singleton-hub problem and finally makes the F4 pure-kernel claim true at the import level. Cycle-detection test catches regressions.
2. **Single read path for window/session state — migrate 44 handler `session_manager.*` sites to `window_query` / `session_query`.** ~1 day. Removes "two ways to do it" before any further DI work. Sets up the singleton-retirement step.
3. **Split `recovery_callbacks.py` into `recovery_banner.py` + `resume_picker.py`.** ~half a day. Independently navigable; the resume-picker pagination work that's already on the backlog drops into a smaller file.
4. **Split `command_orchestration.py` into `handlers/commands/` subpackage (forward / menu_sync / failure_probe / status_snapshot).** ~half a day. Same shape as `shell/`; the four jobs become independently reviewable.
5. **Lazy-import lint check + audit pass.** ~half a day for the lint script + 1 day for the audit. Self-enforces the F6 contract; expands `test_import_no_cycles.py` coverage.
6. **(Optional, multi-day) Singleton-retirement Step 2 — pass `SessionManager` through `context.bot_data` to handlers that mutate state.** Defer until test-friction warrants it.

What _not_ to do:

- Do not abstract inbound PTB types unless you're migrating frameworks — the cost is high and PTB's inbound API is genuinely stable.
- Do not split `tmux_manager.py` — it's the I/O boundary; bigness is correct.
- Do not redesign `providers/` — it's the gold-standard pattern in the codebase; replicate it elsewhere instead.
- Do not collapse the proxy globals to plain instances without first migrating the read path (item 2 above) — you'll just re-introduce the failure mode F2 designed away.

## Why these moves match the model

- The `polling_strategies` split lowers [strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (the pure-types module becomes contract-coupled; the stateful module stays model-coupled but only to its real callers) without changing distance — pure win, balanced both halves.
- The handler splits (`recovery_callbacks`, `command_orchestration`) are pure cohesion improvements at zero distance change — they reduce the cognitive footprint per change and shrink reviewer working memory.
- The single-read-path migration is a strength reduction (handlers depend on a small read-only contract, not on `SessionManager`'s full API) with zero distance change.
- The lazy-import lint check makes the existing F6 contract self-enforcing — nothing new is being coupled, but a latent regression channel is closed.

These moves are aligned with what the maintainer asked for: smaller focused contexts, faster execution, lower AI-agent cost — without touching the parts (provider abstraction, Mini App boundary, lifecycle wiring, pure decision kernel, `TelegramClient` Protocol) that already work.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
