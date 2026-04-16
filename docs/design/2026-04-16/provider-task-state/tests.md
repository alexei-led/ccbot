# Provider Task State Abstraction — Test Specification

## Unit Tests

### test_capability_flag_defaults_false

- **Scenario**: Create a provider with default capabilities
- **Expected behavior**: `capabilities.supports_task_tracking` is `False`

### test_claude_provider_has_task_tracking

- **Scenario**: Check `ClaudeProvider().capabilities.supports_task_tracking`
- **Expected behavior**: `True`

### test_other_providers_lack_task_tracking

- **Scenario**: Check `CodexProvider`, `GeminiProvider`, `ShellProvider` capabilities
- **Expected behavior**: All have `supports_task_tracking == False`

### test_default_seed_task_state_is_noop

- **Scenario**: Call `provider.seed_task_state(wid, sid, path)` on a CodexProvider
- **Expected behavior**: Returns without error, no state changes

### test_default_apply_task_entries_is_noop

- **Scenario**: Call `provider.apply_task_entries(wid, sid, entries)` on a GeminiProvider
- **Expected behavior**: Returns without error, no state changes

### test_claude_seed_task_state_delegates

- **Scenario**: Call `ClaudeProvider().seed_task_state(wid, sid, path)` with a mock `claude_task_state`
- **Expected behavior**: `claude_task_state.seed_from_transcript(wid, sid, path)` called once

### test_claude_apply_task_entries_delegates

- **Scenario**: Call `ClaudeProvider().apply_task_entries(wid, sid, entries)` with mock
- **Expected behavior**: `claude_task_state.apply_entries(wid, sid, entries)` called once with the same entries

## Integration Contract Tests

### test_transcript_reader_uses_capability_flag

- **Scenario**: Set up `TranscriptReader` with a provider whose `supports_task_tracking = True`. Process a session file.
- **Expected behavior**: `provider.seed_task_state` called. No string comparison against `provider.capabilities.name`.

### test_transcript_reader_skips_task_state_for_non_tracking_provider

- **Scenario**: Set up `TranscriptReader` with Codex provider. Process a session file.
- **Expected behavior**: `provider.seed_task_state` never called. `provider.apply_task_entries` never called.

### test_transcript_reader_no_claude_imports

- **Scenario**: Grep `transcript_reader.py` for `claude_task_state` imports
- **Expected behavior**: Zero matches. The module has no knowledge of Claude's task-state implementation.

### test_transcript_reader_no_provider_name_checks

- **Scenario**: Grep `transcript_reader.py` for `capabilities.name`
- **Expected behavior**: Zero matches. No provider identity checks remain.

## Boundary Tests

### test_seed_task_state_with_missing_transcript

- **Scenario**: Call `ClaudeProvider().seed_task_state(wid, sid, "/nonexistent/path")`
- **Expected behavior**: Handles gracefully (no crash). `claude_task_state` handles missing files internally.

### test_apply_task_entries_with_empty_list

- **Scenario**: Call `provider.apply_task_entries(wid, sid, [])`
- **Expected behavior**: No-op, no error

### test_apply_task_entries_with_non_task_entries

- **Scenario**: Call with transcript entries that contain no task information (e.g., plain assistant messages)
- **Expected behavior**: No crash, task state unchanged

## Behavior Tests

### test_claude_task_tracking_end_to_end

- **Scenario**: Full flow: create a Claude window, process JSONL transcript with TaskCreate/TaskUpdate entries, query task state
- **Expected behavior**: Task state reflects the transcript entries. Same behavior as before the refactoring — the protocol change is transparent.

### test_codex_window_ignores_task_state

- **Scenario**: Full flow with Codex provider, process transcript
- **Expected behavior**: No task state created. Status bubble shows no task list. No errors.

### test_new_provider_with_task_tracking

- **Scenario**: Create a mock provider with `supports_task_tracking = True` and custom `seed_task_state`/`apply_task_entries` implementations
- **Expected behavior**: `transcript_reader` calls the mock methods. Demonstrates extensibility without modifying generic code.
