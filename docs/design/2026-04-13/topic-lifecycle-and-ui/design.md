# Topic Lifecycle and Interactive UI

## Functional Responsibilities

Three related concerns wrapped together because they all mutate the same "topic lifecycle" space:

1. **Topic creation / teardown** — new-window orchestration, unbound-window adoption, topic close handling.
2. **Lifecycle timers** — autoclose for done topics, TTL for dead sessions, unbound TTL for orphaned windows.
3. **Interactive UI** — inline keyboards for AskUserQuestion, ExitPlanMode, Permission prompts; arrow-key / enter / esc callbacks.
4. **Cleanup event bus** — `topic_state_registry` with its four scopes (`window`, `topic`, `qualified`, `chat`).
5. **Topic name/emoji updates** — active/idle/done/dead badges with debounce.

Files:

- **`handlers/topic_orchestration.py`** — `orchestrate_new_topic`, topic creation rate limiting, unbound-window adoption, `check_hooks_installed`.
- **`handlers/topic_lifecycle.py`** — autoclose timers for done/dead topics, unbound window TTL, topic-closed / topic-edited handlers.
- **`handlers/topic_state_registry.py`** — `TopicStateRegistry` (self-registering cleanup callbacks), scopes, `fire` / `register` / `register_bound` (after refactor) API.
- **`handlers/topic_emoji.py`** — debounced topic emoji updates (active/idle/done/dead + RC/YOLO badges).
- **`handlers/cleanup.py`** — topic teardown orchestration via `TopicStateRegistry` + async bot cleanup.
- **`handlers/interactive_ui.py`** — AskUserQuestion / ExitPlanMode / Permission UI rendering, `_interactive_msgs`, `_interactive_mode`, `_send_cooldowns`.
- **`handlers/interactive_callbacks.py`** — arrow-key / enter / esc callback dispatch.
- **`handlers/sync_command.py`** — `/sync` command that reconciles window state with tmux.

## Encapsulated Knowledge

- **Registry scope semantics** — only `topic_state_registry.py` knows how to route a `fire("window", @5)` to every `@register("window")` callback, and how `qualified` differs from `window` (the qualified scope fires on `session:@N` IDs for foreign emdash windows).
- **Debounce timing for emoji updates** — `topic_emoji.py` owns the `_DEBOUNCE_BY_STATE` dict and the debounce logic.
- **Lifecycle timer management** — `topic_lifecycle.py` owns autoclose TTLs, unbound window timeouts, and the reset-on-activity logic.
- **Interactive UI message lifecycle** — `interactive_ui.py` owns `_interactive_msgs` (per-topic Telegram message IDs for active interactive prompts) and the mode state machine (navigating vs. confirming vs. cancelling).

## Subdomain Classification

**Core.** Topic lifecycle and interactive UI are where the user-facing experience lives. High volatility.

## Integration Contracts

### Inbound

| From                                                                                                | Kind     |
| --------------------------------------------------------------------------------------------------- | -------- |
| `text_handler` (unbound topic flow) → `topic_orchestration.handle_unbound_message(...)`             | Contract |
| PTB topic-closed filter → `topic_lifecycle.topic_closed_handler(...)`                               | Contract |
| PTB topic-edited filter → `topic_lifecycle.topic_edited_handler(...)`                               | Contract |
| `polling_coordinator` → `topic_lifecycle.check_autoclose_timers(...)`, `topic_emoji.set_state(...)` | Contract |
| `hook_events.handle_notification` → `interactive_ui.show_interactive_alert(...)`                    | Contract |
| `polling_coordinator._check_interactive_only` → `interactive_ui.show_interactive_alert(...)`        | Contract |
| All handlers → `topic_state.register(scope)` decorator at module load                               | Contract |
| Topic teardown → `topic_state.fire(scope, id)`                                                      | Contract |

### Outbound

- `session_manager.view_window` / `get_window_state` / `prune_stale_*`
- `tmux_manager.create_window` / `kill_window`
- `message_sender.safe_send` / `safe_edit`
- `thread_router.set_display_name` / `resolve_chat_id`

## Change Vectors

- **New lifecycle state** (e.g., "paused") — add to `topic_emoji._DEBOUNCE_BY_STATE`, add a timer in `topic_lifecycle`, add a badge in topic name.
- **New interactive UI pattern** — add to `interactive_ui.py` a new keyboard + callback registration.
- **New cleanup scope** — extend `topic_state_registry.py` scope enum.
- **Topic creation rate limit change** — `topic_orchestration._topic_create_retry_until` dict + constant.

## Testability Goals

- **Unit-test `TopicStateRegistry`** with fake callbacks — verify scoped fire-and-forget.
- **Unit-test `topic_emoji` debounce** with a fake clock — verify state transitions respect the debounce window.
- **Unit-test `topic_lifecycle` autoclose timer** with synthetic state and a fake now.
- **Unit-test `interactive_ui.build_keyboard`** — pure function per interactive-UI type.
- **Integration-test `topic_closed_handler`** — dispatches cleanup for the affected topic.
- **Unit-test `register_bound` support** (new capability) — register an instance method, fire the scope, verify the method is called with the correct self.
