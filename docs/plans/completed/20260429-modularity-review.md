# ccgram Modularity Review — 2026-04-29

Honest review of the entire codebase against the Balanced Coupling model
(Khononov: integration strength × distance × volatility). Goal stated by
maintainer: focused, narrow-context changes — both for humans and for AI
agents working on the code. Lower coupling here directly translates into
fewer files in any AI-agent context window per task.

Scope: `src/ccgram/` (~40 KLOC, ~120 modules, 5 providers, 50+ handlers,
optional Mini App). Method: read code + docs (`docs/architecture.md`,
`docs/ai-agents/architecture-map.md`, `docs/ai-agents/codebase-index.md`),
trace imports, sample largest modules and integration points.

## TL;DR

- Strong refactor history is visible. Provider abstraction, query-only
  decoupling layers (`window_query.py`, `session_query.py`, `WindowView`),
  pure-data decision kernels (`TickContext`/`TickDecision`/`decide_tick`),
  `topic_state_registry`, capability flags — all good moves already shipped.
- Three coupling problems still drive context bloat:
  1. **Flat `handlers/` namespace** (50+ peer modules). Feature cohesion is
     informal (file-name prefixes). A "recovery" or "shell" change touches
     5–10 sibling files that are not grouped.
  2. **Implicit-singleton DI everywhere.** `session_manager`,
     `tmux_manager`, `thread_router`, `window_store`, `terminal_screen_buffer`
     etc. are module-level globals imported by handlers. Wiring them
     requires `_wire_singletons` monkey-patch + three `register_*_callback`
     calls in `bot.py`. Order matters; defaults silently mask missing wires.
  3. **PTB / `telegram.*` leakage into 38 modules.** The Bot/Update/Markup
     types appear deep inside handlers, status-bubble, queue worker. Most
     handler logic cannot be reasoned about without loading PTB context.
- Provider subsystem is exemplary; the rest of the code can converge on
  that pattern.

## Domain Classification

| Subsystem               | Type       | Volatility | Comment                                                                            |
| ----------------------- | ---------- | ---------- | ---------------------------------------------------------------------------------- |
| Telegram UX (handlers/) | Core       | High       | Recurrent UX overhaul plans (`docs/plans/completed/`). Where competitive value is. |
| Provider abstraction    | Core       | High       | 5 providers in 6 months, more landing (Pi v3 Apr 28, Gemini JSONL Apr 29).         |
| Inter-agent messaging   | Core       | Medium     | New feature still maturing (mailbox, spawn flow).                                  |
| Mini App                | Core       | High       | New in v3.0; HTTP/WS surface still expanding.                                      |
| Session monitoring      | Supporting | Medium     | Hooks vs hookless variants; refactored multiple times.                             |
| State persistence       | Supporting | Low        | `state.json` schema is stable; mostly forward-compatible.                          |
| tmux integration        | Generic    | Low        | tmux API stable; libtmux interface stable.                                         |
| Telegram client (PTB)   | Generic    | Low        | API surface stable.                                                                |

## Integration Map

For each significant pair of modules I checked _what knowledge_ flows,
_strength level_ (intrusive / functional / model / contract), _distance_
(same module / sibling / cross-package / 3rd-party), and _volatility_
(from the table above).

| #   | From → To                                     | Knowledge                               | Strength   | Distance  | Volatility | Balanced?                                          |
| --- | --------------------------------------------- | --------------------------------------- | ---------- | --------- | ---------- | -------------------------------------------------- |
| 1   | handlers/\* → `session_manager` (singleton)   | mutate window state, audit, prune       | functional | sibling   | medium     | ❌                                                 |
| 2   | handlers/\* → `tmux_manager` (singleton)      | send_keys, capture_pane, list_windows   | functional | sibling   | low        | ✅                                                 |
| 3   | handlers/\* → `thread_router` (singleton)     | (user,thread) ↔ window_id resolution    | functional | sibling   | medium     | ⚠                                                  |
| 4   | handlers/\* → `window_store` / `window_query` | read window state, mutate modes         | model      | sibling   | medium     | ✅ (query layer absorbs read coupling)             |
| 5   | `bot.py` → 30+ handler modules                | command/callback wiring                 | intrusive  | sibling   | high       | ❌                                                 |
| 6   | `bot.py` post_init → 7 subsystems             | `register_*_callback`, `set_*_callback` | intrusive  | sibling   | high       | ❌                                                 |
| 7   | handlers/_ → `telegram._` (PTB)               | Bot, Update, CallbackQuery, Markup      | model      | 3rd-party | low        | ✅ (NOT VOLATILITY) — but painful for context size |
| 8   | `SessionManager._wire_singletons` → 4 stores  | monkey-patches `_schedule_save`         | intrusive  | sibling   | medium     | ❌                                                 |
| 9   | handlers/shell\_\* → `providers.shell_infra`  | match_prompt, KNOWN_SHELLS              | functional | sibling   | low        | ✅ (documented accepted leak)                      |
| 10  | `window_tick.py` → ~12 collaborators          | terminal poll, lifecycle, transcript    | functional | sibling   | high       | ❌                                                 |
| 11  | AgentProvider protocol → 5 implementations    | capabilities, parse, launch             | contract   | sibling   | high       | ✅                                                 |
| 12  | miniapp.api → providers + window_query        | read-only state, transcripts            | contract   | sub-pkg   | high       | ✅                                                 |
| 13  | handlers/message_queue → tool_batch + bubble  | dispatch by task type                   | model      | sibling   | medium     | ✅                                                 |
| 14  | many handlers/\* → in-function `from .X`      | hidden cycles, deferred loads           | intrusive  | sibling   | medium     | ❌                                                 |
| 15  | handlers/\* → `config` (singleton)            | env-var settings                        | model      | sibling   | low        | ✅                                                 |
| 16  | `hook.py` → `~/.claude/settings.json`         | install/uninstall hook config           | contract   | external  | low        | ✅                                                 |

## Critical Findings (unbalanced + volatile)

### F1 — Flat `handlers/` namespace eats AI-agent context budgets

**Symptom.** A change to "shell command flow" requires loading
`shell_commands.py`, `shell_capture.py`, `shell_context.py`,
`shell_prompt_orchestrator.py`, `voice_callbacks.py` (shell branch),
`text_handler.py` (shell branch), plus `providers/shell_infra.py` and
`llm/httpx_completer.py`. None of these are namespaced together. Same
pattern for "recovery" (8 files), "messaging" (5 files), "topic
lifecycle" (4 files), "screenshot/live view" (3 files).

**Diagnosis.** Strength is medium-functional inside each feature, distance
is low (same `handlers/` directory), but cohesion is _hidden_ behind
filename prefixes. Cohesion that is invisible to the file system means an
AI agent (or a new contributor) cannot ask "give me everything about
recovery" — they ask the global handlers/ list.

**Fix.** Group by feature into subpackages. Concrete proposal:

```
handlers/
├── topics/        topic_orchestration, topic_lifecycle, topic_emoji,
│                  directory_browser, directory_callbacks, window_callbacks
├── messaging/     msg_broker, msg_delivery, msg_telegram, msg_spawn (already cohesive)
├── shell/         shell_commands, shell_capture, shell_context,
│                  shell_prompt_orchestrator
├── recovery/      recovery_callbacks, restore_command, resume_command,
│                  transcript_discovery
├── status/        status_bubble, status_bar_actions, topic_emoji
├── interactive/   interactive_ui, interactive_callbacks, history,
│                  history_callbacks
├── send/          send_command, send_callbacks, send_security
├── toolbar/       toolbar_keyboard, toolbar_callbacks
├── live/          live_view, screenshot_callbacks, pane_callbacks
├── voice/         voice_handler, voice_callbacks
├── messaging_pipeline/  message_queue, message_routing, message_sender,
│                        message_task, tool_batch
└── polling/       polling_coordinator, polling_strategies, periodic_tasks,
                   window_tick
```

Effort: ~1 day, mostly mechanical (move + fix imports). No behavior
change. Each subpackage gets a short `__init__.py` re-exporting its public
surface so `bot.py` keeps shallow imports.

### F2 — Implicit-singleton DI is hiding a runtime contract

**Symptom.** `SessionManager.__post_init__` calls `_wire_singletons()`
which **monkey-patches** `_schedule_save` on `window_store`,
`thread_router`, `user_preferences`, `session_map_sync`. Until that runs,
mutating any of those four blows up with `RuntimeError("unwired_save")`.

**Diagnosis.** This is dependency injection expressed as private-attr
mutation across module boundaries. Integration strength here is
**intrusive**: SessionManager assumes the internal layout of four other
modules. Distance is sibling. Volatility is medium (any time you split a
new store, you must remember to add a wire). Balance fails.

The same pattern appears in `bot.py` post_init:

```python
register_stop_callback(_on_stop)
register_rc_active_provider(terminal_screen_buffer.is_rc_active)
register_approval_callback(show_command_approval)
```

Defaults are silent (`_rc_active_default` returns `False`,
`register_approval_callback`'s receiver gates a UI flow). Forgetting one
produces a feature that just doesn't work — no error.

**Fix.** Two options:

1. **Constructor injection** — pass dependencies in via `__init__` rather
   than singleton imports + late wiring. Make `WindowStateStore`,
   `ThreadRouter`, etc. accept their `schedule_save` callback in
   `__init__`. SessionManager constructs them rather than reaching into
   pre-built globals.
2. **Required-callback assertion** — at minimum, change `unwired_save` to
   no longer be silent. Have `register_approval_callback` etc. raise if a
   second registration happens, and have call sites assert that
   registration happened. The current model accepts "wire skipped" as a
   valid state.

Option 1 is the right long-term move; it also makes tests trivial (build a
SessionManager in-test with stub stores).

### F3 — `bot.py` is doing too much

**Symptom.** 723 lines, imports from ~40 handler modules, 7 distinct
post_init phases, 17 command-handler registrations, runtime callback
wiring, hook-install warning, miniapp boot. Every new feature lands here.

**Diagnosis.** The "command_orchestration" sibling already exists — but
`bot.py` itself remains the union of (a) PTB Application factory, (b)
runtime wiring, and (c) lifecycle (post_init / post_stop / post_shutdown).
High strength + sibling distance + high volatility = unbalanced.

**Fix.**

1. Move command-handler registration to a `handlers/registry.py` that owns
   the table `[(name, fn, filter)…]`. `bot.py` calls `register_all(app)`.
2. Move post_init wiring to `app_lifecycle.py` (or `bootstrap.py`) — one
   module that owns "build monitor, wire callbacks, start polling, start
   miniapp." Failure to wire raises.
3. `bot.py` shrinks to ~150 lines: Application factory + lifecycle
   delegate calls.

### F4 — `window_tick.py` orchestrator god

**Symptom.** 694 lines, 22 functions, depends on 12 collaborators
(tmux_manager, screen_buffer, poll_state, lifecycle_strategy,
pane_status_strategy, interactive_ui, cleanup, transcript_discovery,
topic_emoji, recovery_callbacks, message_queue, message_sender,
window_query, claude_task_state, session_monitor, thread_router).

The good news: there's a **pure decision kernel** at
`decide_tick(ctx) → decision`. That's the right pattern. The bad news:
the surrounding `_apply_*_transition` and `_update_status` still reach
into all the singletons.

**Fix.** Split `window_tick.py` into:

- `window_tick/decide.py` — `TickContext`, `TickDecision`, `decide_tick`
  (already pure; just isolate it).
- `window_tick/observe.py` — gather pane text, status, last activity,
  pane lifecycle, etc. Returns `TickContext`. One file, one job.
- `window_tick/apply.py` — apply `TickDecision` (transitions, queue,
  emoji, recovery banner). Heavy DI.
- `window_tick/__init__.py` — `tick_window` thin shim.

Same pattern that worked for the polling strategies. Lets you unit-test
the decision kernel without touching tmux at all.

### F5 — PTB framework leak

**Symptom.** 38 modules import `telegram.*`. Status-bubble formatting,
message_queue, polling, recovery, tools, all parameterize on
`Bot`/`Update`/`InlineKeyboardMarkup`. Domain logic for "what to send when
a session goes idle" lives in the same call frame as `bot.send_message`.

**Volatility on this dimension is low** — PTB's API rarely breaks. Per the
balance rule, that's tolerable. **But** the maintainer's stated goal is
"narrow context per task." Domain logic that depends only on Telegram
_concepts_ (chat ID, thread ID, text, reply markup) but not on Telegram
_types_ would shrink the per-task context dramatically.

**Fix (incremental, optional).** Define a thin `TelegramClient` Protocol
inside ccgram that exposes only the methods you actually use
(`send_message`, `edit_message_text`, `edit_message_media`, `answer_callback_query`,
`send_chat_action`, `create_forum_topic`, ...). Pass it through the same
DI you use for SessionManager. Handlers depend on `TelegramClient`, not
`telegram.Bot`. Tests build a fake. Adapter sits in one place
(`telegram_client.py`).

Cost is real (~3 days of work, ~30 files touched). Payoff: any handler
file becomes readable in isolation; AI-agent token cost on UX changes
drops materially.

### F6 — In-function imports are a cycle smell

**Symptom.** ~30 sites do `from .X import Y` inside function bodies.
Examples: `bot.py:438`, `session.py:101`, `recovery_callbacks.py:189`,
`text_handler.py:34`. Reasons given in code: avoid circular imports, defer
expensive setup, avoid Config dependency in CLI commands.

**Diagnosis.** Every in-function import is admission of a cycle the
module graph can't carry at top level. They hide the real coupling from
static analysis and make the import graph context-dependent.

**Fix.** Once F1 (subpackages) and F2 (constructor DI) land, most of these
disappear naturally. Specifically:

- `from .config import config` inside functions → take `config` as a
  parameter or store it on the object.
- `from .session import session_manager` inside callbacks → already a
  candidate for the new DI: pass dependencies in.
- The remaining few that import providers lazily — those are fine; document
  the reason.

## Other Observations (lower priority)

- **`tmux_manager.py` (1182 lines)** is large but it's the single I/O
  boundary for tmux. That's the correct trade-off — let it stay big rather
  than spread tmux calls. Consider splitting `vim_state` cache and
  `discover_external_sessions` into siblings if size keeps growing.
- **`polling_strategies.py` (1061 lines)** packs 5 strategy classes. The
  classes are independent — splitting one class per file would help
  navigation without changing coupling.
- **`recovery_callbacks.py` (880 lines)** is right at the edge. Splitting
  the resume picker UI from the dead-window banner would help.
- **Provider subsystem is exemplary.** `AgentProvider` Protocol +
  `ProviderCapabilities` + `registry`. One accepted leak (shell prompt
  helpers imported by shell handlers) is documented and balance-rule
  justified. Use this pattern as the template for any new feature area.
- **`miniapp/` is the right shape.** Subpackage boundary, narrow public
  API, only entry points reach into it. Replicate that for messaging.
- **Documentation density is excellent.** Module docstrings are
  consistent. `CLAUDE.md` + `docs/architecture.md` + `docs/ai-agents/`
  give an AI agent enough to navigate. Don't lose that.
- **Test pyramid is right** (16K unit, 3K integration, 1.4K e2e). The
  bottleneck is that unit tests still have to reset module-level
  singletons — DI fixes that.

## Scoring (0–10, honest)

Higher is better. 10 = exemplary; 7–8 = good; 5–6 = mixed; 3–4 = weak.

| #   | Design POV                                | Score   | Comment                                                                   |
| --- | ----------------------------------------- | ------- | ------------------------------------------------------------------------- |
| 1   | Module cohesion (single-responsibility)   | 6       | Module docstrings claim it; flat `handlers/` dilutes feature cohesion     |
| 2   | Coupling — overall (Balanced Coupling)    | 6       | Singleton + PTB coupling pervasive; query layers help                     |
| 3   | Separation of concerns (UI vs domain)     | 5       | Domain logic interleaved with PTB types throughout handlers               |
| 4   | Abstraction quality                       | 7       | Provider Protocol, capability flags, WindowView are excellent             |
| 5   | Dependency direction (acyclic)            | 6       | In-function imports + callback wiring betray latent cycles                |
| 6   | Testability of pure logic                 | 7       | TickContext/TickDecision, CommandResult, RecoveryBanner are unit-testable |
| 7   | Testability of integration logic          | 5       | Handlers require PTB + singleton resets; slow & noisy                     |
| 8   | Boundary discipline (3rd-party isolation) | 4       | PTB types in 38 modules; libtmux types in 8                               |
| 9   | Provider extension cost                   | 9       | One file, one register call; capability flags; no `if provider==` checks  |
| 10  | New Telegram command extension cost       | 6       | bot.py + handler + callback constants + maybe registry — too many places  |
| 11  | Lifecycle clarity                         | 6       | TopicStateRegistry good; `bot.post_init` does too much                    |
| 12  | Configuration coupling                    | 5       | `config` singleton imported by 38 modules; no narrow Settings injection   |
| 13  | State management                          | 7       | window_query / session_query / WindowView decoupling is the right move    |
| 14  | Implicit-coupling risk (singletons)       | 4       | Many globals, monkey-patched callbacks, silent default fallbacks          |
| 15  | Code duplication                          | 8       | `_jsonl` base, `expandable_quote`, `message_task` factor common patterns  |
| 16  | Subsystem locality (AI-agent context)     | 5       | Flat handlers/, PTB leak; recovery/shell/messaging spread across siblings |
| 17  | Documentation density                     | 9       | Excellent — module docstrings, CLAUDE.md, ai-agents/                      |
| 18  | Domain model purity                       | 6       | Window/Session/Topic concepts clear; PTB types blur the seams             |
| 19  | Cyclic risk                               | 6       | In-function imports + callback registration reveal real cycles            |
| 20  | Build / refactor velocity                 | 7       | Refactor history shows the team can move; current shape is workable       |
|     | **Weighted average (rough)**              | **6.3** |                                                                           |

The 6.3 reads as: "good bones, real friction." Five issues (F1–F5) move
the most tokens for the least effort. Fixing F1 alone is a 1-day,
zero-risk change with immediate context-budget payoff.

## Recommended Order of Work

Pick by leverage, not by score. All five fixes preserve behavior.

1. **F1 — Group `handlers/` into feature subpackages.** ~1 day, mechanical.
   Immediate AI-agent context savings (5–8× fewer files in many tasks).
2. **F4 — Split `window_tick.py` (decide / observe / apply).** ~0.5 day.
   Lets you unit-test decisions without tmux.
3. **F2 — Constructor DI for SessionManager / WindowStateStore /
   ThreadRouter.** ~2 days. Eliminates `_wire_singletons` and most
   `unwired_save` ceremony. Tests get faster and quieter.
4. **F3 — Extract `bootstrap.py` and `handlers/registry.py` from
   `bot.py`.** ~0.5 day after F2. Future feature additions stop touching
   `bot.py`.
5. **F5 — `TelegramClient` Protocol + adapter.** ~3 days. Optional but the
   single biggest reduction in per-task context size if AI-agent cost is
   the goal.
6. **F6 — Audit in-function imports.** Continuous; mostly resolves itself
   after F1+F2.

What _not_ to do:

- Don't break up `tmux_manager.py` "because it's big." It's the I/O
  boundary; that's a feature.
- Don't redesign the provider subsystem. It's the strongest part.
- Don't add a DI container. Plain constructor injection is enough for a
  single-process bot.

## Why these choices match the Balanced Coupling model

- F1 reduces **distance** within each feature (siblings → same package),
  while strength stays the same. Cohesion improves; balance with high
  domain volatility (Telegram UX) gets reasserted.
- F2/F3 reduce **strength** by replacing intrusive monkey-patching with
  explicit injected contracts. Distance unchanged; volatility unchanged.
- F4 splits one volatile module into one volatile orchestrator + one
  pure low-volatility kernel. The pure kernel becomes balanced-by-default.
- F5 raises **distance** to a 3rd-party (PTB) but lowers **strength** in
  every dependent module from "model coupling on PTB types" to "contract
  coupling on a small adapter Protocol." Total system strength drops.

These five moves are aligned with what the maintainer asked for: smaller
focused contexts, faster execution, lower AI-agent cost — without
touching the parts that already work.
