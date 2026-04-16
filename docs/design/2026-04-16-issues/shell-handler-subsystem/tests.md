# Shell Handler Subsystem — Test Specification

## Unit Tests

### Public API surface (via `handlers/shell/__init__.py`)

- **`test_public_api_exports_entry_points`**
  Scenario: Import `handlers.shell` and verify the four public names are present:
  `handle_shell_message`, `ensure_setup`, `extract_output`, `is_shell_idle`.
  Expected: All four are importable from the package root; no `AttributeError`.

- **`test_internal_modules_not_re_exported`**
  Scenario: Verify that implementation-level names (`match_prompt`, `KNOWN_SHELLS`,
  `detect_pane_shell`) are not in `handlers.shell.__all__` (or not directly
  accessible at package level).
  Expected: `hasattr(handlers.shell, "match_prompt")` is `False`.

### Output isolation (`extract_output`)

- **`test_extract_output_between_two_markers`**
  Scenario: Pane capture contains two prompt-marker lines with command output
  between them.
  Expected: Returns the lines between markers only; marker lines excluded.

- **`test_extract_output_single_marker`**
  Scenario: Only one marker present (command in progress).
  Expected: Returns empty string or `None` (command not yet complete).

- **`test_extract_output_no_marker`**
  Scenario: No marker in capture (prompt not configured).
  Expected: Falls back to baseline-diff extraction (existing behavior).

### Idle detection (`is_shell_idle`)

- **`test_is_shell_idle_true_when_prompt_present`**
  Scenario: Capture tail contains a prompt-marker line.
  Expected: Returns `True`.

- **`test_is_shell_idle_false_when_command_running`**
  Scenario: Capture tail has no prompt-marker line (command running).
  Expected: Returns `False`.

## Integration Contract Tests

- **`test_subsystem_dependency_on_providers_shell_is_explicit`**
  Scenario: Static analysis — verify all imports of `providers.shell` or
  `providers.shell_infra` within the subsystem originate from inside
  `handlers/shell/`, not from `handlers/` top-level files.
  Expected: Zero matches for `from.*providers.shell` in `handlers/*.py`
  (top-level handler files only, not the sub-package).

- **`test_handle_shell_message_routes_through_llm`**
  Scenario: Call `handle_shell_message` with a natural language input and a
  mock LLM that returns a command string.
  Expected: The command is sent via `send_keys`; LLM receives the prompt;
  approval keyboard is shown when dangerous command is detected.

- **`test_handle_shell_message_raw_passthrough_with_prefix`**
  Scenario: Input prefixed with `!`.
  Expected: Command sent directly via `send_keys`; LLM not called.

## Boundary Tests

- **`test_extract_output_empty_capture`**
  Scenario: Empty string passed to `extract_output`.
  Expected: Returns empty string without error.

- **`test_handle_shell_message_no_llm_configured`**
  Scenario: `get_completer()` returns `None`.
  Expected: Input forwarded as raw command (no LLM call, no approval keyboard).

- **`test_subsystem_no_cross_imports_from_non_shell_handlers`**
  Scenario: Static analysis — verify `handlers/shell/` modules do not import
  from top-level handler modules (e.g., `handlers.text_handler`,
  `handlers.command_orchestration`).
  Expected: No such imports found (subsystem is self-contained except for
  shared infrastructure like `window_query`, `message_queue`).

## Behaviour Tests

- **`test_dangerous_command_triggers_approval_keyboard`**
  Scenario: LLM classifies the generated command as dangerous (e.g., `rm -rf /`).
  Expected: Approval keyboard is shown to the user; command is not sent until
  confirmed.

- **`test_passive_relay_extracts_output_and_routes_to_queue`**
  Scenario: Shell command completes; passive polling detects marker pair.
  Expected: Extracted output is enqueued as a `ContentTask` for the correct
  window; topic receives the message.
