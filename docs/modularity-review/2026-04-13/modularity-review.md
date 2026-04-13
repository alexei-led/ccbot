# Modularity Review

**Scope**: Entire ccgram codebase (post-refactor incremental review)
**Date**: 2026-04-13

## Context and Relationship to Prior Reviews

This review is a follow-up to the two prior reviews in `docs/modularity-review/2026-04-12/` (morning and evening) and the refactor plan in `docs/plans/completed/20260412-modularity-refactor.md`. It verifies what was resolved by the refactor and reframes what remains — plus three fresh cohesion issues introduced by the `/send` command, the TOML-configurable toolbar, and the tool-use batching feature that landed in commit `42475db`.

The analysis uses the [Balanced Coupling](https://coupling.dev/posts/core-concepts/balance/) model. Volatility classifications below were confirmed with the maintainer: session tracking, provider resolution, per-window state, message routing, and the polling loop are all [core subdomain](https://coupling.dev/posts/dimensions-of-coupling/volatility/) areas (high volatility). A second agent provider is **unlikely** in the near term, which downgrades the urgency of the known Claude-hardcoded paths (summarizer, mode-line scraping, residual string checks) from _fix soon_ to _fix when touched_.

## Executive Summary

ccgram is a solo-maintained Python bot that bridges agent CLIs (Claude Code, Codex, Gemini, shell) to Telegram Forum topics via tmux. The Apr 12 refactor successfully closed most of the prior review's quick wins — boundary violations in `providers/base.py` are gone, `UUID_RE` and `EXPANDABLE_QUOTE_*` live in their right homes, `session_map` duplication is deleted, and the `shell_commands ↔ shell_capture` circular import is broken via `shell_context.py`. The overall design remains **healthy with localised cohesion problems**.

The single most important finding: **`message_queue.py` did not actually shrink**. The `status_bubble.py` extraction pulled out only 81 lines (essentially just `build_status_keyboard`), but the 1132-line file absorbed a new concern — Claude tool-use batching — that embeds Claude-specific knowledge (`tool_use_id`, `TaskCreate`/`TaskUpdate` formatting) directly into the generic queue primitives. This is the user's "message batching feels wrong" pain: it is [low cohesion](https://coupling.dev/posts/core-concepts/balance/) masquerading as a single module, and it is the most active source of cognitive load in the handler layer today.

Four additional significant issues remain or emerged: toolbar dispatch blends TOML loading, key/text/builtin routing, and intrusive Claude pane-scraping in one 557-line module; the shell prompt-marker setup flow is scattered across five handlers with implicit ordering; `polling_coordinator.status_poll_loop` and `polling_strategies.py` still exhibit the god-loop + compat-wrapper-sprawl pair that Task 11 was meant to fix (deferral was deliberate, but the pain was confirmed by the user as still present); and the `WindowView` projection that was meant to relieve the state-shape cascade was introduced but adoption stalled — handler calls to `session_manager` grew from 62 to 77 across 26 files since the prior review.

## Coupling Overview

| Integration                                                                           | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                                             | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)                                                                |
| ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `message_queue` (queue + batch + Claude formatting in one module)                     | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (Claude tool schemas in generic queue) | — (internal)                                                            | High                                                                        | **No** — internal [low cohesion](https://coupling.dev/posts/core-concepts/balance/), user-confirmed pain                      |
| `toolbar_callbacks` (TOML loader + dispatch + Claude mode-line scraping)              | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (pane scraping)                    | — (internal) / High (Claude CLI)                                        | High (core) / Low (mode-line format)                                        | **No** — mixed cohesion; scraping fragile                                                                                     |
| Shell prompt-marker setup: 5 handlers + `shell_infra` with implicit order             | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (duplicate triggering logic)                                                                                              | Low                                                                     | Moderate                                                                    | **No** — duplicated setup triggers                                                                                            |
| `polling_coordinator.status_poll_loop` → 9 handler modules                            | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + temporal                                                                                                                | Low                                                                     | High                                                                        | Nominally yes, **internal [low cohesion](https://coupling.dev/posts/core-concepts/balance/)**                                 |
| `polling_strategies.py` → `topic_state_registry` via 20+ module-level wrappers        | [Contract](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (registry protocol can't bind instance methods)                                                                             | Low                                                                     | Moderate                                                                    | Yes mechanically, **No** aesthetically                                                                                        |
| Handlers → `SessionManager` (26 files, 77 calls)                                      | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                        | Low                                                                     | High (core)                                                                 | Borderline — `WindowView` exists but under-used                                                                               |
| `screenshot_callbacks.py` (4 concerns in 764 lines)                                   | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (mixed)                                                                                                                   | — (internal)                                                            | Moderate                                                                    | **No** — partial extraction, still a catch-all                                                                                |
| ~20 module-level per-window dict singletons across handlers                           | Low (independent)                                                                                                                                                                                               | Low                                                                     | High                                                                        | **No** — [low cohesion](https://coupling.dev/posts/core-concepts/balance/), pattern perpetuated by new `toolbar_callbacks.py` |
| `session.py` → `thread_router.window_display_names[wid]` direct dict access (3 sites) | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (private attr)                                                                                                             | Low                                                                     | Moderate                                                                    | Tolerable, but facade leak from inside the facade                                                                             |
| `send_callbacks` → `send_command._upload_file` (private import)                       | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                                            | Low                                                                     | Low                                                                         | Neutralised by low [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/)                                |
| `directory_callbacks:593` — `provider_name == "claude"` leftover                      | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                                                | Low                                                                     | Low                                                                         | Neutralised — one missed site                                                                                                 |
| `summarizer.py` — Claude JSONL hardcoded                                              | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                                                | Low                                                                     | Low (no new provider planned)                                               | Neutralised by [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) — known, deferred                  |

## Issue 1: `message_queue.py` — Tool-Use Batching Grafted onto Queue Primitives

**Integration**: `message_queue.py` (1132 lines) internal cohesion
**Severity**: Significant

### Knowledge Leakage

After the Apr 12 refactor, `message_queue.py` is supposed to own "queue primitives": per-user FIFO, worker task, merging, merge-at-dequeue, and rate limiting. It does all of those things. It also now owns, in the same module scope, a complete second subsystem — Claude Code tool-use batching:

- `ToolBatchEntry`, `ToolBatch` dataclasses encoding `tool_use_id`, `tool_use_text`, `tool_result_text`, `tool_name` — all [Claude-specific](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) concepts. Codex, Gemini, and shell providers do not emit tool_use/tool_result events at all.
- `format_batch_message()`, `_format_task_create_batch()`, `_format_mixed_batch_lines()`, `_format_task_create_section()`, `_format_task_update_section()`, `_format_task_list_section()`, `_batch_result_prefix()`, `_format_batch_entry()`, `_extract_task_create_title()`, `_extract_task_tool_suffix()` — ~160 lines of pure presentation logic that knows which Claude Code tool names mean "a sub-task spawn" (`TaskCreate`, `TaskUpdate`, `TaskList`) and formats them differently.
- `_process_batch_task()`, `_flush_batch()`, `_handle_content_task()`, `_active_batches` dict — state machine for "hold N tool calls, edit-in-place until the batch completes or fills".

This is [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) — the queue module has knowledge of how Claude's agent loop emits tool messages and how users expect them to be summarised. It is also [model coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) — the Claude agent's task-tool vocabulary is embedded in the formatting code. None of this knowledge is documented at the module level; the file's docstring is "Per-user message queue management for ordered message delivery".

The concern is not that batching exists — it's a useful feature and the user flagged it as "feeling wrong" rather than broken. The concern is that four distinct subsystems now share one module scope:

1. Queue primitives (queue, worker, merge, rate limiting) — genuinely cohesive.
2. Claude batch state machine (`ToolBatch`, `_active_batches`, `_process_batch_task`, `_flush_batch`).
3. Claude batch presentation (`format_batch_message` + 9 helpers).
4. Status-update send/clear (`_process_status_update_task`, `_process_status_clear_task`, `_do_send_status_message`, `_do_clear_status_message`, `_format_claude_task_status`).

Additionally, `MessageTask` is a union-shaped dataclass with a `task_type: Literal["content", "status_update", "status_clear"]` discriminator and a grab-bag of optional fields (`tool_use_id`, `tool_name`, `parts`, `text`), where most fields only apply to a subset of task types. This is a [common coupling](https://coupling.dev/posts/related-topics/module-coupling/) smell: readers must keep a mental model of which fields are legal in which states.

### Complexity Impact

A developer trying to change batch-flush behaviour — for example, "flush when the user sends a reply" — must read the 1132-line file to figure out where queue state, batch state, and status state interact. The queue worker `_message_queue_worker` calls `_handle_content_task`, which calls either `_process_batch_task` or `_process_content_task`, and batch task processing internally calls `_do_clear_status_message` (which is in the status-update subsystem). These interleavings exceed the [cognitive capacity](https://coupling.dev/posts/core-concepts/complexity/) of working memory (4±1 units) because a single change can ripple through all four subsystems.

The Claude task-tool formatting helpers (`_format_task_create_section`, `_extract_task_tool_suffix` with its markdown-prefix regex parsing, `_TASK_TOOL_NAMES`) are particularly corrosive to cohesion: they parse presentation output from earlier in the pipeline (`build_response_parts`) back into structured form just to render it differently when batched. This is double parsing that exists only because the formatting logic lives in the wrong place — if it were in `status_bubble.py` or a new `tool_batch_view.py`, the original structured data would still be in scope.

### Cascading Changes

Adding a new status message format (say, a "resuming session" preview) has to coexist with the batching state machine because both write to the same `_active_batches` space via `_do_clear_status_message`. Changing Claude's task-tool presentation (even a format tweak) requires editing queue code. Fixing a queue bug touches batch code. Every change in any of the four subsystems forces the developer to re-load the other three into working memory to verify nothing broke.

The review plan's Task 6 promised that `message_queue.py` would be ~400–500 lines after status-bubble extraction. It is 1132. This is not an execution failure — the batching feature was added in the same commit and grew the module back. But it is a signal that `status_bubble.py` at 81 lines was not the real intended extraction: the right move was splitting queue from presentation from Claude-specific logic, not pulling out just the keyboard builder.

### Recommended Improvement

Break the four concerns apart. Concrete, in order of payoff-to-cost:

1. **Extract `handlers/tool_batch.py`.** Move `ToolBatchEntry`, `ToolBatch`, `_active_batches`, `_process_batch_task`, `_flush_batch`, `_handle_content_task`'s batch branch, `_is_batch_eligible`, `_should_batch`, `BATCH_MAX_ENTRIES`, `BATCH_MAX_LENGTH`, and every `_format_*` helper into it. The new module owns: "given a stream of Claude tool events, emit a rolling edit-in-place summary message". The queue module keeps the branch point (`if batch-eligible → tool_batch.process(...)` else → process normally). Expect ~350 lines moved.
2. **Move `_format_claude_task_status`, `_do_send_status_message`, and `_do_clear_status_message` into `status_bubble.py`.** These are status-bubble lifecycle operations. `message_queue` would import `status_bubble.send_status_text(...)` and `status_bubble.clear_status_text(...)` as [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/). `status_bubble.py` grows from 81 to ~300 lines and becomes a real module instead of a stub.
3. **Consider splitting `MessageTask` into three discriminated types**: `ContentTask`, `StatusUpdateTask`, `StatusClearTask`. The worker's dispatcher becomes an explicit `match task:` and readers no longer have to remember which optional fields are legal when. This is a two-file change with low risk — mypy/pyright will catch the migration sites.
4. **Do not touch merge or rate limiting.** Those are the actual queue primitives and they are cohesive where they are.

Trade-off: one more import in the callback-registry wire-up, one more file to open when reading the pipeline, and `MessageTask → ContentTask/StatusUpdateTask/StatusClearTask` adds ~40 lines of type definitions. Against that, `message_queue.py` drops to ~500 lines of genuine queue logic, the Claude-specific surface is visible and renameable, and adding a hypothetical batch format tweak no longer requires reading queue code. The most important gain: the user's "feels wrong" instinct gets vindicated by the module boundary matching the conceptual boundary.

## Issue 2: `toolbar_callbacks.py` — Three Concerns + Intrusive Claude Pane Scraping

**Integration**: `toolbar_callbacks.py` (557 lines) internal cohesion + scraping → Claude pane text
**Severity**: Significant

### Knowledge Leakage

The toolbar is a new feature: TOML-configurable per-provider button grids, with "read-state" toggles that scrape the pane after a key press to reflect the agent's current mode. The module owns three distinct concerns:

1. **Config plumbing**: `_get_toolbar_config`, `reload_toolbar_config`, `build_toolbar_keyboard`, `_make_button`. Reads `toolbar_config.ToolbarConfig`, honours per-window label overrides from `_window_action_labels`, renders `InlineKeyboardMarkup`. This is UI rendering.
2. **State scraping**: `_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`, `seed_button_states`, `_refresh_button_label`. Grabs the tmux pane text, runs regex against Claude Code's mode line ("auto-accept edits on", "Plan mode on", etc.), and maps the result to short button labels ("Edit", "Plan", "Full", "Def"). This is [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to Claude Code — it reads the internal text output of another process to infer its mode. The coupling is at the highest [integration strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) level because there is no contract: if Claude Code renames "auto-accept" to "auto-edit" in a future release, the toolbar breaks silently (wrong label, still works).
3. **Action dispatch**: `_dispatch_key`, `_dispatch_text`, `_builtin_screenshot`, `_builtin_ctrlc`, `_builtin_live`, `_builtin_send`, `_builtin_dismiss`, `_BUILTIN_DISPATCH`, `handle_toolbar_callback`, `_dispatch`, `_parse_callback_data`. Routes callback query → key send / text send / builtin function.

The module also owns its own scattered per-window state (`_window_action_labels: dict[str, dict[str, str]]`), following the same pattern the morning review flagged as the #1 modularity issue. The pattern's severity is mitigated here by `@topic_state.register("window")` cleanup registration, but the instance of the pattern is fresh code — the new module imported the anti-pattern instead of avoiding it.

The **scraping** concern in particular is coupling of the strongest kind — intrusive, implicit, and directed across a process boundary at an unstable text format. Claude Code's mode line is not a documented API. Gemini has a similar "YOLO" mode that would need its own scraping regex. Codex may or may not show a mode line at all. The current implementation restricts `_scrape_current_mode` to the `mode` action and silently does nothing for other toggles (YOLO, Think), but the pattern is there for any future toggle to copy, and the scraper already encodes three sentinel strings (`auto-accept edits`, `Plan mode`, `Full tool access`) specific to Claude's output format.

### Complexity Impact

A developer adding a new toggle button (say, a "Bypass safety" toggle for a hypothetical provider) has to: (a) add an action in `toolbar.toml`, (b) add a scraping regex to `_find_mode_line`, (c) add a mapping in `_mode_short_label`, (d) add a new attribute to `ToolbarAction` (`read_state: bool`), (e) set it on the provider's action in TOML, (f) ensure `_refresh_button_label` handles it. None of this is obvious from the file layout — all three concerns share the same 557 lines with no section boundaries larger than a 10-line helper.

A developer debugging "why does the button label not update" must chase across `seed_button_states` (called from `bot.toolbar_command`) → `_scrape_current_mode` (which does a pane capture + regex) → `_find_mode_line` (which looks at the bottom 15 lines of the pane) → `_mode_short_label` (which maps text to labels) → `_set_action_label` → `build_toolbar_keyboard` (which reads from `_get_action_label` inside `_make_button`). That's a 6-hop chain across three concerns.

### Cascading Changes

Changes in Claude Code's mode-line output (either `claude` itself, or a wrapper like `cc-mirror` that injects headers) silently break the mode toggle's label — the button still works, the label is just wrong until the next read. Nothing in the system detects or surfaces this.

Adding a new provider means also deciding how to handle its toggle state — either hardcode another scraping regex or give up and keep the static label. The `read_state: bool` flag and `_scrape_current_mode`'s hardcoded list of Claude sentinels is a local solution that doesn't scale without a provider-level callback for "return my current mode".

### Recommended Improvement

Three steps, each independent:

1. **Extract `handlers/toolbar_keyboard.py`** — move `build_toolbar_keyboard`, `_make_button`, `_window_action_labels`, `_set_action_label`, `_get_action_label`, `_clear_window_labels`, and the `@topic_state.register` cleanup. This is pure rendering + state.
2. **Extract mode scraping to a provider-level capability.** Add `AgentProvider.scrape_current_mode(window_id: str) -> str | None` to `providers/base.py`. Claude's implementation holds the regexes it owns. Codex/Gemini/Shell return `None`. `toolbar_callbacks._refresh_button_label` becomes: `label = await provider.scrape_current_mode(window_id) or action.default_label`. This converts [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (direct pane scraping with hardcoded regexes) to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (provider method returning a string) and puts the Claude-specific knowledge where it belongs — in `providers/claude.py`. The user's "new provider is unlikely" answer downgrades urgency, but this refactor also localises the breakage radius when Claude Code changes its mode line.
3. **Leave `toolbar_callbacks.py` as the dispatch module** (Keyboard, callback parsing, `handle_toolbar_callback`, `_dispatch_key`/`_dispatch_text`/`_builtin_*`). Expect it to shrink to ~300 lines.

Trade-off: one provider-protocol method addition, one new handler file. Against that, the `toolbar_*` code splits into three single-purpose files (keyboard, scraping, dispatch), scraping becomes provider-plug-in-able, and the TOML loader stays a small self-contained module. Most importantly, adding the next toggle is one TOML edit and one provider-method return value, not a 6-step cross-file scramble.

## Issue 3: Shell Prompt-Marker Setup — Distributed with Implicit Ordering

**Integration**: `shell_infra.setup_shell_prompt` called from 5 handler modules
**Severity**: Significant

### Knowledge Leakage

The shell provider uses a prompt marker (`⌘N⌘` in wrap mode, `{prefix}:N❯` in replace mode) so that command output can be isolated and exit codes detected. `shell_infra.setup_shell_prompt` does the actual work: ensure idle shell, detect shell binary, pick wrap vs. replace, inject the setup commands, optionally clear scrollback. It is also idempotent — `has_prompt_marker` short-circuits if the marker is already present.

The _decision_ about when to call `setup_shell_prompt` — and in which of the two setup-offer flows ("auto" vs. "ask") — is scattered:

- `handlers/directory_callbacks.py` (directory-browser → shell topic flow): calls setup immediately after window creation, "auto" mode.
- `handlers/window_callbacks.py` (external window bind → shell detected): shows "Set up / Skip" keyboard, user choice.
- `handlers/transcript_discovery.py` (runtime provider-switch detector): triggers the "ask" flow when an agent pane falls back to shell, and the re-offer on provider switch away and back.
- `handlers/shell_commands.py::_ensure_prompt_marker`: lazy recovery on every command send. Checks if the marker disappeared (e.g., `exec bash`, profile reload) and re-runs setup. Honours the user's session-scoped "skip" choice.
- `handlers/shell_capture.py`: reads the marker to parse output, implicitly depends on setup having run. Does not trigger setup itself but assumes a prior handler did.

Five handlers encode slightly different variants of the same decision tree: "has the user skipped for this session?", "is this a re-bind?", "should we offer or just do it?". The CLAUDE.md documents the intended behaviour clearly, but the intent is distributed across the handlers that each participate in one entry point. There is no single `shell_setup_orchestrator` object that owns the state machine.

The knowledge that leaks is [functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/): "when do we need to re-run setup?" — duplicated across five callers that each re-derive the answer from local context (skip-flag, marker presence, provider name, last-run timestamp).

### Complexity Impact

Changing the setup policy — for example, "never offer again once skipped, even on re-bind" — requires locating every caller and updating each one's predicate. Missing one caller leaves a subtle bug where the prompt-marker offer comes back in a path the user didn't expect. There is no single place to put a trace log of "who decided to run setup and why".

The flow is additionally coupled to [runtime timing](https://coupling.dev/posts/dimensions-of-coupling/distance/): `setup_shell_prompt` awaits 0.1s + 0.3s hard sleeps after `C-c` and after injecting the setup command. The `_wait_for_shell_ready` helper in `directory_callbacks.py` does its own polling. The two timing strategies coexist because they were added in different commits; neither is wrong, but they mean setup latency depends on which caller invoked it.

### Cascading Changes

Adding a new setup trigger (e.g., "re-setup if `tmux respawn-window` was used externally") means adding a 6th call site and deciding how its predicate relates to the existing 5. Removing an existing trigger requires reasoning about whether the others cover the same case. The CLAUDE.md's paragraph-long description of the decision tree is the only specification — no test enforces it.

### Recommended Improvement

Introduce a `ShellPromptCoordinator` (or a module `shell_prompt_orchestrator.py`) that owns the decision state: per-window `skip_flag`, `last_setup_ts`, `was_offered`, and a single `ensure_setup(window_id, trigger: Literal["auto", "ask", "lazy", "external_bind"]) -> None` entry point. Each of the five callers calls `ensure_setup(...)` with the trigger kind; the coordinator decides whether to offer, skip, or run silently, and returns. This converts [functional coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (duplicated predicates in 5 handlers) to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (single entry point with a documented trigger enum).

Keep `shell_infra.setup_shell_prompt` exactly as it is — it is the right layer for "actually inject the commands". The coordinator sits on top and owns policy only.

Trade-off: one new file (~100 lines), one new dict for per-window orchestration state (add to the existing scatter for now — or, preferably, fold into `WindowState` since it is window-scoped), and a migration of 5 call sites. Against that, the decision tree is in one place, testable end-to-end, and new triggers plug in at one point. The setup latency sleeps can also be refactored once, from one place.

## Issue 4: `polling_coordinator` Still a God Loop, `polling_strategies` Sprouts Compat Wrappers

**Integration**: `polling_coordinator.py` (598 lines) + `polling_strategies.py` (653 lines)
**Severity**: Significant

### Knowledge Leakage

Task 11 of the refactor plan (invert `polling_coordinator` to strategy-owned `tick()` methods) was deliberately deferred. The plan's justification was valid in the narrow: `status_poll_loop` itself is ~85 lines, the body is decomposed into named helpers (`_scan_window_panes`, `_maybe_check_passive_shell`, `_check_interactive_only`, `update_status_message`, `_handle_dead_window_notification`), and inverting would trade risk for cosmetic gain.

But the user confirmed that "polling/status code is hard to follow" is still a top pain point, and that pain has a more specific source than the god-loop framing captured: `polling_strategies.py` grew to 653 lines and now contains a 20-plus-function compat-wrapper layer at the bottom of the file:

```python
# polling_strategies.py L566-652 — 20+ wrappers
def clear_window_poll_state(window_id: str) -> None:
    terminal_strategy.clear_state(window_id)

def clear_screen_buffer(window_id: str) -> None:
    terminal_strategy.clear_screen_buffer(window_id)

def is_rc_active(window_id: str) -> bool:
    return terminal_strategy.is_rc_active(window_id)

# ... 17 more
```

The wrappers exist because `@topic_state.register` cannot bind instance methods — the cleanup registry needs free functions. So every class method that needs cleanup registration gets a module-level alias. The wrappers perform no logic; they are pure indirection.

The wrappers are also where the actual cleanup registration lives — the `@topic_state.register("window")` decorators are on the free functions, not the strategy methods. A reader looking at `TerminalStatusStrategy.clear_state` has no indication that it is the implementation of a registered cleanup callback. The knowledge "this method is a cleanup hook" is [implicitly](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) distributed: the decoration lives in one place, the implementation in another, and the only hint in the class method is the method name matching a free function below.

Separately, `polling_coordinator.py` still imports from 9 handler modules and orchestrates them in a specific order. The plan's deferral note is correct that the helpers make the loop readable in isolation, but adding a new concern still requires deciding _where_ in the sequence to inject it and _which_ imports to add.

### Complexity Impact

A developer debugging "cleanup not running on window close" must trace the cleanup registration from `topic_state.register("window")` → `clear_window_poll_state` (free function) → `terminal_strategy.clear_state` (instance method) → actual state dict clearing. The indirection serves the library constraint but obscures the logic.

Reading `polling_strategies.py` end-to-end is also a cohesion test: `TerminalStatusStrategy` is 270 lines with 31 methods covering RC debounce, probe failures, startup grace, pane count cache, pyte parsing, screen buffer pooling, recent-activity check. Some of these are cohesive (the pyte parsing and screen buffer go together), but startup-grace, probe-failures, and RC debounce are three independent state machines with no particular reason to share a class.

### Cascading Changes

Adding a new polling concern today means: (a) decide whether it goes in `status_poll_loop` as a new inline section or as its own `run_periodic_tasks` entry; (b) add imports to `polling_coordinator.py`; (c) if it has per-window state, add a method to one of the three strategies (which one?); (d) add a `@topic_state.register` wrapper function at the bottom of `polling_strategies.py`; (e) ensure the cleanup actually wires into the strategy method. Five steps across three files, with choices at each step.

### Recommended Improvement

The plan's Task 11 framing (invert to strategy-owned `tick()`) is more ambitious than this review recommends. A smaller, targeted fix:

1. **Let `topic_state.register` accept bound methods.** The registry is in `topic_state_registry.py` — change it to accept a callable and optionally a bound-method owner object. Once that works, the 20+ compat wrappers at the bottom of `polling_strategies.py` disappear, and `@topic_state.register("window")` moves onto the strategy method where the implementation actually lives. Net: ~90 lines deleted, cleanup registration becomes locally visible at the point of implementation.
2. **Split `TerminalStatusStrategy` into two classes** along its natural seam: `TerminalScreenBuffer` (pyte parsing, screen buffer pool, pane count cache, rendered text) and `TerminalPollState` (RC debounce, probe failures, startup grace, unbound timers, seen-status tracking, recent-activity). They share nothing except being per-window. Expect `polling_strategies.py` to be slightly shorter and each class to be understandable in one read.
3. **Leave `status_poll_loop` alone for now.** The plan's deferral was right: the real friction was in the strategy layer, not the loop. Revisit if a future feature adds a 10th polling concern.

Trade-off: a small change to `topic_state_registry` (maybe 10 lines), a class split, and a handful of import fixes. Against that: the strategy file drops ~90 lines of pure indirection, cleanup registration becomes visible in one place, and the "where does cleanup live" question has one answer instead of two.

## Issue 5: `WindowView` Projection Under-Adopted, Facade Surface Keeps Growing

**Integration**: Handlers → `session_manager` (26 files, 77 calls, up from 62 in the Apr 12 evening review)
**Severity**: Significant

### Knowledge Leakage

The Apr 12 refactor plan's Task 9 introduced `WindowView` as a [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) projection: a frozen dataclass exposing `window_id`, `cwd`, `provider_name`, `approval_mode`, `notification_mode`, `transcript_path`, with `session_manager.view_window(wid)` returning a snapshot. The goal was to decouple read-only handlers from the 39-method `SessionManager` facade so that shape changes to `WindowState` wouldn't cascade.

The implementation landed (file exists, `view_window` method exists, `toolbar_callbacks._builtin_send` and `toolbar_callbacks._refresh_button_label` use it). But adoption plateaued at a handful of call sites. The current counts:

- 27 files import `session_manager`
- 77 direct `session_manager.` calls across 26 handler files (up from 62)
- `sync_command` (10 calls), `transcript_discovery` (7), `recovery_callbacks` (6), `directory_callbacks` (4), `restore_command` (5), `polling_coordinator` (5), `resume_command` (5), `command_orchestration` (4), etc.

The facade is used as the default access point for everything window-related, including pure reads. New handlers (`send_command`, `toolbar_callbacks`, `message_routing`) import `session_manager` as a matter of habit. `WindowView` is a relief valve that only a few callers turn on.

The ratio change (62 → 77) is significant because it means the refactor's _read-side_ decoupling lost ground even as the _mutation-side_ remained stable. This is [accidental volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) — the write-volatility of `WindowState` shape is low, but the ease of "just reach into the facade" increases the read-side exposure with every new feature.

### Complexity Impact

Renaming `WindowState.cwd` to `working_dir` today still cascades to ~20 handlers because most of them call `session_manager.get_window_state(wid).cwd` directly. The cascade is manageable with an IDE refactor, but every change to the facade pushes ripples across the entire handler layer, and a developer modifying `WindowState` cannot see at a glance which fields are safely read-only from which handlers.

`session.py` also reaches past its own facade: at three sites (L412, L414, L495) it accesses `thread_router.window_display_names[wid]` as a raw dict instead of calling `thread_router.set_display_name` / `thread_router.get_display_name`. This is a minor internal [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) smell — the facade leaks into its own implementation.

### Cascading Changes

The user confirmed state-shape cascades are still a top-3 pain point. The `WindowView` mitigation exists on paper but is underused, so the pain persists. Adding a new field to `WindowState` means updating `WindowView` too (easy), but removing or renaming an existing field still cascades because most handlers go through the facade.

### Recommended Improvement

Two small, opportunistic moves:

1. **Migrate one-call-read handlers to `view_window` as they are touched.** The list from the Apr 12 evening review still applies: `file_handler`, `history`, `shell_commands`, `text_handler`, `send_command`, `screenshot_callbacks`, `topic_emoji`. Each is a 2-line change (`get_window_state(...).cwd` → `view_window(...).cwd`). Don't force a big migration; pair each with whatever you're already editing there. Track via `grep -c 'session_manager\.get_window_state' src/ccgram/handlers/*.py` — when it drops below 15, the cascade pain is gone.
2. **Fix the three direct `thread_router.window_display_names` dict accesses inside `session.py`.** Replace with the public `get_display_name` / `set_display_name` / `pop` helpers that already exist. Ten-minute change.

Trade-off: the `WindowView` approach does not address mutation cascades, but the user's pain is read-side: "state shape changes cascade to 25+ handlers". Most of those 25 only read. Progress is measurable and reversible.

## Issue 6: `screenshot_callbacks.py` — Still 4 Concerns in One Module

**Integration**: `screenshot_callbacks.py` (764 lines)
**Severity**: Minor

### Knowledge Leakage

The Apr 12 refactor extracted `toolbar_callbacks.py` from this module, dropping it from ~832 to 764 lines. But four concerns still coexist in the same scope:

1. **Screenshot capture / refresh**: `screenshot_command`, `_handle_refresh`, `_handle_pane_screenshot`, `_handle_status_screenshot`, `build_screenshot_keyboard`.
2. **Live view**: `_handle_live_start`, `_handle_live_stop`.
3. **Status-bar actions that have nothing to do with screenshots**: `_handle_notify_toggle` (notification mode cycling), `_handle_status_recall` (command history recall), `_handle_remote_control`, `_handle_status_esc`, `_handle_keys`, `_schedule_key_refresh`.
4. **Multi-pane operations**: `panes_command` (69 lines).

The `_handle_status_*` family are the most out-of-place: they handle status-bubble button callbacks that have nothing intrinsically to do with screenshots. They live here because `build_screenshot_keyboard` historically returned a keyboard with control keys attached, and the callbacks landed wherever was convenient. The module now imports from `send_command`, `interactive_ui`, `polling_strategies`, `command_history`, `shell_capture`, `live_view`, `message_queue`, `history` (eight handler dependencies), and defines 34 imports total.

### Complexity Impact

A developer working on "cycle notification mode when user taps the 🔔 button" has to read a 764-line file named "screenshot_callbacks". The naming lies: most of the file is not about screenshots. This is a [low-cohesion](https://coupling.dev/posts/core-concepts/balance/) drift, not a coupling failure — distance is low, volatility moderate, strength normal — but it increases the cognitive cost of every edit.

### Cascading Changes

Not much: the module is a catch-all but most of its pieces are independent. Adding a new status-bar action means adding a handler function in this file alongside unrelated screenshot logic. The cost is search-and-open-file friction, not cascading edits.

### Recommended Improvement

Finish the partial extraction:

1. **Extract `handlers/status_bar_actions.py`** — `_handle_notify_toggle`, `_handle_status_recall`, `_handle_remote_control`, `_handle_status_esc`, `_handle_keys`, `_schedule_key_refresh`, `_pending_key_refreshes`, related `@topic_state.register` cleanup. ~200 lines out.
2. **Consider merging `live_view.py` functionality in.** Or leave it — `live_view.py` already owns its own state and lifecycle; the two `_handle_live_*` handlers could move there instead.
3. **Result**: `screenshot_callbacks.py` drops to ~350 lines covering only screenshot and pane-screenshot operations. Matches its name.

Trade-off: one new handler file, one more `@register` import. Low risk, low payoff, do it next time the file is touched.

## Issue 7: Scattered Per-Window Module-Level Dicts — Pattern Perpetuated

**Integration**: ~20 `_prefixed` module-level dicts across handler modules
**Severity**: Minor (but the pattern persists as new handlers arrive)

### Knowledge Leakage

The Apr 12 morning review flagged this as the #1 issue ("scattered per-window handler state, 15+ modules"). The evening review demoted it to "still open — long-term direction". Today the pattern is unchanged in _structure_ but stronger in _scope_:

```
command_history._history, toolbar_callbacks._window_action_labels,
text_handler._bash_capture_tasks,
interactive_ui._interactive_msgs, _interactive_mode, _send_cooldowns,
shell_commands._shell_pending, _generation_counter,
topic_emoji._topic_states, _pending_transitions, _topic_names,
topic_orchestration._topic_create_retry_until,
msg_telegram._loop_alert_pairs,
message_sender._last_send_time, _rate_limit_locks,
live_view._active_views,
shell_capture._shell_monitor_state,
message_queue._message_queues, _queue_workers, _queue_locks,
  _tool_msg_ids, _status_msg_info, _active_batches,
screenshot_callbacks._pending_key_refreshes,
```

That's ~24 scattered state dicts, and `toolbar_callbacks.py` (new this cycle) added one — the pattern reproduced. `topic_state_registry.py` event bus catches cleanup (26 `@register` call sites), but discovery of "what state exists for window @5" remains a manual grep.

### Complexity Impact

Adding a new feature with per-window state means: create a new module-level dict, register a cleanup, trust that the cleanup wires correctly. Miss the registration and you leak state. The pattern works; it just doesn't scale as the handler count grows.

### Cascading Changes

None directly. The scatter doesn't cause cascading edits — it causes a slow accumulation of state-discovery friction. The cost is moderate but monotonic.

### Recommended Improvement

The morning review's `WindowContext` aggregation is still the correct long-term direction but the wrong investment _today_. Instead, adopt a **stopping rule**: no new `_per_window: dict[str, ...]` singletons in new handler modules. New per-window state goes into `WindowState` (for persistent) or a named dataclass held in one of the existing strategy singletons (for ephemeral).

For `toolbar_callbacks._window_action_labels` specifically: it is small (one dict per window with one-or-two entries). Folding it into `WindowState` would be ~15 lines and remove one of the 24 singletons. Do it next time you touch toolbar state.

Trade-off: `WindowState` grows; new features must pick a home consciously. Against that: the scatter stops increasing.

## Issue 8: Residual Leaks from the Refactor

**Integration**: Scattered loose ends
**Severity**: Minor

Three small items the refactor plan missed or introduced. None are urgent; each is a 10-minute fix best done the next time the surrounding code is touched.

1. **`handlers/directory_callbacks.py:593`**: `if approval_mode == "yolo" and provider_name == "claude":`
   The plan's Task 8 (replace `provider_name ==` string checks with capability flags) found and fixed all but this one. Should be a `provider.capabilities.has_yolo_confirmation` or similar flag, or — given the user's "new provider unlikely" answer — left as-is with the same tolerance as the summarizer Claude-hardcoding.

2. **`session.py` L412, L414, L495**: direct dict access `thread_router.window_display_names[wid]`.
   Internal facade leak — SessionManager reaches past its own sub-object. Public helpers `get_display_name` / `set_display_name` / `pop_display_name` exist. 3-line fix.

3. **`handlers/send_callbacks.py:35`**: `from .send_command import _upload_file, build_file_browser`.
   Private-name import (`_upload_file`). Either promote `_upload_file` to `upload_file` in `send_command.py` (it's already called from a sibling callback module, so it isn't really private) or move it into a shared `send_upload.py` alongside `build_file_browser`. The refactor plan promoted `open_file_browser` but missed `_upload_file`.

## Issue 9: `summarizer.py` Still Claude-Hardcoded

**Integration**: `llm/summarizer.py` → Claude JSONL transcript format
**Severity**: Minor (neutralised by low [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/))

The evening review flagged this as provider-abstraction leakage #3. The Apr 12 plan explicitly deferred it ("only matters once a second provider needs summaries"). That rationale is confirmed by the user's answer: a second provider is unlikely, so the Claude-hardcoded parsing (`type == "assistant"`, `type == "user"`, `tool_use`, `tool_result`, `content` blocks) is tolerable.

Left in the review to document the trade-off: the design is wrong (summarisation is a provider capability, not a generic LLM helper), but the right-design fix is deferred until it pays back. If a second provider lands, expect a `AgentProvider.summarise_recent(entries) -> list[str]` addition and a one-week migration.

## Priority Ranking

Today's high-payoff work, roughly in order:

1. **Break up `message_queue.py`** — extract `tool_batch.py` (~350 lines), grow `status_bubble.py` with status-send/clear helpers, optionally split `MessageTask` into discriminated types. _Payoff: addresses the top user-flagged pain directly._
2. **Extract `handlers/toolbar_keyboard.py` + provider `scrape_current_mode` capability** — three modules become three files with single concerns; mode scraping becomes provider-owned.
3. **Introduce `shell_prompt_orchestrator`** — single decision point for the five setup triggers, predicate logic in one file.
4. **Let `topic_state.register` accept bound methods; split `TerminalStatusStrategy`** — deletes ~90 lines of compat wrappers and improves cleanup visibility. Smaller and safer than the plan's Task 11 inversion.
5. **Migrate 5–7 one-call-read handlers from `get_window_state` to `view_window`** — opportunistic, not a full migration.

Do when touching the affected code:

6. Finish `screenshot_callbacks` extraction (status-bar actions out).
7. Residual leaks — 3 small fixes.
8. Stop adding new `_per_window: dict[...]` singletons in new modules.

Don't do:

- Full handler-state aggregation into `WindowContext` — still a multi-week refactor with payoff dominated by items 1–4.
- Full provider extraction for `summarizer.py` — deferred correctly.
- Full `polling_coordinator` inversion to strategy `tick()` methods — the registry fix + class split captures most of the win for a fraction of the risk.

## Summary

The Apr 12 refactor delivered on its quick wins. Half the evening review's issues are cleanly resolved. The three remaining pain points the user named — adding a provider, state-shape cascades, polling code — persist in modified form: adding a provider is now cheap enough given the "no new provider planned" constraint, state-shape cascades persist because `WindowView` adoption stalled, and polling pain is concentrated in `polling_strategies.py`'s compat-wrapper layer rather than in the loop itself. The three new pain points surfaced this review — message batching, toolbar dispatch, shell prompt-marker setup — were all introduced by the `/send` / toolbar / batching feature bundle in commit `42475db`. None require large structural rewrites. Every recommendation above is incremental, reversible, and addresses a coupling imbalance in the [Balanced Coupling](https://coupling.dev/posts/core-concepts/balance/) sense rather than a matter of taste.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._

---

## Resolution

Resolved by [20260413-architecture-refactor](../../plans/completed/20260413-architecture-refactor.md). All actionable recommendations from this review were addressed across 15 implementation tasks covering message queue decomposition, polling strategy extraction, shell prompt orchestration, toolbar module split, provider capability flags, WindowView migration, and documentation updates.
