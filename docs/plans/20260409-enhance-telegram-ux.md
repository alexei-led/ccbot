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

- [ ] Change default `batch_mode` from `"normal"` to `"batched"` in WindowState dataclass
- [ ] Verify /verbose toggle still switches to individual mode and back
- [ ] Update tests for new default value
- [ ] Run tests — must pass before next task

### Task 2: Skip trivial thinking messages

**Files:**

- Modify: `src/ccgram/bot.py`

- [ ] In `handle_new_message`, add filter: skip messages where `content_type == "thinking"` and `text` is `"(thinking)"` or `len(text.strip()) < 20`
- [ ] Keep thinking messages that contain actual reasoning content (>= 20 chars)
- [ ] Write test for thinking filter logic (trivial skipped, substantial passed through)
- [ ] Run tests — must pass before next task

### Task 3: Reduce poll and send intervals

**Files:**

- Modify: `src/ccgram/config.py`
- Modify: `src/ccgram/handlers/message_sender.py`
- Modify: `src/ccgram/handlers/polling_coordinator.py`

- [ ] `config.py`: Change `monitor_poll_interval` default from `2.0` to `1.0`, add min guard `max(0.5, float(...))`
- [ ] `message_sender.py`: Change `MESSAGE_SEND_INTERVAL` from `1.1` to `0.5`
- [ ] `polling_coordinator.py`: Make `STATUS_POLL_INTERVAL` read from config as `status_poll_interval` (default `1.0`, min `0.5`)
- [ ] `config.py`: Add `status_poll_interval` with env var `CCGRAM_STATUS_POLL_INTERVAL`
- [ ] Update tests for new defaults and min guards
- [ ] Run tests — must pass before next task

### Task 4: Debounce SubagentStart/Stop status updates

**Files:**

- Modify: `src/ccgram/handlers/hook_events.py`

- [ ] Add `_subagent_debounce: dict[str, tuple[int, float]]` tracking `{window_id: (count, last_change_time)}`
- [ ] On SubagentStart/Stop: record count change with timestamp but don't emit status update immediately
- [ ] Add debounce check: only emit status update if count has been stable for >2s (checked on next poll cycle)
- [ ] In `_handle_subagent_start`/`_handle_subagent_stop`: replace immediate `enqueue_status_update` with debounced version
- [ ] Write tests for debounce logic (rapid start/stop produces no status, stable count >2s produces status)
- [ ] Run tests — must pass before next task

### Task 5: Fix Stop flicker — wait for LLM summary

**Files:**

- Modify: `src/ccgram/handlers/hook_events.py`

- [ ] In `_handle_stop`: if LLM is configured, don't send immediate "Ready" status
- [ ] Instead, launch `_enhance_with_llm_summary` and await it with `asyncio.wait_for(timeout=3.0)`
- [ ] On success: send the enhanced Ready with summary
- [ ] On timeout/error: fall back to plain enriched Ready (task checklist + last status)
- [ ] Write tests for: LLM success path, LLM timeout path, no-LLM-configured path
- [ ] Run tests — must pass before next task

### Task 6: Truncate expandable quotes at 3500 chars

**Files:**

- Modify: `src/ccgram/transcript_parser.py` or `src/ccgram/entity_formatting.py`

- [ ] In `format_expandable_quote` (or `_format_tool_result_text`): if quote content exceeds 3500 chars, truncate with `\n\n... (truncated, {total} chars total)`
- [ ] This prevents atomic unsplit messages from exceeding Telegram's 4096 limit (3500 content + sentinels + stats line fits within budget)
- [ ] Write tests: short quote passes through, long quote gets truncated with indicator
- [ ] Run tests — must pass before next task

### Task 7: Debounce screenshot key presses

**Files:**

- Modify: `src/ccgram/handlers/screenshot_callbacks.py`

- [ ] Add `_key_debounce: dict[tuple[int, str], float]` tracking `{(user_id, window_id): last_key_time}`
- [ ] In `_handle_keys`: if another key was pressed within 0.3s, skip the capture/render/edit — only process the latest key
- [ ] Use `asyncio.create_task` with 0.3s delay that cancels on next key press
- [ ] Write tests for debounce logic (rapid taps coalesce to single render)
- [ ] Run tests — must pass before next task

### Task 8: Clean up ghost window queue entries

**Files:**

- Modify: `src/ccgram/handlers/message_queue.py`

- [ ] In `_message_queue_worker`: before processing a content task, check if `window_id` is still bound in any thread_binding
- [ ] If window_id is not bound: log a debug message and call `task_done()` to skip the task
- [ ] This prevents the @273-style noise where deleted windows still have queue tasks draining
- [ ] Write test: enqueue task for unbound window_id, verify it's skipped
- [ ] Run tests — must pass before next task

### Task 9: Verify acceptance criteria

- [ ] Verify batch mode is default for new windows
- [ ] Verify /verbose toggles back to individual mode
- [ ] Verify trivial thinking messages are filtered
- [ ] Verify MONITOR_POLL_INTERVAL defaults to 1.0s with min guard
- [ ] Verify MESSAGE_SEND_INTERVAL is 0.5s
- [ ] Verify STATUS_POLL_INTERVAL is configurable
- [ ] Verify subagent status is debounced
- [ ] Verify Stop doesn't flicker when LLM is configured
- [ ] Verify long expandable quotes are truncated
- [ ] Verify screenshot keys are debounced
- [ ] Verify ghost window queue entries are skipped
- [ ] Run full test suite: `make check`

### Task 10: [Final] Update documentation

- [ ] Update CLAUDE.md with new defaults (batch mode, intervals, env vars)
- [ ] Update architecture.md if any new modules/constants are significant
- [ ] Move this plan to `docs/plans/completed/`

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
