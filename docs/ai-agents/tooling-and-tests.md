# Tooling and Tests

## Build and Validation Commands

Primary command set from `Makefile`:

- `make fmt`
- `make test`
- `make lint`
- `make typecheck`
- `make check` (runs fmt + lint + typecheck + test + integration)
- `make build`

Default local workflow for code changes:

1. `make fmt`
2. `make test`
3. `make lint`
4. `make typecheck`

Before considering work complete, run at least:

- `make check` (full gate: fmt + lint + typecheck + test)

## Toolchain and Libraries

- Python: `>=3.14`
- Package/dependency manager: `uv`
- Telegram framework: `python-telegram-bot`
- tmux integration: `libtmux`
- async/file IO: `aiofiles`
- logging: `structlog`
- terminal parsing: `pyte`
- HTTP client (LLM, Whisper): `httpx`
- screenshot rendering: `Pillow`

## Test Layout

- `tests/ccgram/`: unit tests mirroring source modules.
- `tests/integration/`: integration tests for monitor flow, dispatch, tmux manager, state roundtrips.
- `tests/conftest.py`: required test env setup before imports.
- Hypothesis property-based tests: `tests/ccgram/test_message_queue_properties.py`.

## Fast Test Targeting

Use focused test files that match changed modules first, then full test run.

Examples:

- session/state changes -> `tests/ccgram/test_session.py`, `tests/ccgram/test_window_state_store.py`
- monitor/parsing changes -> `tests/ccgram/test_session_monitor.py`, `tests/ccgram/test_transcript_parser.py`
- handlers/UI changes -> `tests/ccgram/handlers/text/test_text_handler.py`, `tests/ccgram/handlers/polling/test_polling_coordinator.py`, `tests/ccgram/handlers/polling/test_polling_strategies.py`, `tests/ccgram/handlers/test_bot_callbacks.py`
- command changes -> `tests/ccgram/test_command_catalog.py`, `tests/ccgram/test_commands_command.py`, `tests/ccgram/test_cc_commands.py`, `tests/ccgram/handlers/commands/test_forward.py`, `tests/ccgram/handlers/commands/test_menu_sync.py`, `tests/ccgram/handlers/commands/test_failure_probe.py`, `tests/ccgram/handlers/commands/test_status_snapshot.py`
- hook/event changes -> `tests/ccgram/test_hook.py`, `tests/ccgram/handlers/test_hook_events.py`, `tests/ccgram/test_session_monitor_events.py`
- cleanup/lifecycle changes -> `tests/ccgram/handlers/test_cleanup.py`, `tests/ccgram/handlers/status/test_topic_emoji.py`, `tests/ccgram/handlers/topics/test_topic_lifecycle.py`
- provider changes -> `tests/ccgram/providers/test_contracts.py`, `tests/ccgram/providers/test_jsonl_providers.py`, `tests/ccgram/providers/test_autodetect.py`
- shell/LLM changes -> `tests/ccgram/providers/test_shell.py`, `tests/ccgram/handlers/shell/test_shell_commands.py`, `tests/ccgram/handlers/shell/test_shell_capture.py`, `tests/ccgram/handlers/shell/test_shell_prompt_orchestrator.py`
- voice changes -> `tests/ccgram/handlers/voice/test_voice_handler.py`
- live view changes -> `tests/ccgram/handlers/live/test_live_view.py`
- polling/periodic changes -> `tests/ccgram/handlers/polling/test_polling_coordinator.py`, `tests/ccgram/handlers/polling/test_polling_strategies.py`, `tests/ccgram/handlers/polling/test_polling_types_purity.py`, `tests/ccgram/handlers/polling/test_status_polling.py`
- recovery UX changes -> `tests/ccgram/handlers/recovery/test_recovery_banner.py`, `tests/ccgram/handlers/recovery/test_recovery_ui.py`, `tests/ccgram/handlers/recovery/test_recovery_subpackage_surface.py`
- structural invariants (Round 5) -> `tests/ccgram/test_query_layer_only_for_handlers.py`, `tests/ccgram/test_lint_lazy_imports.py`, `tests/integration/test_import_no_cycles.py`
- topic lifecycle changes -> `tests/ccgram/handlers/topics/test_topic_orchestration.py`, `tests/ccgram/handlers/topics/test_topic_lifecycle.py`
- tool-call visibility / `/toolcalls` -> `tests/ccgram/handlers/messaging_pipeline/test_message_queue.py` (visibility gate), `tests/ccgram/test_window_state_store.py` (state field + cycle)
- provider switching (claude↔shell↔gemini) -> `tests/ccgram/handlers/polling/test_status_polling.py::TestProviderSwitchPromptSetup`, `TestProviderSwitchChain`

## Quality Constraints

- all hook/check issues are blocking.
- fix failing checks before proceeding to unrelated work.
- preserve existing architecture constraints (topic-window identity, provider boundaries, send-layer split).
