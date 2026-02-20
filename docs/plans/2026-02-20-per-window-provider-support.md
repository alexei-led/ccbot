# Per-Window Provider Support

## Overview

Make the provider (claude/codex/gemini) a per-window attribute instead of a global singleton. When creating a new topic, default to claude but allow choosing codex or gemini. When a tmux window is created externally, auto-detect the provider from the running process name (pane_current_command).

## Context

- Files involved: `src/ccbot/providers/__init__.py`, `src/ccbot/session.py`, `src/ccbot/session_monitor.py`, `src/ccbot/tmux_manager.py`, `src/ccbot/config.py`, `src/ccbot/handlers/directory_browser.py`, `src/ccbot/handlers/directory_callbacks.py`, `src/ccbot/handlers/status_polling.py`, `src/ccbot/handlers/recovery_callbacks.py`, `src/ccbot/handlers/resume_command.py`, `src/ccbot/handlers/message_queue.py`, `src/ccbot/handlers/interactive_ui.py`, `src/ccbot/handlers/text_handler.py`, `src/ccbot/bot.py`, `src/ccbot/hook.py`
- Related patterns: Provider registry already maps names to classes; WindowState already has per-window state; pane_current_command already detected
- Dependencies: None new

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Add provider_name to WindowState and introduce get_provider_for_window()

**Files:**

- Modify: `src/ccbot/session.py` (add `provider_name` field to WindowState)
- Modify: `src/ccbot/providers/__init__.py` (add `get_provider_for_window(window_id)` that looks up provider_name from WindowState, falling back to config default)
- Modify: `src/ccbot/providers/registry.py` (add provider name validation helper)

- [x] Add `provider_name: str = ""` to `WindowState` dataclass (empty = use default from config)
- [x] Add serialization/deserialization in `to_dict()`/`from_dict()`
- [x] Add `get_provider_for_window(window_id: str) -> AgentProvider` in `providers/__init__.py` that resolves provider from window state, falling back to `config.provider_name`
- [x] Add `set_window_provider(window_id: str, provider_name: str)` on SessionManager
- [x] Write tests for WindowState serialization with provider_name
- [x] Write tests for get_provider_for_window resolution logic
- [x] Run `make check` - must pass

### Task 2: Replace global get_provider() calls with per-window resolution

**Files:**

- Modify: `src/ccbot/session_monitor.py` (pass provider per session/window)
- Modify: `src/ccbot/session.py` (`_get_session_direct`, `get_recent_messages`)
- Modify: `src/ccbot/handlers/status_polling.py`
- Modify: `src/ccbot/handlers/message_queue.py`
- Modify: `src/ccbot/handlers/interactive_ui.py`
- Modify: `src/ccbot/handlers/text_handler.py`
- Modify: `src/ccbot/bot.py`

- [x] In `session_monitor._read_new_lines` and `_process_session_file`: look up the window_id for the session being processed, resolve provider from window state
- [x] In `session.py._get_session_direct` and `get_recent_messages`: accept optional `provider_name` parameter, resolve provider accordingly
- [x] In `status_polling.py`: resolve provider per window being polled (window_id is already available in the loop)
- [x] In `message_queue.py`, `interactive_ui.py`, `text_handler.py`, `bot.py`: resolve provider from window_id context where available
- [x] Keep `get_provider()` as fallback for contexts without a window (e.g., CLI commands like doctor/status)
- [x] Write tests verifying different windows can use different providers
- [x] Run `make check` - must pass

### Task 3: Add provider selection to directory browser UI

**Files:**

- Modify: `src/ccbot/handlers/directory_browser.py` (add provider step after directory confirmation)
- Modify: `src/ccbot/handlers/directory_callbacks.py` (handle provider selection callback, store in state)
- Modify: `src/ccbot/handlers/callback_data.py` (new callback constants)
- Modify: `src/ccbot/tmux_manager.py` (accept launch_command override in create_window)

- [x] Add callback constants: `CB_PROV_SELECT = "prov:"` and individual provider buttons
- [x] After directory confirmation, show provider selection inline keyboard (Claude (default), Codex, Gemini) - single tap, Claude pre-selected
- [x] If user picks default (Claude), proceed as today. Otherwise store chosen provider in user_data
- [x] Modify `tmux_manager.create_window()` to accept optional `launch_command` parameter instead of always using `config.claude_command`
- [x] After window creation, call `set_window_provider(window_id, provider_name)` to persist the choice
- [x] Write tests for provider selection UI and callback handling
- [x] Run `make check` - must pass

### Task 4: Auto-detect provider for externally created windows

**Files:**

- Modify: `src/ccbot/session_monitor.py` (detect provider in new window callback)
- Modify: `src/ccbot/providers/__init__.py` (add `detect_provider_from_command(command: str) -> str` utility)
- Modify: `src/ccbot/bot.py` (`_handle_new_window` - set detected provider)
- Modify: `src/ccbot/hook.py` (optionally write provider_name to session_map)

- [x] Add `detect_provider_from_command(pane_current_command: str) -> str` that maps "claude" -> "claude", "codex" -> "codex", "gemini" -> "gemini", unknown -> config default
- [x] In `_handle_new_window` (bot.py): detect provider from window's pane_current_command (already in TmuxWindow), set it on the WindowState
- [x] When session_map is loaded and a new window appears, detect provider if not already set
- [x] In hook.py: optionally detect provider from the process tree or pane command and write it to session_map (only for Claude hook since other providers don't have hooks)
- [x] Write tests for detect_provider_from_command with various inputs
- [x] Write tests for auto-detection during new window handling
- [x] Run `make check` - must pass

### Task 5: Update recovery, resume, and provider-gated UX

**Files:**

- Modify: `src/ccbot/handlers/recovery_callbacks.py` (use per-window provider for resume/continue)
- Modify: `src/ccbot/handlers/resume_command.py` (use per-window provider)
- Modify: `src/ccbot/handlers/sessions_dashboard.py` (show provider per session)

- [x] In recovery callbacks: resolve provider from window state for capability checks (supports_resume, supports_continue) and launch command
- [x] In resume command: use per-window provider for resume args
- [x] In sessions dashboard: display provider name alongside each session
- [x] Write tests for recovery with different providers per window
- [x] Run `make check` - must pass

### Task 6: Verify acceptance criteria

- [ ] Manual test: create two topics - one with Claude, one with Codex - verify independent operation
- [ ] Manual test: create a tmux window externally running codex, verify auto-detection and topic creation
- [ ] Run `make check` (fmt + lint + typecheck + test)
- [ ] Verify test coverage meets 80%+

### Task 7: Update documentation

- [ ] Update CLAUDE.md provider configuration section to document per-window provider
- [ ] Update `.claude/rules/architecture.md` to reflect per-window provider model
- [ ] Move this plan to `docs/plans/completed/`
