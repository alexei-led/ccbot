# Directory Callbacks — Provider Detection Cleanup Test Specification

## Unit Tests

### Shell detection via `detect_provider_from_command`

- **`test_shell_binary_detected_as_shell`**
  Scenario: `detect_provider_from_command` is called for each of `bash`, `zsh`,
  `fish`, `sh`. Verify the result is `"shell"`.
  Expected: Returns `"shell"` for all known shell binaries.

- **`test_non_shell_binary_not_detected_as_shell`**
  Scenario: `detect_provider_from_command("claude")` and
  `detect_provider_from_command("python")`.
  Expected: Returns `"claude"` and `None` respectively, not `"shell"`.

- **`test_directory_callbacks_no_known_shells_import`**
  Scenario: Static analysis — verify `directory_callbacks.py` has no
  `ImportFrom` node that imports `KNOWN_SHELLS`.
  Expected: Zero matches.

### Shell topic auto-setup after `detect_provider_from_command`

- **`test_shell_topic_triggers_prompt_setup`**
  Scenario: Directory browser completes for a window where
  `detect_provider_from_command` returns `"shell"`.
  Expected: `ensure_setup(window_id)` is called; `set_window_provider` is
  called with `"shell"`.

- **`test_non_shell_topic_skips_prompt_setup`**
  Scenario: Directory browser completes for a window where
  `detect_provider_from_command` returns `"claude"`.
  Expected: `ensure_setup` is not called.

## Integration Contract Tests

- **`test_new_shell_binary_detected_without_callback_change`**
  Scenario: Add a hypothetical new shell name (`"nu"`) to `KNOWN_SHELLS` in
  `providers.shell_infra`. Call the directory browser callback with `"nu"` as
  the chosen command.
  Expected: Detected as shell and prompt setup is triggered — with no change
  to `directory_callbacks.py`.

## Boundary Tests

- **`test_empty_command_string`**
  Scenario: `detect_provider_from_command("")`.
  Expected: Returns `None`; does not raise.

- **`test_command_with_path_prefix`**
  Scenario: `detect_provider_from_command("/bin/bash")` — full path, not basename.
  Expected: Returns `"shell"` (function handles path stripping).

## Behaviour Tests

- **`test_full_directory_browser_flow_shell_window`**
  Scenario: Integration test — simulate the complete flow from directory
  selection through provider detection to window creation and prompt setup for
  a shell window.
  Expected: Window created with `provider_name="shell"`, prompt marker setup
  initiated, topic bound.
