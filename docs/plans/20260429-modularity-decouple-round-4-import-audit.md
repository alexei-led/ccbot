# In-function import audit — round 4 (F6.1)

Working notes for Phase F6 of the round-4 modularity decouple plan.
Pure inventory + classification — no code changes in this task.
F6.2 hoists category (a). F6.3 documents category (b).

## Methodology

- Source: `python ast.walk` over every `.py` in `src/ccgram/`, collecting
  `ast.ImportFrom` nodes whose parent is a `FunctionDef` /
  `AsyncFunctionDef` and whose `level > 0` (relative imports only;
  absolute stdlib/3rd-party imports are uninteresting here).
- This excludes `if TYPE_CHECKING:` blocks (those are module-level, not
  inside functions) and module-level `try: import X` blocks.
- Cycle theory verified by reading the top-of-file imports for
  candidates and checking whether the lazy target imports the lazy
  caller.

## Summary

- **Total in-function relative imports: 251** (across ~50 files)
- **Category (a) — circular cycle now resolvable; hoist:** 0 confirmed,
  ~30 likely candidates pending F6.2 verification (the test for whether
  hoisting is safe is "does `make check` still pass after hoisting"; we
  do not pre-prove, we let F6.2 attempt and revert per group).
- **Category (b) — intentional lazy load; keep + document:** ~145
- **Category (c) — Config-avoidance possibly redundant after F2:** 0.
  Round 4 phases F1–F5 did not touch the `config` singleton's
  initialization model; CLI commands still want to avoid loading PTB
  via `bot.create_bot` chain. Inspection confirms zero pure
  config-avoidance imports — every `from ..config import config` site
  is co-located with other lazy imports that have a different reason
  (cycle or CLI-side-effect). No category (c) hits.

The picture is healthier than the original review estimated — the bulk
of remaining in-function imports are intentional CLI lazy-loads or
side-effect-driven callback-registration loads, not residual coupling.

## Category (b) — intentional, keep + document in F6.3

### B1. CLI dispatcher lazy-loads (35 sites — keep)

Click subcommands are wired via tiny dispatchers in `cli.py`. Each
subcommand's heavy module is imported only when the subcommand is
invoked, so `ccgram --help` and `ccgram --version` stay snappy and
don't pull PTB / aiohttp / structlog handlers / etc.

Files & sites:

- `src/ccgram/cli.py:216,234,245,257,272` — `run`, `hook`, `status`,
  `msg`, `doctor` dispatchers.
- `src/ccgram/main.py:126,141,143,161,178,182,210,217,244,255` —
  staged loads inside `run_bot`, `start_miniapp_if_enabled`,
  `stop_miniapp_if_enabled`, `main`. This is the bot bootstrap path
  proper; lazy by design so `ccgram doctor` doesn't pay PTB cost.
- `src/ccgram/status_cmd.py:59,76` — `from .providers import ...`,
  `from . import __version__`. Subcommand body.
- `src/ccgram/doctor_cmd.py:89,273` — hook-module imports inside
  `_check_hooks` / `_fix_hooks`. Subcommand body.
- `src/ccgram/msg_cmd.py:113,124,224,251,411,458,494` — every `msg`
  subcommand body lazy-loads its workers (`msg_discovery`,
  `spawn_request`).
- `src/ccgram/bot.py:95,103` — `_send_shutdown_notification` lazy-loads
  `_shutdown_signal` and `__version__`.
- `src/ccgram/handlers/upgrade.py:41,97` — `upgrade_command` lazy-loads
  `__version__` and `main as main_module`. The `main_module` lazy load
  is load-bearing: `upgrade_command` re-execs itself; we cannot import
  `main` at module top because we are imported by `main → bot →
handlers/upgrade`.
- `src/ccgram/llm/summarizer.py:172` — `from . import get_text_completer`
  inside `summarize_completion`. The `llm/__init__.py` re-exports
  factories that depend on httpx + provider configs; lazy keeps the
  monitor import path light.

### B2. Side-effect-driven callback registration (12 sites — keep)

`src/ccgram/handlers/callback_registry.py:115–132` — the
`load_handlers()` function explicitly imports every callback-bearing
submodule purely for the side effect of executing
`@callback_registry.register(...)` decorators. These imports already
carry `# noqa: F401` and live inside a single function called once
during bootstrap. Hoisting them to module top would (a) defeat the
explicit "wired by `bootstrap.bootstrap_application`" lifecycle
contract (F3.2) and (b) materialise import cycles back to
`callback_registry`. **Keep as-is**, document the contract in F6.3.

### B3. Provider auto-detection lazy-loads (3 sites — keep)

- `src/ccgram/providers/__init__.py:135` — `from .shell import
KNOWN_SHELLS` inside `detect_provider_from_command`. Hoisting would
  load `providers.shell` (and its prompt-marker machinery) on every
  import of `providers`. Keep — provider detection is the only caller.
- `src/ccgram/providers/__init__.py:218` — `from .process_detection
import detect_provider_cached` inside `detect_provider_from_pane`.
  `process_detection` does subprocess fork/exec on import-related
  paths; the module is heavyweight and only relevant when JS-runtime
  wrapping is observed. Keep.
- `src/ccgram/providers/shell_infra.py:231` — `from .process_detection
import get_foreground_args` inside `_is_interactive_shell`. Same
  rationale. Keep.

### B4. Hook subprocess script (2 sites — keep)

`src/ccgram/hook.py:492,600` — `from .utils import ccgram_dir,
atomic_write_json`. The hook module is invoked as a Claude Code
subprocess (`python -m ccgram.hook` style). Keeping these inside the
write-event functions limits import cost on the (frequent, latency-
sensitive) hook fast path. Keep.

### B5. Miniapp factory injection seams (5 sites — keep)

- `src/ccgram/miniapp/api/terminal.py:72,79,88,89` — `_default_capture`,
  `_default_pane_capture`, `_default_pane_list` resolve `tmux_manager`
  / `window_store` lazily because these are the _default factories_
  for dependency-injected callables; tests substitute alternates
  before the route is hit. Keeping the singleton lookup inside the
  default keeps the injection seam clean.
- `src/ccgram/miniapp/api/transcript.py:50` — `_default_reader` same
  pattern.

### B6. Genuine circular dependencies — keep + document (~30 sites)

These are bidirectional cycles where both endpoints would need to
become lazy or be split into a third module to break the cycle.
F6.2 will not attempt to resolve these; F6.3 documents.

- **`session_map.py` ↔ stores**: `session_map.py:81,254,274–275,358,
433,455,550–551` — lazy `from .window_state_store import window_store`
  and `from .thread_router import thread_router`. `session_map.py` is
  imported by `session.py` at top; the stores are imported by
  `session.py` at top; but `session_map.py` modifies the stores
  reactively, which means at _call_ time the stores must already be
  installed via `install_window_store` / `install_thread_router`.
  The lazy imports here are not pure cycle-breakers — they also
  guarantee the stores are wired before access. Keep.
- **`session.py:236`** — `from .window_resolver import LiveWindow,
resolve_stale_ids`. `window_resolver` imports session-state types;
  hoisting forms `session → window_resolver → session.WindowState`
  cycle. Keep.
- **`session.py:601`** — `from .providers.registry import
UnknownProviderError, registry`. `providers.registry` imports
  provider modules; some providers reach back to session state
  indirectly. Keep until verified safe.
- **`session.py:111,351`** — `from .mailbox import Mailbox`.
  `mailbox.py` is a leaf with no internal imports. Likely hoistable.
  Marked **(a) candidate** below.
- **`session_monitor.py:94,286,293,318,341`** — lazy
  `thread_router` / `session_manager` / `session_map_sync`. The cycle
  is `session.py → session_monitor.py` (no, session*monitor is
  bootstrapped, not imported by session at top). On a closer read,
  `session_monitor.py` imports nothing from `session.py` at module
  top but imports `session_manager` \_as a singleton instance* in the
  detector loop. Hoisting `session_manager` import would create
  `session.py → session_monitor.py → session.py` cycle on bootstrap.
  Keep.
- **`tmux_manager.py:1167`** — lazy `thread_router` inside
  `send_to_window`. `thread_router` is a leaf module; tmux_manager is
  imported widely. Probably hoistable; **(a) candidate**.
- **`tmux_manager.py:859`** — lazy `from .providers import (...)`
  inside `_scan_session_windows`. `providers/__init__.py` imports
  tmux pieces indirectly. Keep — genuine cycle.
- **`handlers/topics/topic_orchestration.py:339` ↔
  `handlers/sync_command.py:255–256, 344–345`** — bidirectional cycle:
  `sync_command._adopt_orphaned_windows` lazy-imports
  `topic_orchestration.handle_new_window`, and
  `topic_orchestration.adopt_unbound_windows` lazy-imports
  `sync_command._adopt_orphaned_windows`. Both must stay lazy unless
  one side is split into a third module. Keep, flag for future
  refactor (own ticket — out of scope for round 4).
- **`handlers/messaging/msg_broker.py:270,296,311,330` →
  `msg_telegram`** — `msg_broker` calls `msg_telegram` notify functions;
  `msg_telegram` has no return-side imports of `msg_broker` so
  hoistable; **(a) candidate**.
- **`handlers/messaging/msg_telegram.py:362`** — lazy `from
.msg_delivery import delivery_strategy`. `msg_delivery` is imported
  by `msg_broker`; not imported by `msg_telegram` elsewhere. Likely
  hoistable; **(a) candidate**.
- **`handlers/messaging/msg_spawn.py:142,186,187`** — lazy
  `msg_telegram.resolve_topic` and
  `topics.topic_orchestration.{collect_target_chats,create_topic_in_chat}`.
  `topic_orchestration` participates in the sync_command cycle above;
  keep `msg_spawn` lazy on the topic_orchestration leg. The
  `msg_telegram` leg is **(a) candidate**.
- **`handlers/recovery/transcript_discovery.py:104,185`** — lazy `from
..polling.polling_strategies import is_shell_prompt`. Already
  documented in plan line 751: hoisting forms `polling/__init__ →
window_tick → recovery.transcript_discovery → polling_strategies`
  partial-init cycle (worker-order-dependent). Keep — confirmed cycle.
- **`handlers/recovery/transcript_discovery.py:217,73,83,84`** — lazy
  `from ..shell.shell_prompt_orchestrator import ensure_setup` etc.
  `shell_prompt_orchestrator` imports nothing from recovery; likely
  hoistable; **(a) candidate** — but recovery → polling cycle in same
  file is the binding constraint. Audit: try hoisting only the shell
  imports while leaving polling lazy.

### B7. Cross-subpackage circular avoidance (~95 sites — keep, flagged)

The largest remaining cluster: handler subpackages reaching laterally
through their own ancestry. These are common enough to deserve a
separate sub-list. All are likely cycle-breakers; F6.2 will probe
each in batches.

- `handlers/cleanup.py:52–55,92,100,122–127` — config, thread_router,
  topic_state_registry, window_resolver, mailbox, message_queue,
  message_sender. cleanup is imported by many subpackages; some of
  those subpackages are reachable via `.config` / `..thread_router`
  re-export chains. Likely **(a) candidates** but hoist must be done
  in batches.
- `handlers/command_history.py:84–87` — same shape as cleanup. **(a)
  candidate**.
- `handlers/command_orchestration.py:546–547,566,639,648,737` —
  messaging_pipeline, polling, command_history, toolbar lazy imports.
  command_orchestration is the top-level dispatcher; lazy keeps its
  import light. **(a) candidates** worth probing.
- `handlers/hook_events.py:147,285` — `..llm.summarizer` and
  `messaging_pipeline.message_sender`. summarizer lazy is intentional
  (B1); message_sender lazy is **(a) candidate**.
- `handlers/interactive/interactive_callbacks.py:98` — `..callback_helpers`. Single
  hoist candidate; **(a)**.
- `handlers/interactive/interactive_ui.py:290` —
  `...window_state_store import window_store`. **(a) candidate**.
- `handlers/live/live_view.py:194` — `.screenshot_callbacks`.
  screenshot_callbacks imports live_view at top. Bidirectional cycle
  → keep lazy.
- `handlers/live/screenshot_callbacks.py:129,204,375–377,437–440,521–525,562`
  — mixed: some are siblings (live_view, pane_callbacks), some are
  cleanup-style (config, utils, message_sender). **(a) candidates** for
  the cleanup-style; sibling lazy-loads stay (live_view ↔
  screenshot_callbacks cycle).
- `handlers/messaging_pipeline/message_sender.py:311` — `...config`.
  Trivial; **(a) candidate**.
- `handlers/messaging_pipeline/tool_batch.py:313–314,338,486` —
  claude_task_state, status.status_bubble, sibling message_sender.
  status_bubble may import tool_batch via callback chain; verify in
  F6.2. **(a) candidates** with caveats.
- `handlers/polling/periodic_tasks.py:51–52,70–71,96` — Mailbox,
  msg_broker, spawn_request, msg_spawn. Most likely **(a) candidates**;
  Mailbox is a leaf.
- `handlers/polling/polling_coordinator.py:39–46` — config,
  PTBTelegramClient, periodic_tasks. **(a) candidates**.
- `handlers/polling/polling_strategies.py:182,207,692,732,758,779–780,
810,870–872,1036` — screen_buffer, terminal_parser, window_state_store,
  providers, tmux_manager, window_query. Big cluster. Some are cycle-
  breakers (tmux_manager imports providers; providers may transitively
  reach polling_strategies via window_tick). Hoist in batches; revert
  any batch that fails `make check`.
- `handlers/polling/window_tick/apply.py:107,146–147,202–204,284,386` —
  callback_data, window_state_store, message_sender, config,
  shell.shell_capture, claude_task_state. Mostly **(a) candidates**;
  shell.shell_capture may be cycle-driven (verify).
- `handlers/recovery/recovery_callbacks.py:193,477,742–743` —
  resume_command (sibling), polling_strategies, user_state. Sibling
  may form cycle; verify. **(a) candidates** with caveat.
- `handlers/recovery/resume_command.py:395` — polling_strategies.
  Single site; **(a) candidate**.
- `handlers/send/send_callbacks.py:80` — `...config`. **(a) candidate**.
- `handlers/send/send_security.py:236` — `...utils`. **(a) candidate**.
- `handlers/shell/shell_capture.py:381,390` — llm (lazy by design,
  llm subpackage is heavy), shell_context (sibling). The llm one is
  **(b)**, the shell_context one is **(a) candidate**.
- `handlers/shell/shell_commands.py:140,162,285,334` —
  shell_prompt_orchestrator (sibling), providers.shell, command_history,
  shell_capture (sibling). Sibling cycles need verification; mostly
  **(a) candidates**.
- `handlers/shell/shell_context.py:59` — `...providers.shell`. **(a)
  candidate**.
- `handlers/shell/shell_prompt_orchestrator.py:62,90,124,156` —
  providers.shell_infra, callback_helpers. **(a) candidates**.
- `handlers/status/status_bar_actions.py:109–110,161,170,176,199,265` —
  polling.polling_strategies, status_bubble (sibling), command_history,
  providers, shell.shell_commands, live.live_view. Sibling cycle and
  cross-subpackage cycle risk; verify. Mostly **(a) candidates**.
- `handlers/status/status_bubble.py:114–115,170–171` —
  command_history, status_bar_actions (sibling), callback_data. Sibling
  cycle. The command_history and callback_data sites are **(a)
  candidates**.
- `handlers/status/topic_emoji.py:66,214–215,225,230` — config,
  window_query, thread_router, polling.polling_strategies. **(a)
  candidates**.
- `handlers/text/text_handler.py:355,456` — command_history,
  shell.shell_commands. **(a) candidates**.
- `handlers/toolbar/toolbar_callbacks.py:94–95,129–130,166–167` —
  callback_data, live.screenshot_callbacks, telegram_client, send.
  **(a) candidates**.
- `handlers/topics/directory_callbacks.py:525,583,639,640,653` —
  msg_skill, shell.shell_prompt_orchestrator, telegram_client,
  shell.shell_commands. **(a) candidates**.
- `handlers/topics/topic_lifecycle.py:151,244,292,293` —
  topic_state_registry, callback_helpers, status.topic_emoji.
  **(a) candidates**.
- `handlers/topics/window_callbacks.py:97,108,112,141,146` — providers,
  shell.shell_prompt_orchestrator, shell.shell_commands. providers is
  heavy on import; the shell ones are **(a) candidates**, providers
  may stay (B3 rationale).
- `handlers/voice/voice_callbacks.py:105` — shell.shell_commands.
  **(a) candidate**.
- `handlers/messaging_pipeline/message_sender.py:311` — config.
  **(a) candidate**.
- `monitor_state.py:77` — utils. Trivial. **(a) candidate**.
- `transcript_parser.py:197` — utils. Trivial. **(a) candidate**.
- `transcript_reader.py:45,276` — window_state_store, tmux_manager.
  **(a) candidates**.
- `window_query.py:97` — config. Trivial. **(a) candidate**.
- `session_query.py:22,29,44` — session_resolver. session_query
  intentionally reaches session_resolver lazily for read-only
  resolution (per architecture comment). **(b)** — keep + document.
- `msg_discovery.py:58,80` — utils, config. **(a) candidates**.

## Category (a) — hoist candidates (F6.2)

The list is long enough to warrant batching. Suggested batches for F6.2:

1. **Trivial leaf-module hoists** — single-line `from ..config import
config` / `from ..utils import ...` sites where the target is a
   true leaf:
   - `monitor_state.py:77`
   - `transcript_parser.py:197`
   - `window_query.py:97`
   - `msg_discovery.py:58,80`
   - `handlers/messaging_pipeline/message_sender.py:311`
   - `handlers/send/send_callbacks.py:80`
   - `handlers/send/send_security.py:236`
   - `handlers/status/topic_emoji.py:66`
   - Likely safe as a single batch.

2. **Cleanup / command_history pattern** — `cleanup.py`,
   `command_history.py`, `command_orchestration.py` cluster lazy-loads
   of config, thread_router, topic_state_registry, message_queue,
   message_sender. All are downstream of the handler module itself;
   cycles unlikely after F1's subpackage split.

3. **`polling/` cluster** — `polling_coordinator.py`,
   `periodic_tasks.py`, `polling_strategies.py`, `window_tick/apply.py`.
   This is the biggest cluster but also the most likely to surface a
   cycle on hoisting (per F4.1 split). Suggest hoisting in inner-to-
   outer order: `apply.py` first, `polling_strategies.py` next,
   coordinator/periodic last. Revert any batch that fails `make
check`.

4. **Sibling-pair hoists in handler subpackages** — pairs like
   `status_bubble ↔ status_bar_actions`, `live_view ↔
screenshot_callbacks`, `shell_commands ↔ shell_prompt_orchestrator`.
   These need a one-side-only hoist; if both sides reach the other,
   one must remain lazy. Probe each pair individually.

5. **`tmux_manager.py:1167`** — single line `thread_router` hoist. Try
   alone; if it cycles, leave lazy and document under (b).

6. **`session.py:111,351` Mailbox** — `mailbox.py` is a confirmed leaf;
   should hoist cleanly.

7. **`msg_broker.py → msg_telegram` (4 sites) and `msg_telegram →
msg_delivery` (1 site)** — likely safe; verify with test.

Estimated F6.2 commits: 5–8 logical groups, each preceded by
`make check` to detect cycles.

## Category (c) — Config-avoidance now redundant after F2

**No category (c) sites identified.** F2's constructor DI removed
`unwired_save` and singleton monkey-patching, but did not remove the
`Config` singleton itself, so no in-function `config` import was
purely there to avoid Config initialization. Every `from ..config
import config` site is grouped with other lazy imports for either CLI
startup (B1) or cycle-breaking (B7). All are candidates for category
(a) hoisting if the surrounding cluster proves safe to hoist;
otherwise they stay under (b).

## Notes for F6.3

When documenting category (b) sites, prefer one-line comments
_above_ the import in the function body, e.g.:

```python
def detect_provider_from_pane(...):
    # Lazy: process_detection forks subprocesses on import-relevant
    # paths; load only when JS-runtime wrapping is observed.
    from .process_detection import detect_provider_cached
    ...
```

Do not document the trivial CLI-dispatcher cases individually; instead
add a single note in `cli.py`'s module docstring explaining the
"every subcommand body lazy-loads its workers" pattern. Same for
`callback_registry.py` — one note in `load_handlers`'s docstring.
