# Shell Prompt Orchestrator — Test Specification

## Unit Tests

### Skip semantics

- **`test_ensure_setup_skipped_when_user_chose_skip`**
  Scenario: `view_window()` returns a `WindowView` with `prompt_marker_skip=True`.
  Call `ensure_setup(window_id)`.
  Expected: `provider.ensure_prompt_marker` is never called.

- **`test_ensure_setup_proceeds_when_no_skip`**
  Scenario: `view_window()` returns `prompt_marker_skip=False` (or unset).
  Expected: `provider.ensure_prompt_marker` is awaited exactly once.

### Provider delegation

- **`test_ensure_setup_delegates_to_provider`**
  Scenario: Mock `get_provider_for_window` to return a mock provider.
  Call `ensure_setup(window_id)`.
  Expected: `mock_provider.ensure_prompt_marker(window_id)` is awaited; no
  direct calls to `setup_shell_prompt` or `has_prompt_marker`.

- **`test_ensure_setup_no_direct_shell_infra_calls`**
  Scenario: Static analysis — verify `shell_prompt_orchestrator.py` has no
  `ImportFrom` nodes with module paths containing `shell_infra`.
  Expected: Zero matches (import removed by this design).

### Trigger site coverage

- **`test_trigger_on_window_creation`**
  Scenario: Simulate directory browser completing for a shell window. Verify
  `ensure_setup` is invoked with the new window ID.
  Expected: Provider's `ensure_prompt_marker` is called once.

- **`test_trigger_on_lazy_recovery`**
  Scenario: Shell command sent when marker is absent (prompt not yet configured).
  Expected: `ensure_setup` is invoked before the command is forwarded.

## Integration Contract Tests

- **`test_orchestrator_integrates_with_shell_provider`**
  Scenario: Use a real `ShellProvider` instance with `inject_fn` mocked to a
  no-op. Call `ensure_setup(window_id)` from the orchestrator.
  Expected: The provider's `ensure_prompt_marker` is called; no shell-infra
  symbols are imported directly.

- **`test_orchestrator_integrates_with_claude_provider`**
  Scenario: Use a real `ClaudeProvider` instance. Call `ensure_setup(window_id)`.
  Expected: Completes without error; no tmux interaction occurs.

## Boundary Tests

- **`test_ensure_setup_unknown_window_id`**
  Scenario: `view_window()` returns `None` (window not found).
  Expected: Returns early without error; `ensure_prompt_marker` is not called.

- **`test_ensure_setup_provider_raises`**
  Scenario: `provider.ensure_prompt_marker` raises `OSError`.
  Expected: Exception propagates (orchestrator does not swallow it silently).

## Behaviour Tests

- **`test_all_five_trigger_sites_call_ensure_setup`**
  Scenario: Trace the five code paths (directory creation, provider switch,
  lazy recovery, exec restore, external adoption) each call `ensure_setup`.
  Expected: Each path results in exactly one `ensure_setup` invocation
  (verified via mock counting at the orchestrator entry point).
