# ccgram — Target Architecture

**Date**: 2026-04-13
**Status**: Target state for the post-Apr-12 refactor iteration. Incremental, reversible. Derived from `docs/modularity-review/2026-04-13/modularity-review.md`.

## Functional Requirements Summary

ccgram is a Telegram bot that manages AI coding agents (Claude Code, Codex, Gemini) and plain shells via tmux. Each Telegram Forum topic is bound to one tmux window running one agent session. Users drive agents through Telegram — send text messages, receive streamed responses, tap inline keyboards for interactive prompts, view pane screenshots, send files, control agents via toolbar, and coordinate multiple agents via inter-agent messaging.

Key invariants (from `CLAUDE.md`):

- **1 topic = 1 window = 1 session**, keyed by tmux window ID (`@N`), not name.
- **Topic-only** — no non-topic mode, no General-topic routing.
- **No message truncation at parse layer** — splitting only at send layer.
- **Entity-based formatting** with automatic plain-text fallback.
- **Hook-based session tracking** (Claude Code) with terminal-scraping fallback.
- **Per-user message queue** with FIFO, merge, and rate limiting.

This target architecture preserves every invariant above. It reorganises internal module boundaries to address the five Significant issues from today's modularity review.

## Module Map

| #   | Module                                                                 | Subdomain            | Status                                                                            |
| --- | ---------------------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------- |
| 1   | [Bot Composition Root](bot-composition/design.md)                      | Supporting           | Unchanged                                                                         |
| 2   | [Session and State](session-and-state/design.md)                       | Core                 | Minor cleanup + WindowView migration                                              |
| 3   | [Session Map Resolution](session-map-resolution/design.md)             | Core                 | Unchanged                                                                         |
| 4   | [Provider Abstraction](provider-layer/design.md)                       | Core (internal)      | **Adds `scrape_current_mode` capability**                                         |
| 5   | [Adapters (tmux + terminal parsing)](adapters/design.md)               | Supporting / Generic | Unchanged                                                                         |
| 6   | [Message Delivery](message-delivery/design.md)                         | Core                 | **Split into 4 cohesive files (queue / tool_batch / status_bubble / routing)**    |
| 7   | [Polling and Events](polling-and-events/design.md)                     | Core                 | **Split `TerminalStatusStrategy`; bound-method registry; delete compat wrappers** |
| 8   | [Topic Lifecycle and Interactive UI](topic-lifecycle-and-ui/design.md) | Core                 | Unchanged                                                                         |
| 9   | [Toolbar Subsystem](toolbar/design.md)                                 | Core                 | **Split into keyboard / dispatch / provider-owned scraping**                      |
| 10  | [Screenshot and Live View](screenshot-and-live-view/design.md)         | Core                 | **Extract `status_bar_actions.py`**                                               |
| 11  | [Directory Browser](directory-browser/design.md)                       | Supporting           | Capability-flag replacement for `provider_name == "claude"`                       |
| 12  | [Send Command](send-command/design.md)                                 | Supporting           | Promote `_upload_file` → public                                                   |
| 13  | [Shell Provider UX](shell-provider-ux/design.md)                       | Core                 | **Introduce `shell_prompt_orchestrator.py`**                                      |
| 14  | [History and Recovery](history-and-recovery/design.md)                 | Supporting           | Unchanged                                                                         |
| 15  | [Inter-Agent Messaging](inter-agent-messaging/design.md)               | Core                 | Unchanged                                                                         |
| 16  | [LLM Abstraction](llm-abstraction/design.md)                           | Generic              | Summariser remains Claude-hardcoded (deferred)                                    |
| 17  | [Whisper Transcription](whisper-transcription/design.md)               | Generic              | Unchanged                                                                         |
| 18  | [Telegram Helpers](telegram-helpers/design.md)                         | Generic + wrapper    | Unchanged                                                                         |
| 19  | [CLI Commands (no-bot)](cli-commands/design.md)                        | Supporting           | Unchanged                                                                         |

Of the 19 conceptual modules, **6 are refactored** and **3 receive minor cleanups**. The remaining 10 are unchanged — the refactor is surgical, not sweeping.

## How the Modules Work Together

### Key Functional Flow 1 — User Sends Text to an Agent

```
User types in a Telegram topic
  → Bot Composition Root (text_handler)
  → Topic Lifecycle (bound?) — if unbound, route to Directory Browser
  → Message Routing (notification filter, interactive tool detection, offset tracking)
  → either Interactive UI (if tool prompt pending) or Message Queue (else)
  → Message Queue worker → Tmux Adapter.send_keys → agent CLI
```

Contracts: `text_handler → message_routing.handle_text()`; `message_routing → interactive_ui.is_interactive_tool()`; `message_routing → message_queue.enqueue_content_message()`.

### Flow 2 — Agent Output Reaches the User

```
Claude writes transcript JSONL line
  → Session Map Resolution (monitor reads byte-incrementally)
  → Provider Abstraction (parse_transcript_entries)
  → NewMessage event → Message Routing (callback)
  → Tool Batch (if batch-eligible) OR Message Queue content path
  → Status Bubble (edit-in-place for status updates)
  → Telegram Helpers (rate-limit + entity format) → Telegram
```

Contracts: `session_monitor → message_routing.handle_new_message()`; `message_queue → status_bubble.clear_status_text()` before sending tool batch; `status_bubble → message_sender.rate_limit_send_message()`.

### Flow 3 — Toolbar Toggle Press (e.g., Mode)

```
User taps "Mode" button
  → Bot → Toolbar Dispatch (_dispatch → handle_toolbar_callback)
  → Toolbar Dispatch (action_type="key", payload="BTab")
  → Tmux Adapter.send_keys(window_id, "BTab")
  → sleep 250ms
  → Provider Abstraction.scrape_current_mode(window_id) (NEW capability)
  → Toolbar Keyboard._set_action_label(...) + rebuild + edit_message_reply_markup
```

Contracts: `toolbar_callbacks → provider.scrape_current_mode()` — provider-level contract replaces the current direct pane scraping inside the toolbar module.

### Flow 4 — Shell Prompt-Marker Setup (Every Trigger Goes Through One Door)

```
Any of the 5 triggers calls shell_prompt_orchestrator.ensure_setup(window_id, trigger):
  directory_callbacks — trigger="auto"
  window_callbacks — trigger="external_bind"
  transcript_discovery — trigger="provider_switch"
  shell_commands._ensure_prompt_marker — trigger="lazy"

  shell_prompt_orchestrator decides: run silently / show offer keyboard / no-op
  → providers/shell_infra.setup_shell_prompt(window_id, clear=...)
  → Tmux Adapter (keys + setup commands)
```

Contract: single `ensure_setup(window_id, trigger)` function with a closed enum of triggers. Policy logic centralised.

### Flow 5 — Polling Tick

```
Bot's status_poll_loop, once per second:
  for each (user, thread, window_id) binding:
    _scan_window_panes, _check_interactive_only, _handle_dead_window_notification,
    update_status_message, _maybe_check_passive_shell, transcript_discovery
    — uses TerminalScreenBuffer + TerminalPollState (post-split)
  run_periodic_tasks:
    broker delivery, mailbox sweep, live view tick, spawn processing
```

Cleanup callbacks registered via `topic_state.register_bound(scope, instance.method)` (new capability) fire on `topic_state.fire(scope, id)` — no module-level wrappers needed.

### Flow 6 — Hook Event (Claude Stop)

```
Claude calls ~/.claude/hooks/ccgram_hook (SessionEnd / Stop)
  → CLI Commands (hook.py) reads stdin
  → Provider Abstraction (ClaudeProvider.parse_hook_payload)
  → write events.jsonl line (append-only)

Session Monitor (in bot process):
  → read new line from events.jsonl
  → dispatch to Hook Event Processing (hook_events.handle_stop)
  → enqueue Ready status via Status Bubble
  → LLM Abstraction (summarizer, async) → edit status in place with 1-line summary
```

## Coupling Assessment (Target State)

| Integration                                                              | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                            | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)                             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Bot Composition → all handlers                                           | Contract (imports)                                                                                                             | Low                                                                     | Low                                                                         | Yes                                                                                        |
| Session & State → Session Map Resolution                                 | Model (shared `WindowState` / `session_map` view)                                                                              | Low                                                                     | High                                                                        | Yes — high cohesion                                                                        |
| Handlers → Session & State via `WindowView` (target)                     | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                            | Low                                                                     | High                                                                        | Yes — projection decouples shape                                                           |
| Handlers → Session & State via `get_window_state` (residual)             | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                               | Low                                                                     | High                                                                        | Borderline — acceptable for mutating handlers                                              |
| Message Queue → Tool Batch (split)                                       | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (`is_batch_eligible → process_tool_event`) | Low                                                                     | High                                                                        | Yes                                                                                        |
| Tool Batch → Status Bubble                                               | Contract (`clear_status_text` coordination)                                                                                    | Low                                                                     | High                                                                        | Yes                                                                                        |
| Status Bubble → Claude Task State                                        | Contract (pure lookup)                                                                                                         | Low                                                                     | Moderate                                                                    | Yes                                                                                        |
| Message Routing → Interactive UI + Queue                                 | Contract                                                                                                                       | Low                                                                     | High                                                                        | Yes                                                                                        |
| Polling Coordinator → 9 handler modules                                  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + temporal                               | Low                                                                     | High                                                                        | Yes — low distance absorbs high strength                                                   |
| Polling Strategies → `topic_state.register_bound`                        | Contract (bound method)                                                                                                        | Low                                                                     | Moderate                                                                    | Yes — no more compat wrappers                                                              |
| Terminal Screen Buffer ↔ Terminal Poll State (post-split)                | Read-only method calls                                                                                                         | Low                                                                     | Moderate                                                                    | Yes — clean split                                                                          |
| Toolbar Callbacks → `AgentProvider.scrape_current_mode`                  | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                            | Low                                                                     | High (Claude internal) / Low (provider count)                               | Yes — encapsulates Claude-specific knowledge                                               |
| Toolbar Keyboard ↔ Toolbar Callbacks                                     | Contract (`_set_action_label`, `build_toolbar_keyboard`)                                                                       | Low                                                                     | Moderate                                                                    | Yes — single-purpose files                                                                 |
| Shell Prompt Orchestrator → `shell_infra.setup_shell_prompt`             | Contract (policy → mechanics)                                                                                                  | Low                                                                     | Moderate                                                                    | Yes                                                                                        |
| 5 shell triggers → Shell Prompt Orchestrator                             | Contract (`ensure_setup` enum trigger)                                                                                         | Low                                                                     | Moderate                                                                    | Yes — one decision point                                                                   |
| Screenshot Callbacks → Status Bar Actions (split)                        | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes — cohesion win                                                                         |
| Send Command → Send Security                                             | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes                                                                                        |
| Send Callbacks → Send Command (public `upload_file`)                     | Contract (post-rename)                                                                                                         | Low                                                                     | Low                                                                         | Yes                                                                                        |
| Directory Callbacks → Provider capability flag (`has_yolo_confirmation`) | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes                                                                                        |
| Provider `__init__` → Session Manager (lazy)                             | Functional                                                                                                                     | Low                                                                     | High                                                                        | Acceptable; optional fix via `provider_name` parameter                                     |
| Hook Event Processing → Session Map Resolution (via `events.jsonl`)      | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (append-only file)                         | Medium (cross-process)                                                  | Moderate                                                                    | Yes — runtime-decoupled                                                                    |
| Inter-Agent Messaging mailbox                                            | Contract (filesystem)                                                                                                          | Medium (cross-process)                                                  | Moderate                                                                    | Yes                                                                                        |
| LLM Abstraction (Protocols)                                              | Contract                                                                                                                       | Low                                                                     | Low (functional) / Moderate (impl)                                          | Yes                                                                                        |
| Summariser → Claude JSONL                                                | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                               | Low                                                                     | Low (no new provider planned)                                               | Neutralised by [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) |
| Whisper Abstraction                                                      | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes                                                                                        |
| Telegram Helpers (entity formatting, rate limit, split)                  | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes                                                                                        |
| CLI Commands (doctor/hook/status) → Session & State                      | Contract                                                                                                                       | Low                                                                     | Low                                                                         | Yes                                                                                        |

**No Critical imbalances.** **No Significant imbalances** after the refactor lands. A handful of minor residues remain (residual `get_window_state` calls in mutating handlers, `providers/__init__.py` lazy import cycle, summariser Claude-hardcoding) — each neutralised by low [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) or listed as opportunistic cleanup.

## Design Decisions and Trade-offs

### Decision 1 — Split `message_queue.py` into 4 files (queue / tool_batch / status_bubble / routing)

**Considered alternatives:**

- _Leave as-is._ Rejected — the review's top pain (user-flagged) is message batching "feeling wrong"; internal [low cohesion](https://coupling.dev/posts/core-concepts/balance/) confirmed by the 1132-line module with 4 distinct concerns.
- _One mega-module, thicker docstring._ Rejected — cognitive load is measured in lines, not documentation.
- _Full Claude-provider extraction of tool_batch._ Rejected — only Claude emits tool_use/tool_result; moving tool_batch into `providers/claude.py` would couple the provider to Telegram I/O. The current location (inside Message Delivery) is correct; it just needs its own file.

**Chosen:** Extract `tool_batch.py` (~350 lines) and expand `status_bubble.py` (81 → ~300 lines) to own status send/clear. The queue module drops to ~500 lines of genuine queue primitives. Message batching becomes plug-point-able without the queue caring.

**Trade-off:** 3 new imports in `callback_registry`, one new file to open. Net win: addresses the #1 user pain, reduces cognitive load by >50% in the most-edited file.

### Decision 2 — Move Claude mode scraping to `AgentProvider.scrape_current_mode`

**Considered:**

- _Keep scraping in `toolbar_callbacks.py`._ Rejected — it's [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (reading another process's text output) in a handler that has no business knowing Claude's mode-line format.
- _New `mode_scraper.py` shared helper._ Rejected — the knowledge isn't shared; only Claude has mode lines. Creating a shared helper pretends otherwise.

**Chosen:** Add `scrape_current_mode(window_id) -> str | None` to `AgentProvider` protocol with default `return None`. Claude implements; Codex/Gemini/Shell return None. Toolbar calls the provider. This is the canonical way to encapsulate provider-specific knowledge in this codebase — the same pattern used for `parse_hook_payload`, `read_transcript_file`, etc.

**Trade-off:** Protocol grows by one method with a safe default. Gains: breakage from Claude Code's future mode-line changes stays in one file; toolbar code becomes provider-agnostic.

### Decision 3 — `shell_prompt_orchestrator.py` single entry point

**Considered:**

- _Leave predicates scattered across 5 handlers._ Rejected — user confirmed shell setup flow is a pain point; duplicated logic in 5 files is the source.
- _Fold the orchestrator into `shell_infra.py`._ Rejected — mechanics (which tmux keys to send) and policy (when to offer vs. skip vs. auto) are different concerns. `shell_infra` stays pure mechanics.
- _Make it a stateful class with persisted state._ Rejected for now — session-scoped state is enough; persistence can be added opportunistically.

**Chosen:** New module owning the 4-trigger decision tree (`"auto"`, `"external_bind"`, `"provider_switch"`, `"lazy"`) with an `ensure_setup(window_id, trigger)` entry point. 5 call sites migrate to one-line calls.

**Trade-off:** One new file, one new per-window state dict (candidate to fold into `WindowState` later). Gain: policy change = edit one file, not grep-five-handlers.

### Decision 4 — `topic_state.register_bound` for instance methods; split `TerminalStatusStrategy`

**Considered:**

- _Full `polling_coordinator` inversion (plan's Task 11)._ Rejected again — the plan correctly deferred this. The inline helpers make the loop readable; the real pain is elsewhere.
- _Metaclass magic_ to auto-register decorated class methods. Rejected — too magical for a single-maintainer codebase. `register_bound(scope, self.method)` in `__init__` is explicit and obvious.
- _Leave 20+ compat wrappers._ Rejected — they hide where cleanup lives.

**Chosen:** 10-line change to `topic_state_registry.py` to accept bound methods. `TerminalStatusStrategy.__init__` calls `topic_state.register_bound("window", self.clear_state)` etc. Delete all 20+ module-level wrappers. Split `TerminalStatusStrategy` into `TerminalScreenBuffer` and `TerminalPollState` along its natural seam (one owns pyte/cache, the other owns the 5 state machines).

**Trade-off:** Small registry change, one class split, a few import updates. Gain: 90 lines of pure indirection deleted, cleanup registration visible at the method definition.

### Decision 5 — Incremental `WindowView` migration, not full

**Considered:**

- _Full migration to `WindowView` everywhere._ Rejected — unnecessary churn; many handlers legitimately mutate and need `get_window_state`.
- _Split `SessionManager` into multiple facades._ Rejected — god-object pattern tolerable at solo-dev distance; splitting adds ceremony without payback.
- _`WindowContext` aggregation for all scattered per-window dicts._ Rejected — multi-week refactor; payoff dominated by the other 4 decisions.

**Chosen:** Opportunistic migration of 7 one-call-read handlers (`file_handler`, `history`, `shell_commands`, `text_handler`, `send_command`, `screenshot_callbacks`, `topic_emoji`). Pair with other edits in those files. Track via grep count. New handlers default to `WindowView` for reads.

**Trade-off:** The handler count on `session_manager.get_window_state` drops gradually, not all at once. Mutation cascades persist (but those are rare). Incremental and low-risk.

### Decision 6 — Keep `summarizer.py` Claude-hardcoded (defer)

**Rationale:** User confirmed a second agent provider is unlikely in the near term. Moving summariser into the provider protocol now would be speculative generality. The [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) of the "second provider for summarisation" axis is low. Leave it; revisit if a second provider ships.

**Trade-off:** The file is technically wrong (generic LLM module contains provider-specific parsing). Accepted because fixing it adds cost without near-term benefit.

## Unresolved Risks

1. **`providers/__init__.py → session_manager` lazy import cycle** remains. Minor — optional fix via `provider_name: str | None = None` parameter. Revisit if the lazy import causes a concrete debugging incident.

2. **Scattered per-window module-level dicts** (~24 dicts including the new `toolbar_callbacks._window_action_labels`). No full `WindowContext` aggregation planned. Mitigation: adopt a **stopping rule** — new per-window state goes in `WindowState` or a named strategy instance, not a new module-level dict. Revisit if the count crosses 30.

3. **`summarizer.py` Claude-hardcoding** — deferred as documented above. Revisit if a second agent provider is added.

4. **`polling_coordinator.status_poll_loop` inline section ordering** is undocumented. Risk: a developer reorders sections without understanding that transcript discovery must precede status scanning. Mitigation: add a 10-line comment block at the top of `status_poll_loop` explaining the ordering constraint. Not a structural change.

5. **Tool batching only works for Claude** — if a future Codex release grows tool-event streaming, batching needs a provider-level hook. Current design assumes Claude is the only source. Document as a known limitation in `tool_batch.py`.

6. **Test coverage for the refactor target** — the test specs in each `tests.md` are written against the _target_ state. They will fail if implemented against the current code. Implementation should follow the design + tests as a single migration, not test-first against stale files.

7. **Formatter churn in design docs** — prettier ran after every write, so the tables in `docs/design/2026-04-13/*/design.md` are formatted slightly differently from the inline drafts. No functional change.

## Next Steps

1. Self-review the design (Step 6 — next task).
2. Implementation plan: sequence the 6 refactor decisions by payoff/risk. Recommendation:
   - Fortnight 1: `tool_batch.py` extraction + `status_bubble.py` expansion (highest-payoff).
   - Fortnight 2: `shell_prompt_orchestrator.py` + `topic_state.register_bound` + `TerminalStatusStrategy` split.
   - Fortnight 3: `scrape_current_mode` provider capability + toolbar split.
   - Opportunistic: `WindowView` migration, residual leak fixes, status_bar_actions extraction.

Each refactor is independent and can be merged alone. No flag days; no multi-module atomic changes.

---

_This architecture was designed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
