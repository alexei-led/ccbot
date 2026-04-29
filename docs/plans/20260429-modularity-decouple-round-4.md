# Modularity Decouple — Round 4

## Overview

Execute the six findings from `docs/plans/20260429-modularity-review.md`
in order: F1 → F4 → F2 → F3 → F5 → F6. Goal: shrink per-task context
size, lower coupling, raise testability — without changing user-facing
behavior.

The review summary:

- **F1.** Group flat `handlers/` (50+ peer modules) into feature
  subpackages. Hard cut — rewrite import sites, no compat shims.
- **F4.** Split `window_tick.py` (694 lines, 22 funcs, 12 collaborators)
  into pure `decide` / I/O `observe` / DI `apply`.
- **F2.** Constructor DI for `SessionManager` / `WindowStateStore` /
  `ThreadRouter` / `UserPreferences` / `SessionMapSync`. Eliminate
  `_wire_singletons` monkey-patching and the silent `unwired_save`
  default. Make all `register_*_callback` failures explicit.
- **F3.** Extract `handlers/registry.py` (command table) and
  `bootstrap.py` (post_init wiring) from `bot.py`. Bot.py shrinks to
  ~150 lines.
- **F5.** Introduce `TelegramClient` Protocol + adapter. Gradual
  per-module migration. Handlers depend on the Protocol, not
  `telegram.Bot`.
- **F6.** Audit and eliminate the ~30 in-function imports left over
  after F1+F2.

## Context (from discovery)

Files / components involved:

- All of `src/ccgram/handlers/` (50+ modules).
- `src/ccgram/session.py` (SessionManager singleton, `_wire_singletons`).
- `src/ccgram/window_state_store.py`, `thread_router.py`,
  `user_preferences.py`, `session_map.py`, `state_persistence.py`
  (singletons + `unwired_save` default).
- `src/ccgram/bot.py` (723 lines: command table + post_init wiring +
  callback registration + miniapp boot).
- `src/ccgram/handlers/window_tick.py` (orchestrator god module).
- `src/ccgram/handlers/{message_queue,status_bubble,...}.py` (PTB types
  in inner logic — F5 targets).
- All `tests/` directories (170 test files; will need fixture updates
  for F2).

Patterns observed:

- Subpackage example already exists: `src/ccgram/miniapp/` is the right
  shape (subpackage, narrow public API, only entry points reach in).
- Pure decision kernel pattern: `TickContext`/`TickDecision`/`decide_tick`
  in `polling_strategies.py` is the template for F4.
- Provider Protocol pattern: `AgentProvider` + `ProviderCapabilities` +
  `registry` in `providers/` is the template for F5.
- Test conventions: `asyncio_mode = "auto"`, no test docstrings, mirror
  source layout under `tests/`.

Dependencies identified:

- `make check` (fmt + lint + typecheck + test + integration) is the
  green-light gate. It must pass after every task.
- Test integration uses real PTB Application + `_do_post` patch — this
  pattern survives F5 (the adapter wraps PTB, so integration tests still
  exercise PTB internally).
- E2E tests (`tests/e2e/`) use real agent CLIs + tmux but no Telegram —
  they are unaffected by F5.

## Development Approach

- **Testing approach:** Regular (code first, then add/update tests).
- Complete each task fully before moving to the next.
- Make small, focused changes. One subpackage move per task in F1; one
  store extraction per task in F2; one waved migration per task in F5.
- **CRITICAL: every task MUST include new/updated tests** for code
  changes in that task — see Testing Strategy.
- **CRITICAL: `make check` MUST pass before moving to next task.**
- **CRITICAL: update this plan file when scope changes during
  implementation.**
- Maintain backward compatibility for state files (`state.json`,
  `session_map.json`) — schema is stable.
- Each task is its own commit so history reads as small reviewable steps.

## Testing Strategy

**Per-task discipline:**

- Pure refactors (F1 file moves, F4 split): existing tests must pass
  unchanged. Update import paths in tests where source moved. Add
  unit tests only when a new pure seam appears (e.g. F4 `decide_tick`
  isolated module).
- Structural refactors (F2 constructor DI, F3 bootstrap): replace
  singleton-mutation tests with fixtures that build a test
  `SessionManager` from stub stores. Add new tests that exercise the
  failure modes the silent defaults used to hide.
- Behavioral additions (F5 Protocol + adapter): new unit tests for the
  Protocol fake; integration tests stay on real PTB but exercise the
  adapter on the way in/out.
- F6: each in-function import removed must be covered by a static
  import-cycle test (or the existing test suite confirms no breakage).

**Test commands:**

- Unit: `make test`
- Integration: `make test-integration`
- All except e2e: `make test-all`
- E2E (only at end of F1, F2, F4, and final): `make test-e2e`
- Type check: `make typecheck` (must be 0 errors)
- Lint: `make lint`
- Full gate: `make check`

**E2E note:** This project has `tests/e2e/` exercising real agent CLIs +
tmux. It does not exercise Telegram. Run e2e at the end of phases F1,
F2, F4, and at the final task — once per phase is enough; e2e is
expensive (~3–4 min).

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.
- Keep plan in sync with actual work done.

## Solution Overview

Six phases, sequential. Each phase preserves user-visible behavior
and ends with `make check` green.

```
Phase F1  (~1 day)   handlers/ → feature subpackages (12 moves)
Phase F4  (~0.5 day) window_tick.py → window_tick/{decide,observe,apply}/
Phase F2  (~2 days)  Constructor DI for stores + SessionManager
Phase F3  (~0.5 day) Extract handlers/registry.py + bootstrap.py
Phase F5  (~3 days)  TelegramClient Protocol + adapter, gradual migration
Phase F6  (~0.5 day) Audit + eliminate residual in-function imports
```

Total: ~7.5 working days. Order chosen by leverage and risk:

- F1 first because it makes every later phase cheaper (smaller blast
  radius per file move).
- F4 second because it isolates a pure kernel that F2 and F5 then build
  on cleanly.
- F2 unlocks honest unit tests, which de-risks F5.
- F3 falls out of F2 (bot.py mostly empties anyway).
- F5 last among heavy work — its blast radius is the largest, and it
  benefits maximally from F1/F2/F3 already landed.
- F6 is sweeping cleanup; most in-function imports vanish naturally
  during F1+F2.

## Technical Details

### Subpackage layout (F1)

```
src/ccgram/handlers/
├── __init__.py            (existing — keep doc only)
├── callback_data.py       (stays at top — pure constants)
├── callback_helpers.py    (stays at top — pure helpers)
├── callback_registry.py   (stays at top — wiring infra)
├── cleanup.py             (stays at top — used by all)
├── command_history.py     (stays at top — small leaf)
├── command_orchestration.py (stays at top — top-level orchestrator)
├── file_handler.py        (stays at top — leaf, used directly by bot)
├── hook_events.py         (stays at top — wired in bootstrap)
├── response_builder.py    (stays at top — pure formatter)
├── sessions_dashboard.py  (stays at top — top-level command)
├── sync_command.py        (stays at top — top-level command)
├── upgrade.py             (stays at top — top-level command)
├── user_state.py          (stays at top — pure constants)
├── interactive/           interactive_ui, interactive_callbacks
├── live/                  live_view, screenshot_callbacks, pane_callbacks
├── messaging/             msg_broker, msg_delivery, msg_telegram, msg_spawn
├── messaging_pipeline/    message_queue, message_routing, message_sender,
│                          message_task, tool_batch
├── polling/               polling_coordinator, polling_strategies,
│                          periodic_tasks, window_tick
├── recovery/              recovery_callbacks, restore_command,
│                          resume_command, transcript_discovery,
│                          history, history_callbacks
├── send/                  send_command, send_callbacks, send_security
├── shell/                 shell_commands, shell_capture, shell_context,
│                          shell_prompt_orchestrator
├── status/                status_bubble, status_bar_actions, topic_emoji
├── text/                  text_handler
├── toolbar/               toolbar_keyboard, toolbar_callbacks
├── topics/                topic_orchestration, topic_lifecycle,
│                          directory_browser, directory_callbacks,
│                          window_callbacks
└── voice/                 voice_handler, voice_callbacks
```

Each subpackage `__init__.py` re-exports the public surface used by
`bot.py` / `bootstrap.py` after F3, so call sites are stable on the new
layout. Hard cut — no `handlers/X.py` shim files.

### Constructor DI shape (F2)

Before:

```python
# session.py (excerpt)
def _wire_singletons(self) -> None:
    window_store._schedule_save = self._save_state
    window_store._on_hookless_provider_switch = self._clear_session_map_entry
    thread_router._schedule_save = self._save_state
    thread_router._has_window_state = lambda wid: wid in window_store.window_states
    user_preferences._schedule_save = self._save_state
    session_map_sync._schedule_save = self._save_state
```

After:

```python
# Each store accepts callbacks in __init__:
class WindowStateStore:
    def __init__(
        self,
        schedule_save: Callable[[], None],
        on_hookless_provider_switch: Callable[[str], None],
    ) -> None: ...

class ThreadRouter:
    def __init__(
        self,
        schedule_save: Callable[[], None],
        has_window_state: Callable[[str], bool],
    ) -> None: ...

# SessionManager constructs them rather than reaching into globals:
class SessionManager:
    def __init__(self, *, persistence, ...) -> None:
        self._persistence = persistence
        self._window_store = WindowStateStore(
            schedule_save=self._save_state,
            on_hookless_provider_switch=self._clear_session_map_entry,
        )
        self._thread_router = ThreadRouter(
            schedule_save=self._save_state,
            has_window_state=lambda wid: self._window_store.has_window(wid),
        )
        ...
```

The module-level singleton `session_manager = SessionManager()` is
preserved (single-process bot still wants one global), but it is now
the _only_ call site that constructs the dependency graph. Tests build
a `SessionManager` from stub stores via a fixture.

`unwired_save` default disappears entirely.

### TelegramClient Protocol shape (F5)

```python
# src/ccgram/telegram_client.py
class TelegramClient(Protocol):
    async def send_message(
        self, chat_id: int, text: str, *,
        message_thread_id: int | None = None,
        reply_markup: ReplyMarkup | None = None,
        parse_mode: str | None = None,
        entities: list[MessageEntity] | None = None,
        disable_notification: bool = False,
    ) -> Message: ...

    async def edit_message_text(
        self, chat_id: int, message_id: int, text: str, *, ...
    ) -> Message | bool: ...

    async def edit_message_media(
        self, chat_id: int, message_id: int, media: InputMedia, *, ...
    ) -> Message | bool: ...

    async def answer_callback_query(self, callback_query_id: str, ...) -> bool: ...

    async def send_chat_action(self, chat_id: int, action: ChatAction, *, ...) -> bool: ...

    async def create_forum_topic(self, chat_id: int, name: str, *, ...) -> ForumTopic: ...

    async def edit_forum_topic(self, chat_id: int, message_thread_id: int, *, ...) -> bool: ...

    async def close_forum_topic(self, chat_id: int, message_thread_id: int) -> bool: ...

    async def delete_message(self, chat_id: int, message_id: int) -> bool: ...

    async def send_photo(...) -> Message: ...
    async def send_document(...) -> Message: ...
    async def get_file(...) -> File: ...

# Adapter wraps a real PTB Bot:
class PTBTelegramClient(TelegramClient):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot
    async def send_message(self, ...) -> Message:
        return await self._bot.send_message(...)
    ...

# Tests build a fake:
class FakeTelegramClient(TelegramClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
    async def send_message(self, **kw) -> Message: ...
```

The Protocol exposes only methods the codebase actually uses (verified
by grep before defining each). Handlers take `client: TelegramClient`
instead of `bot: Bot`. Migration is wave-by-wave per the user's
preference.

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): code moves, file
  creations, test updates, lint/typecheck fixes — all in-tree.
- **Post-Completion** (no checkboxes): manual smoke test of bot in a
  real Telegram group; `ccgram doctor` against a clean `~/.ccgram/`;
  integration with emdash if maintainer uses it.

---

## Implementation Steps

### Phase F1 — Group `handlers/` into feature subpackages

Each task creates one subpackage, moves the listed modules into it,
adds a `__init__.py` that re-exports the public surface, and rewrites
all import sites in the codebase. After each task: `make check` passes.

Order chosen so leaf subpackages move first; orchestrators move last.
This keeps each task's diff small.

#### Task F1.1: Create `handlers/messaging_pipeline/` subpackage

**Files:**

- Create: `src/ccgram/handlers/messaging_pipeline/__init__.py`
- Create: `src/ccgram/handlers/messaging_pipeline/message_queue.py`
- Create: `src/ccgram/handlers/messaging_pipeline/message_routing.py`
- Create: `src/ccgram/handlers/messaging_pipeline/message_sender.py`
- Create: `src/ccgram/handlers/messaging_pipeline/message_task.py`
- Create: `src/ccgram/handlers/messaging_pipeline/tool_batch.py`
- Delete: `src/ccgram/handlers/{message_queue,message_routing,message_sender,message_task,tool_batch}.py`
- Modify: every importer of those modules (grep + rewrite).
- Create: `tests/ccgram/handlers/messaging_pipeline/` (mirror layout).

- [x] create subpackage skeleton with `__init__.py` re-exporting current public API
- [x] move five modules into the subpackage (git mv for history preservation)
- [x] rewrite all import sites: `from .message_queue` → `from .messaging_pipeline.message_queue` (and equivalents from outside `handlers/`)
- [x] move corresponding tests from `tests/ccgram/handlers/` into mirror layout
- [x] verify `make typecheck` passes (0 errors)
- [x] verify `make test` passes (no behavior change expected)
- [x] commit "refactor(handlers): group messaging_pipeline subpackage"

#### Task F1.2: Create `handlers/polling/` subpackage

**Files:**

- Create: `src/ccgram/handlers/polling/__init__.py`
- Move: `polling_coordinator.py`, `polling_strategies.py`, `periodic_tasks.py`, `window_tick.py`
- Modify: import sites
- Create/move tests

- [x] create subpackage with `__init__.py` re-exporting `status_poll_loop`, `terminal_screen_buffer`, `terminal_poll_state`, `lifecycle_strategy`, `pane_status_strategy`, `tick_window`, `run_periodic_tasks`, `run_lifecycle_tasks`, `run_broker_cycle`
- [x] git mv four modules
- [x] rewrite import sites (bot.py, status_bubble.py — the RC callback wiring; etc.)
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group polling subpackage"

#### Task F1.3: Create `handlers/topics/` subpackage

**Files:**

- Move: `topic_orchestration.py`, `topic_lifecycle.py`, `directory_browser.py`, `directory_callbacks.py`, `window_callbacks.py`
- Note: `topic_emoji.py` goes to `handlers/status/` (it owns status emoji), not here

- [x] create subpackage; re-export `handle_new_window`, `adopt_unbound_windows`, `topic_closed_handler`, `topic_edited_handler`, `clear_browse_state`, plus directory browser builders
- [x] git mv five modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group topics subpackage"

#### Task F1.4: Create `handlers/recovery/` subpackage

**Files:**

- Move: `recovery_callbacks.py`, `restore_command.py`, `resume_command.py`, `transcript_discovery.py`, `history.py`, `history_callbacks.py`

- [x] create subpackage with `__init__.py` re-exporting `RecoveryBanner`, `render_banner`, `build_recovery_keyboard`, `restore_command`, `resume_command`, `discover_and_register_transcript`, `send_history`
- [x] git mv six modules (history goes here because it's the "browse past sessions" surface — same conceptual cluster as resume)
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group recovery subpackage"

#### Task F1.5: Create `handlers/messaging/` subpackage

**Files:**

- Move: `msg_broker.py`, `msg_delivery.py`, `msg_telegram.py`, `msg_spawn.py`

- [x] create subpackage; re-export `broker_delivery_cycle`, `delivery_strategy`, `notify_message_to_telegram`, spawn types
- [x] git mv four modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group inter-agent messaging subpackage"

#### Task F1.6: Create `handlers/shell/` subpackage

**Files:**

- Move: `shell_commands.py`, `shell_capture.py`, `shell_context.py`, `shell_prompt_orchestrator.py`

- [x] create subpackage; re-export `show_command_approval`, `register_approval_callback`, `gather_llm_context`, `redact_for_llm`, prompt orchestrator entry points
- [x] git mv four modules
- [x] rewrite import sites (notable: bot.py post_init wires shell approval callback — F3 will simplify this further)
- [x] move tests
- [x] `make check` passes (manual: send a message in a shell topic in dev — already covered by integration tests)
- [x] commit "refactor(handlers): group shell subpackage"

#### Task F1.7: Create `handlers/status/` subpackage

**Files:**

- Move: `status_bubble.py`, `status_bar_actions.py`, `topic_emoji.py`

- [x] create subpackage; re-export `build_status_keyboard`, `register_rc_active_provider`, `convert_status_to_content`, `clear_status_message`, `update_topic_emoji`, `format_topic_name_for_mode`, `strip_emoji_prefix`
- [x] git mv three modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group status subpackage"

#### Task F1.8: Create `handlers/interactive/` subpackage

**Files:**

- Move: `interactive_ui.py`, `interactive_callbacks.py`

- [x] create subpackage; re-export `handle_interactive_ui`, `clear_interactive_msg`, `get_interactive_window`, `set_interactive_mode`, `clear_interactive_mode`, callback handlers
- [x] git mv two modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group interactive subpackage"

#### Task F1.9: Create `handlers/live/` subpackage

**Files:**

- Move: `live_view.py`, `screenshot_callbacks.py`, `pane_callbacks.py`

- [x] create subpackage; re-export `live_command`, `panes_command`, `screenshot_command`, `apply_pane_rename`, live-view tick functions
- [x] git mv three modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group live/screenshot subpackage"

#### Task F1.10: Create `handlers/send/` subpackage

**Files:**

- Move: `send_command.py`, `send_callbacks.py`, `send_security.py`

- [x] create subpackage; re-export `send_command`, callback handlers, security validators
- [x] git mv three modules
- [x] rewrite import sites
- [x] move tests
- [x] `make check` passes
- [x] commit "refactor(handlers): group send subpackage"

#### Task F1.11: Create `handlers/toolbar/` subpackage

**Files:**

- Move: `toolbar_keyboard.py`, `toolbar_callbacks.py`

- [ ] create subpackage; re-export `build_toolbar_keyboard`, `seed_button_states`, callback dispatcher
- [ ] git mv two modules
- [ ] rewrite import sites
- [ ] move tests
- [ ] `make check` passes
- [ ] commit "refactor(handlers): group toolbar subpackage"

#### Task F1.12: Create `handlers/voice/` subpackage and `handlers/text/` for text_handler

**Files:**

- Move: `voice_handler.py`, `voice_callbacks.py` → `handlers/voice/`
- Move: `text_handler.py` → `handlers/text/`

- [ ] create both subpackages; re-export `handle_voice_message`, voice callbacks; re-export `handle_text_message`
- [ ] git mv three modules
- [ ] rewrite import sites
- [ ] move tests
- [ ] `make check` + `make test-e2e` pass (last F1 task — run full e2e to verify nothing regressed across all subpackage moves)
- [ ] commit "refactor(handlers): group voice and text subpackages (F1 complete)"

#### Task F1.13: F1 verification

- [ ] verify only the listed top-level files remain in `handlers/`: `__init__.py`, `callback_data.py`, `callback_helpers.py`, `callback_registry.py`, `cleanup.py`, `command_history.py`, `command_orchestration.py`, `file_handler.py`, `hook_events.py`, `response_builder.py`, `sessions_dashboard.py`, `sync_command.py`, `upgrade.py`, `user_state.py`
- [ ] verify `bot.py` imports look like `from .handlers.recovery import restore_command` (subpackage clarity)
- [ ] verify CLAUDE.md handler table reflects new layout (defer the rewrite to the final docs task — no double-edit)
- [ ] `make check` green; commit if any final fixups landed

---

### Phase F4 — Split `window_tick.py` into decide / observe / apply

#### Task F4.1: Extract pure decision kernel

**Files:**

- Create: `src/ccgram/handlers/polling/window_tick/__init__.py`
- Create: `src/ccgram/handlers/polling/window_tick/decide.py`
- Create: `src/ccgram/handlers/polling/window_tick/observe.py`
- Create: `src/ccgram/handlers/polling/window_tick/apply.py`
- Delete: `src/ccgram/handlers/polling/window_tick.py` (replaced by package)
- Create: `tests/ccgram/handlers/polling/window_tick/test_decide.py`

- [ ] move `TickContext`, `TickDecision`, `decide_tick` and the small pure helpers (`is_shell_prompt`, `_build_status_line`) into `decide.py` — zero deps on tmux/PTB/singletons
- [ ] move pane-text capture, last-activity lookup, screen-buffer parsing, status resolve, vim-insert detection (`_resolve_status`, `_check_vim_insert`, `_get_last_activity_ts`, `_parse_with_pyte`) into `observe.py` — pure inputs in, `TickContext` out
- [ ] move `_apply_*_transition`, `_update_status`, `_send_typing_throttled`, `_handle_dead_window_notification`, `_scan_window_panes`, `_check_interactive_only`, `_maybe_check_passive_shell`, `_surface_pane_alert`, `_forward_pane_output`, `_notify_pane_lifecycle` into `apply.py` — DI-heavy
- [ ] keep `tick_window` in `__init__.py` as thin orchestrator: `ctx = await observe.build_context(...)` → `decision = decide.decide_tick(ctx)` → `await apply.apply(decision, ...)`
- [ ] write isolated unit tests for `decide.decide_tick` covering every transition case (active / done / starting / no-op) — no mocks, just `TickContext` instances
- [ ] write tests for `_build_status_line` and `is_shell_prompt` (pure)
- [ ] run `make check` — must pass before next task
- [ ] run `make test-e2e` — final-of-phase confirmation
- [ ] commit "refactor(polling): split window_tick into decide/observe/apply"

#### Task F4.2: F4 verification

- [ ] verify `decide.py` has zero imports from `tmux_manager`, `telegram.*`, or any singleton
- [ ] verify `observe.py` has zero imports from `telegram.*` (it can use `tmux_manager` and `screen_buffer`)
- [ ] verify `apply.py` is the only file with side effects
- [ ] commit any final cleanup

---

### Phase F2 — Constructor DI for stores + SessionManager

#### Task F2.1: WindowStateStore takes callbacks in `__init__`

**Files:**

- Modify: `src/ccgram/window_state_store.py`
- Modify: `src/ccgram/session.py` (constructs the store)
- Modify: `tests/ccgram/test_window_state_store.py` (build store with stub callbacks)

- [ ] change `WindowStateStore.__init__` signature to accept `schedule_save: Callable[[], None]` and `on_hookless_provider_switch: Callable[[str], None]`
- [ ] remove `unwired_save` import + `__post_init__` defaults from `WindowStateStore`
- [ ] update `SessionManager._wire_singletons` to construct `WindowStateStore(schedule_save=self._save_state, on_hookless_provider_switch=self._clear_session_map_entry)` — store on `self._window_store`
- [ ] keep module-level `window_store` for the singleton bot, but make it lazy: a function `get_window_store()` returns the current SessionManager-owned store, raising if SessionManager not yet built
- [ ] update tests to build a `WindowStateStore` directly with stub callbacks (no global reset)
- [ ] verify `make check` passes; specifically check that all `from .window_state_store import window_store` sites still resolve — most should now use `get_window_store()` or the SessionManager-bound instance
- [ ] commit "refactor(state): WindowStateStore takes callbacks via constructor"

#### Task F2.2: ThreadRouter takes callbacks in `__init__`

**Files:**

- Modify: `src/ccgram/thread_router.py`
- Modify: `src/ccgram/session.py`
- Modify: `tests/ccgram/test_thread_router.py`

- [ ] change `ThreadRouter.__init__` signature: `schedule_save`, `has_window_state` (was monkey-patched lambda)
- [ ] remove `unwired_save` defaults
- [ ] SessionManager constructs `ThreadRouter(schedule_save=self._save_state, has_window_state=self._window_store.has_window)`
- [ ] make module-level `thread_router` lazy via `get_thread_router()` shim (same pattern as F2.1)
- [ ] update tests to build with stub callbacks
- [ ] `make check` passes
- [ ] commit "refactor(state): ThreadRouter takes callbacks via constructor"

#### Task F2.3: UserPreferences takes callback in `__init__`

**Files:**

- Modify: `src/ccgram/user_preferences.py`
- Modify: `src/ccgram/session.py`
- Modify: `tests/ccgram/test_user_preferences.py`

- [ ] change `UserPreferences.__init__` to accept `schedule_save`
- [ ] remove `unwired_save` default
- [ ] SessionManager constructs `UserPreferences(schedule_save=self._save_state)`
- [ ] lazy `get_user_preferences()` for legacy call sites
- [ ] update tests
- [ ] `make check` passes
- [ ] commit "refactor(state): UserPreferences takes callback via constructor"

#### Task F2.4: SessionMapSync takes callback in `__init__`

**Files:**

- Modify: `src/ccgram/session_map.py` (the `SessionMapSync` class)
- Modify: `src/ccgram/session.py`
- Modify: `tests/ccgram/test_session_map.py`

- [ ] change `SessionMapSync.__init__` to accept `schedule_save`
- [ ] remove `unwired_save` default
- [ ] SessionManager constructs and owns it
- [ ] update tests
- [ ] `make check` passes
- [ ] commit "refactor(state): SessionMapSync takes callback via constructor"

#### Task F2.5: Delete `unwired_save` and `_wire_singletons`

**Files:**

- Modify: `src/ccgram/state_persistence.py` (delete `unwired_save`)
- Modify: `src/ccgram/session.py` (delete `_wire_singletons`)

- [ ] confirm no remaining call sites for `unwired_save` (grep)
- [ ] delete the function and its callers
- [ ] delete `SessionManager._wire_singletons` — its body is now empty since stores are constructor-injected
- [ ] simplify `SessionManager.__post_init__` to: `self._persistence = StatePersistence(...); self._construct_stores(); self._load_state()`
- [ ] add a unit test that builds a `SessionManager` with stub state file and verifies all stores are wired (i.e., calling `set_window_provider` triggers a save)
- [ ] `make check` passes
- [ ] commit "refactor(state): remove unwired_save and \_wire_singletons"

#### Task F2.6: Add explicit failure mode for `register_*_callback`

**Files:**

- Modify: `src/ccgram/handlers/status/status_bubble.py` (`register_rc_active_provider`)
- Modify: `src/ccgram/handlers/hook_events.py` (`register_stop_callback`)
- Modify: `src/ccgram/handlers/shell/shell_capture.py` (`register_approval_callback`)
- Modify: `src/ccgram/bot.py` / future bootstrap

- [ ] change each `register_*_callback` to raise `RuntimeError` if called twice (was silently overwriting)
- [ ] change the _callee_ default to raise `RuntimeError("not wired")` if invoked before registration — instead of silent `False` / no-op (this makes a missed wire produce a loud error in dev/test)
- [ ] add unit tests asserting both behaviours
- [ ] `make check` passes
- [ ] commit "refactor(wiring): register\_\*\_callback fails loud on missing/double registration"

#### Task F2.7: F2 verification

- [ ] grep confirms no `_schedule_save = self._save_state` monkey-patching remains
- [ ] grep confirms no `unwired_save` references
- [ ] `make test` passes; specifically verify the singleton-reset fixtures in tests are gone (replaced by per-test SessionManager construction)
- [ ] `make test-integration` passes
- [ ] `make test-e2e` passes (end-of-phase e2e)
- [ ] commit if any final cleanup

---

### Phase F3 — Extract `handlers/registry.py` and `bootstrap.py` from `bot.py`

#### Task F3.1: Create `handlers/registry.py` for command-handler table

**Files:**

- Create: `src/ccgram/handlers/registry.py`
- Modify: `src/ccgram/bot.py` (delegate registration)

- [ ] define a `CommandSpec` dataclass: `(name, handler, filter)` and a `register_all(application, group_filter)` function
- [ ] move the 17 `application.add_handler(CommandHandler(...))` calls plus the `MessageHandler` registrations from `bot.py` into a single `_COMMAND_TABLE: list[CommandSpec]` and message-handler list
- [ ] `bot.py` calls `handlers.registry.register_all(application, _group_filter)`
- [ ] add unit test verifying `register_all` registers exactly N handlers in the expected order (sentinel)
- [ ] `make check` passes
- [ ] commit "refactor(bot): extract handlers/registry.py for command/message handlers"

#### Task F3.2: Create `bootstrap.py` for post_init wiring

**Files:**

- Create: `src/ccgram/bootstrap.py`
- Modify: `src/ccgram/bot.py` (delegate to bootstrap)

- [ ] move `post_init` logic out of `bot.py` into `bootstrap.py` — split into named functions: `register_provider_commands`, `verify_hooks_installed`, `start_session_monitor`, `wire_runtime_callbacks` (the three `register_*_callback` calls), `start_status_polling`, `start_miniapp_if_enabled`
- [ ] `bot.py.post_init(application)` becomes a 5-line delegate calling the named functions in order
- [ ] make ordering explicit: `wire_runtime_callbacks` must run before `start_session_monitor`; raise if order violated (fits with F2.6 "fail loud on not-wired")
- [ ] add unit test that calls `bootstrap.bootstrap_application(stub_app)` against a fake Application and verifies the ordering + that all callbacks were registered
- [ ] `make check` passes
- [ ] commit "refactor(bot): extract bootstrap.py for post_init wiring"

#### Task F3.3: Slim `bot.py` to factory + lifecycle delegates

**Files:**

- Modify: `src/ccgram/bot.py`

- [ ] verify `bot.py` is now <200 lines containing only: imports, `is_user_allowed`, `_group_filter`, `_global_exception_handler`, `post_init/post_stop/post_shutdown` delegates, `_send_shutdown_notification`, `_error_handler`, `create_bot`
- [ ] move the 5 inline command handlers (`new_command`, `history_command`, `commands_command`, `toolbar_command`, `verbose_command`, `toolcalls_command`, `text_handler`, `inline_query_handler`, `unsupported_content_handler`) out: into `handlers/topics/__init__.py` (new_command), `handlers/recovery/history.py` (history_command), `handlers/command_orchestration.py` (commands_command, toolbar_command — already half there), `handlers/text/text_handler.py` (text_handler — wraps existing), `handlers/messaging_pipeline/__init__.py` (verbose_command, toolcalls_command), and a new `handlers/inline.py` (inline_query_handler, unsupported_content_handler)
- [ ] `make check` passes
- [ ] commit "refactor(bot): bot.py is factory + lifecycle only (F3 complete)"

---

### Phase F5 — `TelegramClient` Protocol + adapter, gradual migration

#### Task F5.1: Define `TelegramClient` Protocol and adapter

**Files:**

- Create: `src/ccgram/telegram_client.py`
- Create: `tests/ccgram/test_telegram_client.py`
- Modify: `src/ccgram/bootstrap.py` (build `PTBTelegramClient` and pass to wired components — start with one, not all, to keep this task small)

- [ ] grep all `bot.<method>` calls in `src/ccgram/handlers/**` and `src/ccgram/*.py` to enumerate the actual API surface used
- [ ] define `TelegramClient` Protocol covering exactly that surface (no aspirational methods)
- [ ] implement `PTBTelegramClient(bot: Bot)` adapter that delegates each Protocol method to the underlying PTB Bot
- [ ] implement `FakeTelegramClient` recording every call as a `(method_name, kwargs)` tuple, returning canned `Message`/bool values configured per-test
- [ ] add unit tests: real adapter delegates correctly (mocked PTB Bot); fake records calls
- [ ] DO NOT migrate any handler in this task — Protocol + adapter only
- [ ] `make check` passes
- [ ] commit "feat(telegram): introduce TelegramClient Protocol + PTB adapter"

#### Task F5.2: Migrate `messaging_pipeline/` (queue, sender)

**Files:**

- Modify: `src/ccgram/handlers/messaging_pipeline/message_sender.py` (already most centralized PTB wrapper)
- Modify: `src/ccgram/handlers/messaging_pipeline/message_queue.py`
- Modify: `src/ccgram/handlers/messaging_pipeline/tool_batch.py`
- Modify: tests for these modules

- [ ] migrate `safe_reply`/`safe_edit`/`safe_send`/`rate_limit_send_message`/`edit_with_fallback` to take `client: TelegramClient` instead of `bot: Bot`
- [ ] migrate `_message_queue_worker` to receive a `TelegramClient`
- [ ] migrate `tool_batch` flush helpers similarly
- [ ] update existing tests to inject `FakeTelegramClient` instead of mocking `Bot`
- [ ] `make check` passes
- [ ] commit "refactor(messaging_pipeline): depend on TelegramClient Protocol"

#### Task F5.3: Migrate `status/` (bubble + bar actions + topic_emoji)

**Files:**

- Modify: `src/ccgram/handlers/status/status_bubble.py`
- Modify: `src/ccgram/handlers/status/status_bar_actions.py`
- Modify: `src/ccgram/handlers/status/topic_emoji.py`

- [ ] migrate `process_status_update`, `clear_status_message`, `update_topic_emoji`, `format_topic_name_for_mode` (only places it sends) to depend on `TelegramClient`
- [ ] migrate status-bar-action callback handlers
- [ ] update tests
- [ ] `make check` passes
- [ ] commit "refactor(status): depend on TelegramClient Protocol"

#### Task F5.4: Migrate `recovery/` (banner, restore, resume, history)

**Files:**

- Modify: `src/ccgram/handlers/recovery/recovery_callbacks.py`
- Modify: `src/ccgram/handlers/recovery/restore_command.py`
- Modify: `src/ccgram/handlers/recovery/resume_command.py`
- Modify: `src/ccgram/handlers/recovery/history.py`
- Modify: `src/ccgram/handlers/recovery/transcript_discovery.py`

- [ ] migrate banner rendering and recovery callbacks
- [ ] migrate `/restore`, `/resume`, `/history` commands
- [ ] migrate transcript discovery (sends new-window banner)
- [ ] update tests
- [ ] `make check` passes
- [ ] commit "refactor(recovery): depend on TelegramClient Protocol"

#### Task F5.5: Migrate `interactive/` and `live/`

**Files:**

- Modify: `src/ccgram/handlers/interactive/interactive_ui.py`
- Modify: `src/ccgram/handlers/interactive/interactive_callbacks.py`
- Modify: `src/ccgram/handlers/live/live_view.py`
- Modify: `src/ccgram/handlers/live/screenshot_callbacks.py`
- Modify: `src/ccgram/handlers/live/pane_callbacks.py`

- [ ] migrate interactive UI rendering + callbacks
- [ ] migrate live view tick + screenshot callbacks
- [ ] update tests
- [ ] `make check` passes
- [ ] commit "refactor(interactive,live): depend on TelegramClient Protocol"

#### Task F5.6: Migrate `topics/`, `messaging/`, `shell/`, `voice/`, `send/`, `toolbar/`

**Files:**

- Modify: every remaining handler subpackage

- [ ] migrate `topics/topic_orchestration.py` (forum-topic creation, retry)
- [ ] migrate `topics/topic_lifecycle.py` (autoclose), `topics/window_callbacks.py`
- [ ] migrate `messaging/msg_telegram.py` (already telegram-facing) and `messaging/msg_spawn.py`
- [ ] migrate `shell/shell_commands.py` (approval keyboard), `shell/shell_capture.py` (relay)
- [ ] migrate `voice/voice_handler.py` (download + transcribe + reply), `voice/voice_callbacks.py`
- [ ] migrate `send/send_command.py`, `send/send_callbacks.py`
- [ ] migrate `toolbar/toolbar_keyboard.py` (only uses Bot for one path) and `toolbar/toolbar_callbacks.py`
- [ ] migrate root-level `handlers/file_handler.py`, `handlers/sessions_dashboard.py`, `handlers/sync_command.py`, `handlers/upgrade.py`, `handlers/cleanup.py`, `handlers/command_orchestration.py`, `handlers/hook_events.py`
- [ ] update tests for each
- [ ] `make check` + `make test-integration` pass
- [ ] commit per subpackage to keep diffs reviewable: 6 commits

#### Task F5.7: Verify zero direct PTB imports in handlers (except types)

**Files:**

- Modify: any straggler

- [ ] grep `^from telegram\.ext` and `^from telegram import Bot` inside `src/ccgram/handlers/**` — should be zero or only used as type annotations behind `if TYPE_CHECKING:`
- [ ] handlers may still import `telegram.constants` (ChatAction) and `telegram.error` — those are types/constants, not the Bot client. Keep them.
- [ ] handlers may import `Update`, `CallbackQuery`, `Message`, `InlineKeyboardMarkup`, `MessageEntity` for type annotations — fine. The Protocol returns these types.
- [ ] only `src/ccgram/telegram_client.py`, `src/ccgram/bot.py`, `src/ccgram/bootstrap.py`, `src/ccgram/telegram_request.py`, and `src/ccgram/telegram_sender.py` should import `from telegram.ext` / construct `Bot`
- [ ] `make check` passes; `make test-e2e` passes
- [ ] commit "refactor(telegram): handlers no longer import telegram.ext (F5 complete)"

---

### Phase F6 — Audit residual in-function imports

#### Task F6.1: Inventory remaining in-function imports

**Files:**

- Create: `docs/plans/20260429-modularity-decouple-round-4-import-audit.md` (working notes — moved to completed at end)

- [ ] grep `^[ ]+from \.` inside function bodies under `src/ccgram/` (skipping `if TYPE_CHECKING:` blocks)
- [ ] for each match, classify: (a) circular cycle now resolved by F1/F2 → hoist to top; (b) intentional lazy load (e.g. provider registration) → keep + document with one-line comment; (c) Config-avoidance for CLI commands → check whether F2 made it redundant
- [ ] write the inventory to the working-notes file
- [ ] no code changes in this task — pure audit
- [ ] commit "docs: in-function import audit for round 4"

#### Task F6.2: Hoist resolvable in-function imports

**Files:**

- Modify: every file flagged as category (a) above

- [ ] for each category-(a) site, hoist the import to the top
- [ ] verify `make check` passes after each batch (commit per file or per logical group, ~5 commits)
- [ ] add an integration test that asserts no cycles via `import src.ccgram` from a clean interpreter (catch regressions)
- [ ] `make check` passes
- [ ] commit per logical group; final commit "refactor: hoist resolvable in-function imports (F6 complete)"

#### Task F6.3: Document remaining intentional lazy imports

**Files:**

- Modify: each file with category-(b) lazy import

- [ ] add a one-line comment above each remaining in-function import explaining why it's lazy (e.g., `# Lazy: avoids Config dependency in CLI commands`)
- [ ] verify the count is meaningfully smaller than the audit baseline
- [ ] `make check` passes
- [ ] commit "docs: explain remaining intentional lazy imports"

---

### Task N-1: Verify acceptance criteria

- [ ] no module under `src/ccgram/handlers/` is at top level except the listed exceptions (F1.13)
- [ ] `bot.py` is <200 lines (F3.3)
- [ ] no `unwired_save` references anywhere (F2.5)
- [ ] no `_wire_singletons` method on `SessionManager` (F2.5)
- [ ] no `from telegram.ext import` inside `src/ccgram/handlers/**` (F5.7)
- [ ] `make check` is green
- [ ] `make test-e2e` is green
- [ ] `ccgram doctor` against a clean `~/.ccgram/` reports no errors
- [ ] manual smoke test: start bot in real Telegram group, create a topic, run a Claude session end-to-end, run a shell topic with NL command, run `/sessions`, run `/restore`, restart bot, confirm state recovers — log any regressions as ⚠️
- [ ] verify test coverage at least matches pre-F1 baseline (run `pytest --cov` before F1 and at the end; record numbers)

### Task N: Update documentation and move plan

**Files:**

- Modify: `CLAUDE.md`
- Modify: `docs/architecture.md`
- Modify: `docs/ai-agents/architecture-map.md`
- Modify: `docs/ai-agents/codebase-index.md`
- Move: this plan to `docs/plans/completed/`

- [ ] update `CLAUDE.md` handler table to reflect new subpackage layout (F1)
- [ ] update `CLAUDE.md` to mention `bootstrap.py` and `handlers/registry.py` (F3)
- [ ] update `CLAUDE.md` to document `TelegramClient` Protocol + `PTBTelegramClient` adapter (F5) and the testing pattern using `FakeTelegramClient`
- [ ] update `docs/architecture.md` module layer diagram to show subpackages
- [ ] update `docs/ai-agents/architecture-map.md` and `codebase-index.md` for new paths
- [ ] add a "Round 4 outcomes" subsection in CLAUDE.md (or its CHANGELOG) noting the constructor-DI migration
- [ ] move this plan: `mkdir -p docs/plans/completed && git mv docs/plans/20260429-modularity-decouple-round-4.md docs/plans/completed/`
- [ ] commit "docs: complete round-4 modularity decouple plan"

## Post-Completion

_Items requiring manual intervention or external systems — informational only._

**Manual verification:**

- Run the bot in a real Telegram group for 24 hours and confirm no
  regressions in topic creation, recovery flows, shell command flow,
  voice transcription flow, live view, or messaging.
- Profile bot startup time before/after — F2 constructor wiring and F3
  bootstrap split should be neutral or slightly faster (no functional
  change).
- Record `ccusage` / token cost on a representative AI-agent task
  before F1 and after F6 to quantify the context-budget improvement
  (the actual goal of this round). Add the result to the CLAUDE.md
  Round-4 summary.

**External system updates** (none expected):

- No state-file schema changes — `state.json`, `session_map.json`,
  `events.jsonl`, `monitor_state.json`, mailbox layout all unchanged.
- No CLI argument changes.
- No env-var changes.
- No bot command changes.
- No hook configuration changes.
