# Telegram UX Overhaul

## Overview

Six-theme UX overhaul derived from a Telegram Bot API capability audit (2026-04-27) plus a 33-finding UX flow audit of the current ccgram handlers. Goal: close information-design gaps, adopt native Bot API streaming/feedback primitives that landed in 2025-2026 (Bot API 7.0–9.6), make multi-pane agent teams first-class, and lay the groundwork for an optional Mini App dashboard.

Ships across three releases:

- **v2.12 — Telegram polish (Themes 1-4)**: information-design quick wins, reactions as universal feedback, `sendChatAction`/`sendMessageDraft` adoption, recovery/resume rework. All communication-layer + handler code, no new subsystems.
- **v2.13 — Multi-pane teams (Theme 5)**: per-pane status, subscriptions, naming, lifecycle notifications.
- **v3.0 — Mini App dashboard (Theme 6)**: optional web view (xterm.js terminal, transcript search, multi-pane grid, AskUserQuestion forms).

Themes are independent within a phase. Phases run sequentially; each phase ships as its own release. Theme 6 is gated on validation that v2.12+v2.13 don't already solve enough.

## Context (from discovery)

- **Audit findings**: 33 UX issues across 10 flows. 9 high-severity, ~14 medium, ~10 low. Cluster around: invisible pending state (FLOW-1a), recovery/resume confusion (FLOW-2a/b), interactive UI cognitive load (FLOW-10a), multi-pane blindness (FLOW-4a/b/c), shell-LLM silence (FLOW-5a).
- **Capability gaps**: `sendMessageDraft` (Bot API 9.5, native streaming), `setMessageReaction` (Bot API 7.0, persistent acks), `CopyTextButton` (Bot API 8.0, one-tap copy), `show_caption_above_media`, `editForumTopic` icon, scoped `setMyCommands`, Mini App full-screen.
- **Files affected (Phase 1)**: `handlers/recovery_callbacks.py`, `handlers/restore_command.py`, `handlers/resume_command.py`, `handlers/interactive_ui.py`, `handlers/voice_*.py`, `handlers/shell_commands.py`, `handlers/text_handler.py`, `handlers/topic_orchestration.py`, `handlers/status_bubble.py`, `handlers/tool_batch.py`, `handlers/message_sender.py`, `handlers/message_queue.py`, `handlers/msg_telegram.py`, `handlers/send_callbacks.py`.
- **Files affected (Phase 2)**: `window_state_store.py`, `handlers/window_tick.py`, `handlers/polling_strategies.py`, `handlers/status_bubble.py`, `handlers/screenshot_callbacks.py`, `handlers/callback_data.py`.
- **Files affected (Phase 3)**: new `src/ccgram/miniapp/` subpackage, `cli.py`, `bot.py`.
- **Patterns to follow**: `safe_reply`/`safe_edit`/`safe_send` for entity-based formatting; `rate_limit_send()` for outbound throttling; `TopicStateRegistry.register_bound()` for per-topic state cleanup; `topic_state_registry` decorator for callback registration; tests mirror source under `tests/ccgram/`.
- **PTB integration for new API methods**: PTB `Bot` exposes raw API access via `Bot.do_api_request(method, data)` (or via the existing httpx layer in `telegram_request.py`). No PTB wrapper required for `sendMessageDraft` / `setMessageReaction`.

## Development Approach

- **Testing approach**: Regular (code first, then tests) — matches ccgram convention.
- Complete each task fully before moving to the next.
- Make small, focused changes.
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task.
  - Tests are not optional — they are a required part of the checklist.
  - Cover both success and error scenarios.
- **CRITICAL: all tests must pass before starting next task** — no exceptions.
- **CRITICAL: update this plan file when scope changes during implementation**.
- Run `make check` (fmt + lint + typecheck + test) after each task.
- Maintain backward compatibility throughout — no breaking config or state-file changes.

## Testing Strategy

- **Unit tests**: required for every task, mirror source layout under `tests/ccgram/`.
- **Integration tests** (`tests/integration/`): added when handler dispatch or PTB routing changes. Use the `_do_post` patch pattern from `tests/integration/test_message_dispatch.py`.
- **Manual device testing** (Post-Completion): each theme requires real-device verification on iOS + Android + Desktop because rendering of new entity types and inline-button behavior differs by client.
- **Bot API method probing**: for `sendMessageDraft`, test bot must run against a real Telegram server (Bot API 9.5+). Add a one-time integration probe that calls the method against `@BotFather`-issued test bot and asserts no `400 method not found`.

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.

## Solution Overview

### Phase 1 — v2.12 (Themes 1-4)

Order chosen so each task builds on the last and reuses infrastructure:

1. **Theme 1** first (info-design quick wins) — pure text/keyboard, no API. Fast confidence builder.
2. **Theme 3** (reactions) — introduces a `react()` helper used by Themes 4 and 2.
3. **Theme 4a** (`sendChatAction`) — small, instantly visible polish.
4. **Theme 4b** (`sendMessageDraft`) — architecture change to streaming. Biggest task in Phase 1.
5. **Theme 2** (recovery rework) — touches recovery flow comprehensively, can use Theme 3 reactions.

### Phase 2 — v2.13 (Theme 5)

`WindowState` gains a `panes: dict[pane_id, PaneInfo]` map. Polling-strategy layer surfaces pane state continuously. Status bubble renders per-pane status block. Inline alerts include pane names. New `pane_subscribe` and `pane_rename` callbacks. Lifecycle notifications gated by per-window setting.

### Phase 3 — v3.0 (Theme 6)

New `src/ccgram/miniapp/` package serves a single-page web app via aiohttp on a configurable port. Telegram inline button opens `https://<host>/app/<signed_token>`. Token validates `Telegram.WebApp.initData` HMAC. Three Phase 3 surfaces: live xterm.js terminal, transcript search, multi-pane grid. AskUserQuestion HTML form is Phase 3.5 (deferred to v3.1 if v3.0 lands smaller).

## Technical Details

### `sendMessageDraft` integration

- Helper at `src/ccgram/telegram_draft.py`: `class DraftStream` with `async start(initial_text)`, `async append(delta)`, `async finalize(final_text)`.
- Calls API via `bot.do_api_request("sendMessageDraft", data={...})`.
- Fallback path: on first call returning `400 method not found`, set process-wide flag `_DRAFT_UNAVAILABLE = True`, all subsequent `DraftStream` instances degrade to `editMessageText` polling (current code).
- Probed once at startup: `ccgram doctor` adds a `[draft-streaming]` check.
- Tool-batch (`tool_batch.py`) uses `DraftStream` for tool_use messages so the batched output streams as it grows.
- Status bubble (`status_bubble.py`) uses `DraftStream` for the bubble itself; content-hash gating becomes a no-op when streaming is active.

### `setMessageReaction` helper

- New helper `react(bot, chat_id, message_id, emoji)` in `handlers/message_sender.py`.
- Wraps `bot.set_message_reaction(chat_id, message_id, [ReactionTypeEmoji(emoji=emoji)])` (PTB exposes this directly since v21).
- Allowed emojis are restricted by Telegram to a fixed set; helper validates against `ALLOWED_REACTIONS = {"👀","✅","❌","🤔","📬","⚙","🔥",...}` (subset of Telegram's allowed list — verify exact set during Task 3.1).
- Failure modes: graceful — log warning, fall back to existing toast.

### Recovery banner unification

- `RecoveryBanner` dataclass in `handlers/recovery_callbacks.py`: holds chat_id, thread_id, window_id, mode (`dead` / `restore` / `resume`).
- One render function builds the keyboard with subtitle help text and provider-aware button labels.
- `/restore` invokes the same render (no new logic — just re-shows the banner).
- `/resume` keeps the cross-project picker but uses the new entry formatter (timestamp + last-4 + msg count).

### Per-pane WindowState

- New `PaneInfo` dataclass in `window_state_store.py`: `pane_id`, `name`, `provider`, `last_active_ts`, `subscribed`, `state` (active/idle/blocked).
- `WindowState.panes: dict[str, PaneInfo]`.
- Migration: empty dict on load — backward compatible.
- Pane scanner (currently in `window_tick.py`) becomes a `PaneStatusStrategy` in `polling_strategies.py`.

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): all code, tests, doc updates inside the ccgram repo.
- **Post-Completion** (no checkboxes): manual device testing (iOS/Android/Desktop), Bot API method probing in production-like environment, deployment of Mini App backend (Phase 3 only).

## Implementation Steps

---

### Phase 1 — v2.12 — Themes 1-4

---

### Task 1.1: Theme 1 — Recovery keyboard subtitles + interactive UI instructions

**Files:**

- Modify: `src/ccgram/handlers/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/interactive_ui.py`
- Modify: `tests/ccgram/handlers/test_recovery_callbacks.py`
- Modify: `tests/ccgram/handlers/test_interactive_ui.py`

- [x] add `_recovery_help_text()` helper in `recovery_callbacks.py` returning provider-aware subtitle ("Continue last session · Resume from list · Start fresh") and prepend to recovery banner message body
- [x] in `interactive_ui.py` `format_interactive_message()`, prepend instruction line: "↑↓ select · Enter confirm · Esc cancel · type to enter text"
- [x] verify line stays inside 4096-char limit even with long terminal captures (split if needed)
- [x] write tests for new help text rendering (recovery banner, all three modes)
- [x] write tests for interactive instruction line presence + length safety
- [x] run `make check` — must pass before next task

### Task 1.2: Theme 1 — Resume picker timestamps + session-id last-4

**Files:**

- Modify: `src/ccgram/handlers/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/resume_command.py`
- Modify: `tests/ccgram/handlers/test_recovery_callbacks.py`
- Modify: `tests/ccgram/handlers/test_resume_command.py`

- [x] add `_format_session_entry(session_meta)` helper rendering "{relative_time} · {summary[:40]} · {sid_last4}"
- [x] use new formatter in both `_send_resume_picker` (recovery callbacks) and `/resume` command picker
- [x] sort entries newest-first (by mtime)
- [x] handle missing/zero mtime ("never" fallback)
- [x] write unit tests for `_format_session_entry` (today/yesterday/n-days-ago/never)
- [x] write tests for picker ordering (newest first)
- [x] run `make check`

### Task 1.3: Theme 1 — Pending message disclosure + remaining info-design fixes

**Files:**

- Modify: `src/ccgram/handlers/text_handler.py`
- Modify: `src/ccgram/handlers/topic_orchestration.py`
- Modify: `src/ccgram/handlers/voice_handler.py`
- Modify: `src/ccgram/handlers/send_callbacks.py`
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/cli.py` (register `/live` alias)
- Modify: `src/ccgram/handlers/screenshot_callbacks.py` (handle `/live` direct invocation)
- Modify: `tests/ccgram/handlers/test_text_handler.py`
- Modify: `tests/ccgram/handlers/test_voice_handler.py`
- Modify: `tests/ccgram/test_shell_commands.py`

- [x] in `text_handler.py` queue-pending path: send disclosure "💬 Will deliver once the agent starts." after directory browser opens
- [x] in `voice_handler.py` unbound-topic path: same disclosure pattern (rejection reworded — voice has no queue, so message clarifies that voice messages aren't queued and the user should send text first)
- [x] rewrite `send_callbacks.py` "Session expired" → "Browser expired — use /send to restart"
- [x] in `shell_commands.py`: on first message in a shell topic per session, append one-time hint "Tip: prefix `!` to skip LLM."
- [x] register `/live` slash command in `bot.py` + `screenshot_callbacks.py` (plan said `cli.py` but that file is the Click CLI; Telegram command handlers live in `bot.py`)
- [x] update bot command list (`setMyCommands`) to include `/live` (added to `_BOT_COMMANDS` in `cc_commands.py`)
- [x] write tests: pending disclosure (text + voice), browser-expired wording, `/live` shortcut, `!` hint shows once per session
- [x] run `make check`

### Task 1.4: Theme 3 — `react()` helper + reaction allowlist

**Files:**

- Create: `src/ccgram/handlers/reactions.py`
- Modify: `src/ccgram/handlers/message_sender.py` (re-export `react`)
- Create: `tests/ccgram/handlers/test_reactions.py`

- [x] verify exact Telegram-allowed reaction set for bots (Bot API docs, `getAvailableReactions` if applicable)
- [x] create `reactions.py` with `ALLOWED_REACTIONS: frozenset[str]` and `async react(bot, chat_id, message_id, emoji, *, fallback_toast: str | None = None)`
- [x] graceful failure: catch `BadRequest`, log warning, optionally answer with `fallback_toast` via callback
- [x] dedupe: track last reaction per (chat_id, message_id) in-memory to skip no-op edits
- [x] write tests for: success path, disallowed emoji rejection, BadRequest fallback, dedupe behavior
- [x] run `make check`

### Task 1.5: Theme 3 — Replace toasts with reactions across handlers

**Files:**

- Modify: `src/ccgram/handlers/voice_callbacks.py`
- Modify: `src/ccgram/handlers/msg_telegram.py`
- Modify: `src/ccgram/handlers/send_callbacks.py`
- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/status_bar_actions.py` (notify mode toggle)
- Modify: existing test files for each handler

- [x] voice send: react 👀 on receive, ✅ on delivery (replace `query.answer("✓ Sent")`)
- [x] /send delivery: react ✅ on success, keep current text for denial reasons
- [x] inter-agent peer message arriving: react 📬 on the most recent user message in the topic
- [x] shell command run: react ⚙ on start, ✅ on exit-0, ❌ on non-zero
- [x] notification mode toggle: react with the new mode's icon on the bubble
- [x] keep toast fallback when reaction call fails (helper already does this)
- [x] update tests to assert reaction calls instead of toasts where applicable
- [x] run `make check`

### Task 1.6: Theme 4a — `sendChatAction` for shell LLM + agent forward

**Files:**

- Modify: `src/ccgram/handlers/shell_commands.py`
- Modify: `src/ccgram/handlers/text_handler.py`
- Modify: `tests/ccgram/test_shell_commands.py`
- Modify: `tests/ccgram/handlers/test_text_handler.py`

- [x] in `shell_commands.py` `handle_shell_message`: send `sendChatAction("typing")` immediately on entry, before LLM call; refresh every 4s while generating (Telegram action expires after 5s)
- [x] in `text_handler.py` agent-forward path: send `sendChatAction("typing")` once on text dispatch (cheap signal that bot saw the message)
- [x] cancel/clear chat action when reply arrives or generation aborts
- [x] write tests: action sent before LLM, refresh loop, cleared on completion
- [x] run `make check`

### Task 1.7: Theme 4b — `DraftStream` helper + Bot API probe

**Files:**

- Create: `src/ccgram/telegram_draft.py`
- Modify: `src/ccgram/doctor_cmd.py`
- Create: `tests/ccgram/test_telegram_draft.py`

- [x] implement `class DraftStream` in `telegram_draft.py`: `start(initial_text) -> message_id`, `append(delta)`, `finalize(final_text)`, `abort()`
- [x] internal mode: `streaming` (uses `sendMessageDraft`) or `legacy` (current `editMessageText` loop). Mode is process-wide, set by first probe.
- [x] startup probe in `doctor_cmd.py`: try `bot.do_api_request("sendMessageDraft", {"chat_id": <self_id>, "text": "_probe_"})`; on `400` set `_DRAFT_UNAVAILABLE = True` and log (probe helper `probe_draft_availability` exposed; doctor reports cached flag — actual probe runs at bot startup)
- [x] doctor adds `[draft-streaming] available` / `[draft-streaming] degraded — Bot API <9.5` line
- [x] handle rate-limit/flood errors with backoff + degrade to legacy for that stream
- [x] write tests: streaming mode happy path, legacy fallback path, abort cleans up, append ordering
- [x] run `make check`

### Task 1.8: Theme 4b — Adopt `DraftStream` in tool_batch + status_bubble

**Files:**

- Modify: `src/ccgram/handlers/tool_batch.py`
- Modify: `src/ccgram/handlers/status_bubble.py`
- Modify: `src/ccgram/handlers/message_queue.py`
- Modify: `tests/ccgram/handlers/test_tool_batch.py`
- Modify: `tests/ccgram/handlers/test_status_bubble.py`

- [x] tool_batch: replace edit-in-place sequence with `DraftStream` for tool_use accumulation; on tool_result, finalize the stream
- [x] status_bubble: replace `editMessageText` polling with single `DraftStream` per bubble lifetime; bubble close = `finalize`
- [x] keep content-hash gating active only in legacy mode (skip when streaming)
- [x] message_queue: ensure DraftStream usage doesn't break merge logic (drafts are not mergeable — they're a single message)
- [x] write tests: streaming bubble updates, tool_use → tool_result transition, legacy fallback path still works (mock probe to disabled)
- [x] run `make check`

### Task 1.9: Theme 2 — Unified `RecoveryBanner` dataclass + render

**Files:**

- Modify: `src/ccgram/handlers/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/restore_command.py`
- Create: `tests/ccgram/handlers/test_recovery_banner.py`

- [x] add `RecoveryBanner` dataclass: `chat_id, thread_id, window_id, mode, provider`
- [x] add `render_banner(banner) -> (text, keyboard)` building both message body and inline keyboard with subtitle text from Task 1.1
- [x] migrate existing dead-window notification path to use `render_banner` (window_tick proactive + text_handler reactive both routed through it)
- [x] migrate `/restore` command to invoke `render_banner` with `mode="restore"` — re-shows banner instead of auto-running `--continue`
- [x] write tests: banner renders correctly for each mode, button counts, callback data shapes preserved
- [x] run `make check`

### Task 1.10: Theme 2 — Resume picker upgrades + Continue→Resume fallback + empty-state

**Files:**

- Modify: `src/ccgram/handlers/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/resume_command.py`
- Modify: `tests/ccgram/handlers/test_recovery_callbacks.py`
- Modify: `tests/ccgram/handlers/test_resume_command.py`

- [x] resume picker: include msg-count when transcript parser returns it cheaply; otherwise omit
- [x] empty-state for resume in cwd: edit keyboard message to "No sessions in this folder. [Browse other projects] [Start fresh]" instead of toast
- [x] continue → resume fallback: if `--continue` produces no session for cwd, auto-show resume picker
- [x] update toast wording for unrecoverable cases ("session file gone" etc.) to be specific
- [x] write tests: empty-state rendering, continue→resume fallback path, error toast wordings
- [x] run `make check`

### Task 1.11: Phase 1 — Verify + ship v2.12

- [x] run full test suite: `make test-all` (4005 passed, 30 skipped)
- [x] run integration tests: `make test-integration` (97 passed)
- [x] manual device testing matrix (skipped - not automatable, see Post-Completion)
- [x] update CHANGELOG.md with v2.12 entry covering all four themes
- [x] verify no regressions in `ccgram doctor` (all checks pass, includes new `[draft-streaming] available`)
- [x] tag `v2.12.0` and let release workflow run (skipped - not automatable, requires release workflow trigger)

---

### Phase 2 — v2.13 — Theme 5 (Multi-pane teams)

---

### Task 2.1: `PaneInfo` dataclass + `WindowState.panes` migration

**Files:**

- Modify: `src/ccgram/window_state_store.py`
- Modify: `tests/ccgram/test_window_state_store.py`

- [x] add `PaneInfo` dataclass: `pane_id: str`, `name: str | None`, `provider: str`, `last_active_ts: float`, `state: Literal["active","idle","blocked","dead"]`, `subscribed: bool`
- [x] add `panes: dict[str, PaneInfo] = field(default_factory=dict)` to `WindowState`
- [x] state-file backward compat: existing entries without `panes` load as empty dict
- [x] add `get_pane(window_id, pane_id)`, `upsert_pane(...)`, `remove_pane(window_id, pane_id)` helpers
- [x] write tests: load/save round-trip, missing-panes-key tolerance, helper CRUD
- [x] run `make check`

### Task 2.2: `PaneStatusStrategy` polling

**Files:**

- Modify: `src/ccgram/handlers/polling_strategies.py`
- Modify: `src/ccgram/handlers/window_tick.py`
- Create: `tests/ccgram/handlers/test_pane_status_strategy.py`

- [x] extract pane scanning from `window_tick.py` into new `PaneStatusStrategy` in `polling_strategies.py`
- [x] strategy responsibilities: enumerate panes, classify state (active/idle/blocked/dead), update `WindowState.panes`, detect transitions
- [x] auto-detect provider per pane via `detect_provider_from_pane` (sync `detect_provider_from_command` is used; tmux PaneInfo lacks pane_tty so the async ps fallback can't run during scan)
- [x] preserve existing blocked-pane interactive UI behavior (FLOW-4a)
- [x] write tests: pane enumeration, state classification, transition detection, dead-pane removal
- [x] run `make check`

### Task 2.3: Per-pane status block in main bubble + pane-named alerts

**Files:**

- Modify: `src/ccgram/handlers/status_bubble.py`
- Modify: `src/ccgram/handlers/interactive_ui.py`
- Modify: `tests/ccgram/handlers/test_status_bubble.py`
- Modify: `tests/ccgram/handlers/test_interactive_ui.py`

- [x] when window has >1 pane, render per-pane block under main agent line: "└ %5 active · %6 idle 2m · %7 ⏸ blocked"
- [x] block is collapsible (expandable_blockquote entity) when 4+ panes
- [x] interactive UI alert prepends pane name: "🔀 api-gateway (%5):" instead of "🔀 Pane (%5):"
- [x] write tests: bubble with 1/2/4+ panes, alert wording with named/unnamed panes
- [x] run `make check`

### Task 2.4: Pane subscribe / rename callbacks + keyboard

**Files:**

- Modify: `src/ccgram/handlers/callback_data.py`
- Modify: `src/ccgram/handlers/screenshot_callbacks.py`
- Create: `src/ccgram/handlers/pane_callbacks.py`
- Create: `tests/ccgram/handlers/test_pane_callbacks.py`

- [x] add callback constants: `CB_PANE_SUBSCRIBE`, `CB_PANE_UNSUBSCRIBE`, `CB_PANE_RENAME`
- [x] in `pane_callbacks.py`: handlers for subscribe toggle (sets `PaneInfo.subscribed`), rename (force-reply prompt → text capture)
- [x] `/panes` keyboard gains [Subscribe] [Rename] buttons per pane
- [x] subscribed pane: forward output via screen-buffer diff (PaneStatusStrategy emits `on_pane_output` with content-hash dedup; window_tick wires forwarder; transcript-based streaming deferred — pane capture is sufficient and provider-agnostic)
- [x] auto-clear subscription when pane dies (PaneStatusStrategy.reconcile_dead_panes drops the PaneInfo entry along with its subscribed flag and evicts the content-hash cache)
- [x] write tests: subscribe persistence, rename round-trip, output forwarding behavior, auto-clear on pane death
- [x] run `make check`

### Task 2.5: Pane lifecycle notifications (configurable)

**Files:**

- Modify: `src/ccgram/window_state_store.py` (add `pane_lifecycle_notify: bool`)
- Modify: `src/ccgram/handlers/polling_strategies.py`
- Modify: `src/ccgram/config.py` (new env var `CCGRAM_PANE_LIFECYCLE_NOTIFY`, default `false`)
- Modify: `tests/ccgram/handlers/test_pane_status_strategy.py`

- [x] when `pane_lifecycle_notify=true`, send one-line message "➕ pane %6 created" / "➖ pane %6 closed" in topic
- [x] toggle via `/panes` keyboard (per-window)
- [x] write tests: notifications fire on transitions when enabled, suppressed when disabled
- [x] run `make check`

### Task 2.6: Phase 2 — Verify + ship v2.13

- [x] run full test suite + integration (4120 passed, 30 skipped via `make test-all`; 97 passed via `make test-integration`)
- [x] manual device testing for multi-pane scenarios (skipped - not automatable; see Post-Completion)
- [x] update CHANGELOG.md with v2.13 entry
- [x] update `.claude/rules/architecture.md` with new pane-as-first-class model (skipped - sensitive-file permission denied; .claude/rules/ blocked at the harness level)
- [x] tag `v2.13.0` (skipped - not automatable, requires release workflow trigger)

---

### Phase 3 — v3.0 — Theme 6 (Mini App dashboard)

---

### Task 3.1: Mini App backend skeleton (aiohttp + signed tokens)

**Files:**

- Create: `src/ccgram/miniapp/__init__.py`
- Create: `src/ccgram/miniapp/server.py`
- Create: `src/ccgram/miniapp/auth.py`
- Create: `src/ccgram/miniapp/static/index.html`
- Modify: `src/ccgram/main.py` (start/stop server alongside bot)
- Modify: `src/ccgram/config.py` (add `CCGRAM_MINIAPP_HOST`, `CCGRAM_MINIAPP_PORT`, `CCGRAM_MINIAPP_BASE_URL`, default disabled)
- Create: `tests/ccgram/miniapp/test_server.py`
- Create: `tests/ccgram/miniapp/test_auth.py`

- [x] aiohttp app with one route `/app/<token>` + static file serving (also `/healthz` for readiness, `/static/{path}` for assets)
- [x] `auth.py`: HMAC-signed token generation (window_id + user_id + expiry), validation against Telegram WebApp `initData`
- [x] `index.html`: minimal SPA shell, loads JS modules per surface (Telegram WebApp SDK + payload meta-tag readback)
- [x] start server in `main.py` only when `CCGRAM_MINIAPP_BASE_URL` configured (`start_miniapp_if_enabled`/`stop_miniapp_if_enabled` wired into bot.py post_init/post_shutdown)
- [x] write tests: token sign/verify round-trip, expiry, initData HMAC validation, server route auth (22 tests across `test_auth.py` + `test_server.py`)
- [x] run `make check` (fmt + lint + typecheck + deptry + test + test-integration all green)

### Task 3.2: Inline button + WebApp launch

**Files:**

- Modify: `src/ccgram/handlers/status_bar_actions.py` (add 🪟 dashboard button)
- Modify: `src/ccgram/handlers/status_bubble.py` (button only when MINIAPP enabled)
- Modify: `tests/ccgram/handlers/test_status_bubble.py`

- [x] new button "🪟 Dashboard" using `WebAppInfo(url=signed_url)` opens Mini App scoped to current window
- [x] hide button when `CCGRAM_MINIAPP_BASE_URL` unset
- [x] write tests: button presence/absence, URL signing
- [x] run `make check`

### Task 3.3: Live xterm.js terminal surface

**Files:**

- Create: `src/ccgram/miniapp/static/terminal.js`
- Create: `src/ccgram/miniapp/api/terminal.py` (websocket endpoint streaming `tmux capture-pane`)
- Modify: `src/ccgram/miniapp/server.py` (mount websocket route)
- Create: `tests/ccgram/miniapp/test_terminal_api.py`

- [x] websocket `/ws/terminal/<token>` streams pane content (delta-based) at 200ms cadence
- [x] xterm.js client renders ANSI colors, handles resize
- [x] read-only Phase 3 (input is Phase 3.5)
- [x] write tests: websocket auth, delta streaming, disconnect cleanup
- [x] run `make check`

### Task 3.4: Transcript search surface

**Files:**

- Create: `src/ccgram/miniapp/static/transcript.js`
- Create: `src/ccgram/miniapp/api/transcript.py`
- Modify: `src/ccgram/miniapp/server.py`
- Create: `tests/ccgram/miniapp/test_transcript_api.py`

- [x] HTTP `/api/transcript/<token>` returns paginated JSON (cursor-based) — token-scoped to mirror terminal route; window_id derived from token payload, not path
- [x] HTTP `/api/transcript/<token>/search?q=...` returns matches with ±1 entry context, capped at 50, case-insensitive
- [x] re-uses existing transcript reader infrastructure (`session_query.get_recent_messages`)
- [x] frontend renders threaded view with date markers (`miniapp/static/transcript.js`, mounted below terminal in `index.html`)
- [x] write tests: pagination cursor, search relevance ordering, auth scoping (token sees only its window) — 16 tests in `tests/ccgram/miniapp/test_transcript_api.py`
- [x] run `make check` (4068 passed + 97 integration, lint+typecheck clean)

### Task 3.5: Multi-pane grid surface

**Files:**

- Create: `src/ccgram/miniapp/static/panes.js`
- Modify: `src/ccgram/miniapp/api/terminal.py` (multi-pane multiplex)
- Create: `tests/ccgram/miniapp/test_panes_grid.py`

- [x] grid view subscribes to all panes in window (one websocket per tile via `?pane=` query; `/api/panes/<token>` lists panes)
- [x] click pane → expand to focused terminal view (single-tile focused view with back button; tiles teardown subscriptions on switch)
- [x] re-uses subscription model from Theme 5 (`/api/panes/<token>` merges tmux state with `WindowState.panes` so name/state/subscribed flags carry through)
- [x] write tests: grid layout for 1/2/4 panes, focus transition, subscription lifecycle (13 tests in `tests/ccgram/miniapp/test_panes_grid.py`)
- [x] run `make check` (4081 passed + 97 integration, lint+typecheck clean)

### Task 3.6: Phase 3 — Verify + ship v3.0

- [x] run full test suite + integration (4191 passed + 30 skipped via `make test-all`; 97 passed via `make test-integration`; fmt/lint/typecheck all clean)
- [x] manual device testing (skipped - not automatable; see Post-Completion)
- [x] verify Mini App falls back gracefully when `CCGRAM_MINIAPP_BASE_URL` unset (verified: `main.py:212` short-circuits server start, `status_bar_actions.py:69-71` returns None for the dashboard button)
- [x] update CHANGELOG.md with v3.0 entry — major version note
- [x] update README.md with Mini App setup guide (TLS, reverse proxy, BotFather Web App URL config)
- [x] update CLAUDE.md with new `miniapp/` subpackage in module inventory (architecture.md update skipped - sensitive-file permission denied; .claude/rules/ blocked at the harness level)
- [x] tag `v3.0.0` (skipped - not automatable, requires release workflow trigger)

---

### Task N-1: Verify acceptance criteria across all phases

- [x] verify all Theme 1 audit findings (FLOW-1a, 2a, 2b, 5a, 9b, 10a, /live discoverability) closed — disclosure copy "💬 Will deliver once the agent starts." in `text_handler.py:55`; interactive instruction line in `interactive_ui.py:68`; "Browser expired — use /send to restart" in `send_callbacks.py:99`; `/live` registered in `bot.py:600` + `cc_commands.py:56`
- [x] verify Theme 3 reactions used in voice, /send, peer messages, shell, notify-toggle (≥5 sites) — 6 sites: `voice_callbacks.py` (REACT_SEEN/REACT_DONE), `send_callbacks.py` (REACT_DONE), `msg_telegram.py` (REACT_INBOX), `shell_capture.py` (per-exit-code), `shell_commands.py` (REACT_RUNNING), `status_bar_actions.py` (notify toggle)
- [x] verify Theme 4 streaming active when probe succeeds; legacy fallback verified by mocking unavailable API — `_DRAFT_UNAVAILABLE` flag + `set_draft_unavailable()` in `telegram_draft.py:81-110`; `tests/ccgram/test_telegram_draft.py` covers both modes
- [x] verify Theme 2 recovery flow uses single `RecoveryBanner` everywhere — `RecoveryBanner` + `render_banner` used in `recovery_callbacks.py`, `restore_command.py`, `text_handler.py`, `window_tick.py` (4 sites; no ad-hoc keyboards)
- [x] verify Theme 5 panes are first-class (visible in bubble, named, subscribable) on a 3-pane test team — code paths verified: `WindowState.panes` (`window_state_store.py:132`), per-pane status block in `status_bubble.py`, `PaneStatusStrategy` in `polling_strategies.py`, subscribe/rename callbacks in `pane_callbacks.py`. Live 3-pane test deferred to Post-Completion (manual)
- [x] verify Theme 6 Mini App is fully optional (default-off path works exactly as v2.13) — `main.py:212` short-circuits server start when `miniapp_base_url` empty; `status_bar_actions.py:69-71` returns None for the dashboard button
- [x] run final test suite: `make check && make test-integration && make test-e2e` — `make check` (fmt+lint+typecheck+unit+integration) green: 0 errors, 4193 unit + 97 integration passed. `make test-e2e` requires a configured Telegram bot+group chat (not automatable in this loop) — see Post-Completion
- [x] verify test coverage report meets ≥80% for new modules — pane_callbacks 93%, polling_strategies 87%, reactions 100%, recovery_callbacks 85%, telegram_draft 86%, miniapp/auth 92%, miniapp/server 87%, miniapp/api/terminal 90%, miniapp/api/transcript 91%; total 87% across new modules

### Task N: Final — Update documentation

- [x] update `README.md` with new commands (`/live`), Mini App setup section — `/live` mentioned alongside Live button (`README.md:81`); Mini App setup section already in place (`README.md:260-294`); env vars in Configuration Reference table (`README.md:251-254`)
- [x] update `CLAUDE.md` Configuration section with new env vars (`CCGRAM_PANE_LIFECYCLE_NOTIFY`, `CCGRAM_MINIAPP_*`) — env vars already documented (`CLAUDE.md:87-88`); added `/live` to bot commands list (`CLAUDE.md:46`)
- [x] update `.claude/rules/architecture.md` with Mini App subsystem and pane-as-first-class — skipped (sensitive-file permission denied; `.claude/rules/` blocked at the harness level, same blocker as Tasks 2.6/3.6/N-1). Mini App + pane subsystem already documented in `CLAUDE.md` Architecture/Mini App sections.
- [x] move this plan to `docs/plans/completed/`

## Post-Completion

_Items requiring manual intervention or external systems — informational only_

**Manual device testing matrix** (per phase):

- iOS Telegram (latest + N-1)
- Android Telegram (latest)
- Telegram Desktop (macOS, Windows)
- Telegram Web

For each phase, exercise:

- new entity rendering (instruction lines, expandable blockquotes for pane block)
- reactions (Theme 3) — verify all chosen emojis are accepted by server
- streaming (Theme 4) — verify draft updates render smoothly without flicker
- Mini App (Theme 6) — verify launch button, WebApp initData parsing, websocket stability on cellular network

**External system updates**:

- BotFather: register Mini App URL after Phase 3 deploy (`/setdomain`, `/newapp`)
- TLS termination + reverse proxy required for Mini App in production (cloudflared, caddy, or nginx)
- Bot API version monitoring: announce v2.12 dependency on Bot API 9.5+ (graceful degradation, but feature parity requires it)

**Bot API method probing** (Phase 1):

- `sendMessageDraft` probe runs in `ccgram doctor`. After v2.12 ships, monitor Sentry/logs for the `_DRAFT_UNAVAILABLE` flag flips — indicates API regression or bot account on a stale region.
- `setMessageReaction` allowlist may shift; if Telegram changes allowed reactions, helper logs warnings — re-verify `ALLOWED_REACTIONS` quarterly.

**Performance considerations**:

- Streaming (Theme 4): observe per-message edit count vs current baseline; expect ~80% reduction in `editMessageText` calls.
- Mini App websocket: target ≤10 concurrent connections per ccgram instance for typical use; benchmark before announcing.
