# Modularity Review

**Scope**: Entire ccgram codebase — core modules, handlers, providers, LLM, whisper, messaging subsystem  
**Date**: 2026-04-12

## Executive Summary

ccgram is a Telegram bot that bridges agent CLIs (Claude Code, Codex, Gemini, shell) to Telegram Forum topics via tmux, with each topic bound to one tmux window running one agent session. The overall modularity is **healthy with localized concerns**: the provider abstraction, LLM/whisper layers, security pipeline, and cleanup event bus are well-designed boundaries. However, the review identified one **unbalanced** integration — per-window handler state scattered across 30+ module-level singleton dicts — and four cohesion issues that increase cognitive load as new features are added. For a solo developer working in a [volatile core domain](https://coupling.dev/posts/dimensions-of-coupling/volatility/), the primary risk is not tight coupling (which is [balanced](https://coupling.dev/posts/core-concepts/balance/) at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/)) but low cohesion in the handler layer, where related state and behavior are dispersed across many files with no unifying abstraction.

## Coupling Overview

| Integration                                               | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                            | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/)             |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Handlers → SessionManager (39 methods)                    | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                          | Low (same process)                                                      | High (core domain)                                                          | Yes — but god-object cohesion concern                                      |
| screenshot_callbacks (4 concerns, 21 prefixes, 832 lines) | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) + [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (private imports) | Low                                                                     | High                                                                        | Yes — but catch-all cohesion concern                                       |
| polling_coordinator → 12 handler modules                  | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                          | Low                                                                     | Moderate                                                                    | Yes (deliberate design)                                                    |
| providers ↔ session (circular lazy imports)               | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                          | Low                                                                     | High                                                                        | Yes — but fragile architecture                                             |
| **Handler state: 30+ module-level singleton dicts**       | **Low (independent dicts)**                                                                                                                                                                    | **Low**                                                                 | **High**                                                                    | **No — [low cohesion](https://coupling.dev/posts/core-concepts/balance/)** |
| bot.py: composition root with business logic              | Mixed                                                                                                                                                                                          | Low                                                                     | Moderate                                                                    | Yes — but misplaced logic                                                  |
| message_queue → UI builder (build_status_keyboard)        | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                          | Low                                                                     | Moderate                                                                    | Yes — but mixed concerns                                                   |
| sync_command ↔ topic_orchestration (bidirectional)        | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                          | Low                                                                     | Low                                                                         | Yes                                                                        |
| /send → screenshot_callbacks (private function imports)   | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/)                                                                                                           | Low                                                                     | High                                                                        | Yes — but private API dependency                                           |

## Issue: Scattered Per-Window Handler State

**Integration**: 15+ handler modules, each owning independent module-level singleton dicts keyed by window/topic/user  
**Severity**: Significant

### Knowledge Leakage

Each handler that needs per-window state creates its own module-level dictionary: `interactive_ui` owns `_interactive_msgs`, `_interactive_mode`, `_send_cooldowns`; `live_view` owns `_active_views`; `message_queue` owns per-user queues and status tracking; `hook_events` owns `_active_subagents`; `shell_capture` owns `_shell_monitor_state`; `shell_commands` owns `_shell_pending`; `polling_strategies` owns three strategy singletons; `topic_emoji` owns four dicts; `msg_delivery` owns `delivery_strategy`; `msg_telegram` owns `_loop_alert_pairs`; `command_history` owns `_history`; and `message_sender` owns rate-limit tracking.

The knowledge of "what state exists for a given window" is [implicitly](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) distributed across all these modules. There is no single place to answer "what is the complete state of window @5?" — you must grep for `topic_state.register` across the entire handler layer and manually aggregate.

### Complexity Impact

When a new feature is added (like `/send` was), the developer must decide where to put its per-window state — and the answer is always "a new module-level dict in the new handler module." This is [accidental complexity](https://coupling.dev/posts/core-concepts/complexity/): the pattern works, but it fragments the system's state model. A developer modifying window lifecycle (creation, teardown, re-binding) must understand 15+ cleanup registrations across 15+ files to ensure nothing leaks. The `topic_state_registry` event bus mitigates this somewhat — cleanup is self-registered — but discovery of what state exists remains a manual search.

Some singletons are not registered for cleanup at all (`message_sender`'s rate-limit dicts, `cc_commands`'s `_name_map` cache), creating indefinite accumulation in long-running bot instances.

### Cascading Changes

Adding a new per-window concern (e.g., per-window upload history for `/send`) requires: (1) a new module-level dict, (2) a `@topic_state.register` cleanup function, (3) manual verification that the new state is cleared on topic close, window re-bind, and bot restart. Omitting step 2 or 3 produces silent state leaks that only manifest after hours of uptime. Changing the window ID scheme (e.g., supporting multi-server tmux) would require updating every singleton's key format independently.

### Recommended Improvement

Introduce a `WindowContext` dataclass that aggregates per-window ephemeral state into a single, typed structure. Instead of each handler owning `_my_state: dict[str, MyData]`, they access `window_contexts[window_id].my_field`. The `WindowContext` is created when a window is bound, passed to handlers that need it, and destroyed atomically on teardown — eliminating the scattered cleanup registrations for per-window state.

This is a [cohesion](https://coupling.dev/posts/core-concepts/balance/) improvement: it co-locates related data (all per-window state) without increasing [integration strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) — handlers still only access the fields they need. The tradeoff is a larger shared type that must be extended for each new feature, but this is preferable to the current implicit scatter because the type definition documents all per-window state in one place.

This change is substantial. A practical incremental step: start with the highest-churn state (interactive UI, live view, shell monitor) and leave stable singletons (polling strategies, message sender rate limits) where they are. Migrate opportunistically as handlers are modified.

## Issue: screenshot_callbacks.py — Four Concerns in One Module

**Integration**: screenshot_callbacks.py ↔ send_command, interactive_ui, live_view, polling_strategies, message_queue, history, command_history, shell_capture (8 handler dependencies)  
**Severity**: Significant

### Knowledge Leakage

`screenshot_callbacks.py` (832 lines, 21 callback prefixes) handles four distinct concerns: (1) screenshot capture and refresh, (2) toolbar buttons for all four providers (13 actions), (3) status bar button actions, and (4) pane-level operations. It imports `send_command._cache_browser_state` and `send_command.build_file_browser` — accessing a private function across handler boundaries — to implement the toolbar "Send" button. It also imports from `polling_strategies`, `interactive_ui`, `command_history`, `shell_capture`, `message_queue`, and `history`.

This module has [intrusive knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of the `/send` feature's internal state management (`_cache_browser_state` caches 5 `user_data` keys), and [functional knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of how every provider's toolbar buttons map to tmux key sequences.

### Complexity Impact

Every new feature that needs a toolbar button must be implemented here. The `/send` feature required adding `_handle_toolbar_send` (which imports from `send_command`) alongside completely unrelated handlers like `_handle_toolbar_ctrlc` and `_handle_pane_screenshot`. A developer working on toolbar behavior must load the entire 832-line file into working memory even when their change affects only one provider's buttons. This exceeds the [cognitive capacity](https://coupling.dev/posts/core-concepts/complexity/) threshold — the file contains 18 handler functions with no internal sectioning.

### Cascading Changes

Adding a new provider (e.g., Aider) with custom toolbar buttons requires modifying `build_toolbar_keyboard()`, adding new `CB_TOOLBAR_*` constants in `callback_data.py`, adding new handler functions in `screenshot_callbacks.py`, and registering them. All of this happens in a single file that also handles unrelated screenshot and status-bar concerns. A bug in the new toolbar handler could affect screenshot refresh behavior because they share the same module scope and the same `@register` dispatch.

### Recommended Improvement

Extract toolbar handling into a dedicated `toolbar_callbacks.py` module. Move `build_toolbar_keyboard()`, all `_handle_toolbar_*` functions, and `_send_toolbar_key()` into it. The toolbar module would own the provider→button mapping and the tmux key-send logic, while `screenshot_callbacks.py` shrinks to its natural scope: screenshot capture, refresh, and live view.

The `/send` toolbar integration should be inverted: instead of `screenshot_callbacks` importing `send_command._cache_browser_state`, the `send_command` module should expose a public `open_browser(update, context, window_id, cwd)` function that `toolbar_callbacks` calls. This converts [intrusive coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (private import) to [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) (public interface).

The tradeoff is one more handler file and one more `@register` import in `callback_registry.load_handlers()`. This is negligible — the system already has 35+ handler modules.

## Issue: SessionManager God Object

**Integration**: 39 public methods consumed by virtually every handler and core module  
**Severity**: Minor

### Knowledge Leakage

`SessionManager` (1076 lines, 39 public methods) is a facade that mixes four levels of concern: (1) state CRUD — `get_window_state`, `set_window_provider`, `get_display_name`; (2) mode settings — `get_approval_mode`, `cycle_notification_mode`, `set_batch_mode`; (3) persistence and sync — `resolve_stale_ids`, `load_session_map`, `flush_state`, `prune_*`; and (4) session resolution — `resolve_session_for_window`, `get_recent_messages`. Callers import `session_manager` for any of these purposes and receive access to all of them.

Additionally, `session_resolver.py` accesses `window_store._schedule_save()` directly (a private attribute), and `session_map.py` mutates `thread_router.window_display_names` (bypassing the public `set_display_name()` method). These are boundary violations where modules reach past the facade into its wired sub-objects.

### Complexity Impact

The wide surface area means `session_manager` is imported by nearly every module in the codebase. Any change to its interface (renaming a method, changing a return type) has broad ripple effects. However, for a solo developer at low [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/), these ripples are manageable with IDE refactoring tools. The cognitive cost is moderate: a developer must remember which of the 39 methods to call, but the method names are descriptive and grouped by prefix (`get_*`, `set_*`, `prune_*`).

### Cascading Changes

Adding a new per-window setting requires: adding the setting to `WindowState`, adding getter/setter methods to `SessionManager`, updating `state_persistence` serialization, and wiring any UI toggle. This is a 4-file change for what is conceptually a single concern. However, the current rate of new settings is low, making this tolerable.

### Recommended Improvement

The immediate fixes are the two boundary violations:

1. Replace `session_resolver.py`'s direct `window_store._schedule_save()` calls with a public `window_store.update_cwd(window_id, cwd)` method.
2. Replace `session_map.py`'s direct `thread_router.window_display_names[wid] = name` mutation with `thread_router.set_display_name(wid, name)`.

The broader decomposition (splitting SessionManager into separate state-access and lifecycle-management interfaces) is not recommended at this time. The [volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) of the facade's surface is moderate (new methods are additive, not breaking), and the [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) is low. The cost of refactoring a 39-method class into smaller interfaces would not pay for itself until either team size increases or the method count exceeds ~50.

## Issue: Circular Dependency — Providers ↔ Session

**Integration**: `providers/__init__.py` → `session.session_manager` → `session_resolver` → `providers/__init__.py`  
**Severity**: Minor

### Knowledge Leakage

`get_provider_for_window(window_id)` in `providers/__init__.py` needs to know the window's `provider_name`, which lives in `WindowState` managed by `session_manager`. Meanwhile, `session_resolver` needs to call `get_provider_for_window()` to get the correct transcript parser. This creates a cycle where the provider layer has [functional knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of session management and vice versa.

The cycle is broken by lazy imports — `from ccgram.session import session_manager` appears inside the function body of `get_provider_for_window()`, not at module level. This is stable at runtime but invisible to static analysis tools and fragile to refactoring.

### Complexity Impact

The lazy import pattern means the dependency is invisible at the module level. A developer reading `providers/__init__.py` sees no import from `session` and may not realize the coupling exists. Moving the lazy import to module level (a natural refactoring) would crash the application at startup with a circular import error. This is a [complexity](https://coupling.dev/posts/core-concepts/complexity/) trap — the system works, but the reason it works is non-obvious.

### Cascading Changes

Adding a new provider does not trigger this cycle (providers register via `registry.py` which has no session dependency). The cycle only matters when changing how provider resolution works — e.g., adding multi-session-per-window support or changing the window state schema. These changes are infrequent.

### Recommended Improvement

Pass `provider_name: str` as a parameter to `get_provider_for_window()` instead of having it look up the name from `session_manager`. Callers already have access to `window_id` and can trivially obtain `provider_name` from `window_store.get_window_state(window_id).provider_name`. This breaks the cycle by making the provider layer a pure lookup (name → instance) with no knowledge of session management.

The tradeoff: callers must pass one additional argument. This is a minor inconvenience that eliminates a fragile architectural cycle. The ~20 call sites can be updated mechanically.

## Issue: Business Logic in Composition Root (bot.py)

**Integration**: `bot.py` (1089 lines) ↔ 24 handler modules + core modules  
**Severity**: Minor

### Knowledge Leakage

`bot.py` serves as the composition root (`create_bot()` wires all handlers), but it also contains substantive business logic: `handle_new_message` (122 lines of notification filtering, thinking-block gating, interactive-tool detection, offset tracking, and queue management), `screenshot_command` (tmux capture + image rendering + Telegram upload), `toolbar_command`, `recall_command`, `panes_command`, and topic lifecycle handlers (`topic_closed_handler`, `topic_edited_handler`). These functions have [functional knowledge](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of message processing, terminal rendering, and topic lifecycle — concerns that belong in the handler layer.

### Complexity Impact

A developer looking for "where is the screenshot command implemented?" must check both `screenshot_callbacks.py` and `bot.py`. The composition root's dual role as wiring hub and business logic container means any change to message handling requires reading a 1089-line file that is mostly unrelated handler registration. The notification-mode filtering in `handle_new_message` is particularly subtle — it gates which inbound messages reach the user based on per-window settings — and its placement in `bot.py` makes it easy to overlook.

### Cascading Changes

Adding a new command handler requires modifying `bot.py` to register it (expected for a composition root). But if the new command is similar to existing ones defined inline in `bot.py` (screenshot, toolbar, panes), the developer faces a style choice: define it inline here, or in a dedicated handler module. The inconsistency creates drift toward an ever-larger `bot.py`.

### Recommended Improvement

Extract the business logic functions into their existing handler modules: move `screenshot_command` into `screenshot_callbacks.py`, `handle_new_message` into a new `message_routing.py` or into `text_handler.py` (which already handles text routing), and topic lifecycle handlers into `topic_lifecycle.py`. Leave `bot.py` as a pure composition root: `create_bot()` builds the application, registers handlers, and returns.

The tradeoff is splitting what is currently a single "entry point" file into composition-only wiring plus distributed logic. For a solo developer this is low priority — the current structure works — but it prevents `bot.py` from growing further as new commands are added.

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
