# Enhance Telegram UX — Reduce Noise, Delays, and Flood

## Overview

Improve the Telegram message delivery experience across four axes:

1. **Noise reduction** — fewer messages, smarter batching, skip trivial content
2. **Faster delivery** — lower poll intervals and rate limits
3. **Better formatting** — truncate oversized quotes, fix Stop flicker
4. **Flood prevention** — debounce subagent status, screenshot keys, ghost window cleanup

These changes target the message pipeline from transcript detection through Telegram delivery.
The goal is a cleaner, faster, more professional Telegram experience without losing important information.

## Context (from analysis)

**Active pipeline path**: transcript JSONL (2s poll) -> TranscriptParser -> handle_new_message -> response_builder -> message_queue worker (merge/batch/coalesce) -> message_sender (1.1s rate limit) -> Telegram API

**Key files involved**:

- `src/ccgram/config.py` — tunable intervals and defaults
- `src/ccgram/session_monitor.py` — transcript poll interval
- `src/ccgram/bot.py` — handle_new_message, notification filtering, thinking filter
- `src/ccgram/transcript_parser.py` — tool formatting, expandable quotes
- `src/ccgram/handlers/message_queue.py` — merge/batch/coalesce, batch default
- `src/ccgram/handlers/message_sender.py` — MESSAGE_SEND_INTERVAL, rate limiting
- `src/ccgram/handlers/hook_events.py` — SubagentStart/Stop, Stop/Ready flow
- `src/ccgram/handlers/polling_coordinator.py` — STATUS_POLL_INTERVAL
- `src/ccgram/handlers/polling_strategies.py` — subagent debounce state
- `src/ccgram/handlers/screenshot_callbacks.py` — key press debounce
- `src/ccgram/window_state_store.py` — default batch mode
- `src/ccgram/entity_formatting.py` — expandable quote truncation

**Insights from six-ddc/ccbot fork**:

- PR #57 added `SHOW_TOOL_CALLS` / `SHOW_USER_MESSAGES` env vars (simple noise toggles)
- Issue #66: "Message is not modified" causes duplicate messages (catch BadRequest specifically)
- We already handle most of their other fixes (telegramify-markdown, hook timeouts, provider abstraction)

## Development Approach

- **Testing approach**: Regular (implement first, then update tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run `make check` after each task
- Maintain backward compatibility (env var toggles, /verbose still works)

## Testing Strategy

- **Unit tests**: required for every task
- Focus on threshold/config changes and filtering logic
- Existing tests must not break

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope

## Solution Overview

**Batch mode as default**: Change default from "normal" to "batched" — single biggest noise reduction. 10 tool calls become 1 live-updating message instead of 20+ separate messages. /verbose toggles back.

**Thinking filter**: Skip trivial "(thinking)" messages that carry no actual reasoning content.

**Faster intervals**: MONITOR_POLL_INTERVAL 2.0s -> 1.0s, MESSAGE_SEND_INTERVAL 1.1s -> 0.5s. PTB's AIORateLimiter is the real flood safety net.

**SubagentStart/Stop debounce**: Only show subagent status if count changes persist >2s. Short-lived subagents become invisible.

**Stop flicker fix**: Wait up to 3s for LLM summary before sending Ready. No more flicker.

**Expandable quote truncation**: Cap at 3500 chars to prevent exceeding Telegram's 4096 limit.

**Screenshot key debounce**: Coalesce rapid taps — only render final state.

## Implementation Steps

### Task 1: Default to batched tool mode

**Files:**

- Modify: `src/ccgram/window_state_store.py`

- [x] Change default `batch_mode` from `"normal"` to `"batched"` in WindowState dataclass — ALREADY DONE (`DEFAULT_BATCH_MODE = "batched"` in window_state_store.py)
- [x] Verify /verbose toggle still switches to individual mode and back — tests confirm cycle works
- [x] Update tests for new default value — tests already assert `"batched"` as default
- [x] Run tests — existing tests pass

### Task 2: Skip trivial thinking messages

**Files:**

- Modify: `src/ccgram/bot.py`

- [x] In `handle_new_message`, add filter: skip messages where `content_type == "thinking"` and `len(text.strip()) < _MIN_THINKING_LENGTH` (20 chars)
- [x] Keep thinking messages that contain actual reasoning content (>= 20 chars)
- [x] Write test for thinking filter logic — `tests/ccgram/test_thinking_filter.py` (10 parametrized cases)
- [x] Run tests — 3073 passed

### Task 3: Reduce poll and send intervals

**Files:**

- Modify: `src/ccgram/config.py`
- Modify: `src/ccgram/handlers/message_sender.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`

- [x] `config.py`: Change `monitor_poll_interval` default from `2.0` to `1.0`, add min guard `max(0.5, ...)`
- [x] `message_sender.py`: Change `MESSAGE_SEND_INTERVAL` from `1.1` to `0.5`
- [x] `polling_coordinator.py`: Make `STATUS_POLL_INTERVAL` read from config at startup
- [x] `config.py`: Add `status_poll_interval` with env var `CCGRAM_STATUS_POLL_INTERVAL` (default 1.0, min 0.5)
- [x] Added 6 tests for new defaults and min guards in TestPollingConfig
- [x] Run tests — 3079 passed

### Task 4: Debounce SubagentStart/Stop status updates

**Files:**

- Modify: `src/ccgram/handlers/hook_events.py`

- [x] Removed `enqueue_status_update` calls from both `_handle_subagent_start` and `_handle_subagent_stop`
- [x] Subagent count/names already shown by polling loop (1s) via `get_subagent_names()` — no debounce state needed
- [x] Simpler approach than planned: just remove the noise source entirely, polling loop already handles display
- [x] Updated 6 tests to verify tracking without asserting status notifications
- [x] Run tests — 3079 passed

### Task 5: Fix Stop flicker — wait for LLM summary

**Files:**

- Modify: `src/ccgram/handlers/hook_events.py`

- [x] Refactored `_handle_stop`: await `_get_llm_summary` with `asyncio.wait_for(timeout=3.0s)` before sending status
- [x] On success: single "Done — {summary}" message (no flicker)
- [x] On timeout/error: fall back to plain enriched Ready
- [x] Replaced fire-and-forget `asyncio.create_task(_enhance_with_llm_summary)` with synchronous wait
- [x] Updated test: verify single status call with summary instead of 2-call flicker pattern
- [x] Run tests — 3079 passed

### Task 6: Truncate expandable quotes at 3500 chars

**Files:**

- Modify: `src/ccgram/transcript_parser.py` or `src/ccgram/entity_formatting.py`

- [x] Added `_EXPANDABLE_QUOTE_MAX_CHARS = 3500` to `providers/base.py`
- [x] `format_expandable_quote` truncates with `\u2026 (truncated, {total} chars total)` indicator
- [x] Added 3 tests in `TestExpandableQuoteTruncation`: short pass-through, long truncated, exact limit
- [x] Run tests — passed

### Task 7: Debounce screenshot key presses

**Files:**

- Modify: `src/ccgram/handlers/screenshot_callbacks.py`

- [x] Extracted `_schedule_key_refresh` with `_KEY_REFRESH_DELAY = 0.3s` and `_pending_key_refreshes` dict
- [x] On each key tap: cancel pending refresh task, schedule new one with 0.3s delay
- [x] Updated existing test to work with async debounce (set delay to 0, await task completion)
- [x] Run tests — 3082 passed

### Task 8: Clean up ghost window queue entries

**Files:**

- Modify: `src/ccgram/handlers/message_queue.py`

- [x] Added `_is_ghost_window_task_at_enqueue(window_id)` helper using `thread_router.has_window()`
- [x] Filter at enqueue time in `enqueue_content_message` — ghost tasks never enter the queue
- [x] This prevents the @273-style noise where deleted windows still have queue tasks draining
- [x] Run tests — 3082 passed, lint + typecheck clean

### Task 9: Verify acceptance criteria

- [x] Verify batch mode is default for new windows — `DEFAULT_BATCH_MODE = "batched"` ✓
- [x] Verify /verbose toggles back to individual mode — `cycle_batch_mode` tests ✓
- [x] Verify trivial thinking messages are filtered — `_MIN_THINKING_LENGTH = 20` ✓
- [x] Verify MONITOR_POLL_INTERVAL defaults to 1.0s with min guard 0.5 ✓
- [x] Verify MESSAGE_SEND_INTERVAL is 0.5s ✓
- [x] Verify STATUS_POLL_INTERVAL is configurable via CCGRAM_STATUS_POLL_INTERVAL ✓
- [x] Verify subagent status is debounced — removed direct status updates ✓
- [x] Verify Stop doesn't flicker when LLM is configured — wait_for(3s) ✓
- [x] Verify long expandable quotes are truncated at 3500 chars ✓
- [x] Verify screenshot keys are debounced with 0.3s cancel-on-tap ✓
- [x] Verify ghost window queue entries are skipped at enqueue time ✓
- [x] Run full test suite: 3082 passed, lint clean, typecheck 0 errors ✓

### Task 10: [Final] Update documentation

- [x] Updated CLAUDE.md: rate limit 1.1s->0.5s, LLM summary wait-for, new config env vars
- [x] No architecture.md changes needed — no new modules
- [x] Move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification**:

- Run ccgram locally with multiple active agent windows
- Verify batch messages update live in Telegram
- Verify subagent-heavy sessions (5+ subagents) show minimal status churn
- Verify Stop -> Ready transition is clean (no flicker)
- Verify long tool results (Grep with many matches) don't exceed 4096 chars
- Verify rapid screenshot key taps result in single render

**ccbot fork insights not included in this plan** (potential future work):

- `SHOW_TOOL_CALLS` / `SHOW_USER_MESSAGES` simple env var toggles (PR #57 pattern)
- "Message not modified" BadRequest handling (issue #66 — check if we already handle this)
- TTS voice reply feature (issue #59)
