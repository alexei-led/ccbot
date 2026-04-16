# AgentProvider Protocol — Test Specification

## Unit Tests

### Default implementations (non-shell providers)

- **`test_ensure_prompt_marker_default_is_noop`**
  Scenario: Call `ensure_prompt_marker(window_id)` on `ClaudeProvider`,
  `CodexProvider`, and `GeminiProvider`.
  Expected: Each awaits without raising; no tmux calls are made.

- **`test_prompt_marker_present_default_returns_true`**
  Scenario: Call `prompt_marker_present(capture)` on any non-shell provider
  with arbitrary capture text.
  Expected: Returns `True` unconditionally.

### ShellProvider implementation

- **`test_ensure_prompt_marker_calls_setup_when_absent`**
  Scenario: `prompt_marker_present` returns `False` for the current pane
  capture; call `ensure_prompt_marker(window_id)`.
  Expected: `setup_shell_prompt(window_id)` is called exactly once.

- **`test_ensure_prompt_marker_skips_when_present`**
  Scenario: `prompt_marker_present` returns `True` for the current pane
  capture; call `ensure_prompt_marker(window_id)`.
  Expected: `setup_shell_prompt` is not called.

- **`test_prompt_marker_present_true_when_marker_in_capture`**
  Scenario: Pass a pane capture string containing the `⌘N⌘` marker sequence.
  Expected: Returns `True`.

- **`test_prompt_marker_present_false_when_no_marker`**
  Scenario: Pass a pane capture string with ordinary shell output and no marker.
  Expected: Returns `False`.

## Integration Contract Tests

- **`test_all_providers_satisfy_extended_protocol`**
  Scenario: For each registered provider (`claude`, `codex`, `gemini`, `shell`),
  verify the instance satisfies `isinstance(provider, AgentProvider)` (structural
  subtyping via `runtime_checkable` or `Protocol` verification).
  Expected: No `AttributeError`; all four methods (`ensure_prompt_marker`,
  `prompt_marker_present`, and the existing protocol methods) are present and
  callable.

- **`test_shell_provider_marker_round_trip`**
  Scenario: `ensure_prompt_marker` on a live tmux pane with `inject_fn` mocked;
  then `prompt_marker_present` on the resulting captured output.
  Expected: The two methods form a consistent detect→inject→detect cycle.

## Boundary Tests

- **`test_prompt_marker_present_empty_capture`**
  Scenario: Pass an empty string to `prompt_marker_present` on `ShellProvider`.
  Expected: Returns `False` (not an error).

- **`test_ensure_prompt_marker_invalid_window_id`**
  Scenario: Pass a window ID that does not exist in the tmux session.
  Expected: Raises `TmuxWindowNotFound` or returns silently (provider-specific
  contract); does not propagate an unhandled exception to the caller.

## Behaviour Tests

- **`test_orchestrator_uses_protocol_not_shell_infra`**
  Scenario: In `shell_prompt_orchestrator`, verify no direct import of
  `providers.shell_infra` symbols exists (static import analysis).
  Expected: `ast.walk` finds no `ImportFrom` nodes targeting
  `providers.shell_infra` in `shell_prompt_orchestrator.py`.

- **`test_non_shell_provider_orchestrator_call_is_noop`**
  Scenario: Call `ensure_setup(window_id)` from the orchestrator with a
  `ClaudeProvider` resolved for the window.
  Expected: Completes without error; no tmux interaction.
