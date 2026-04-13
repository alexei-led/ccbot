# Shell Provider UX

## Functional Responsibilities

The shell provider turns a Telegram topic into an interactive shell session backed by a tmux window running `$SHELL`. Text messages become commands (optionally translated from natural language via an LLM); command output is captured and relayed back; dangerous commands go through an approval keyboard. A per-window prompt marker (`⌘N⌘` or `{prefix}:N❯`) enables output isolation and exit-code detection.

Files after refactor:

- **`handlers/shell_commands.py`** (~420 lines) — NL→command generation, approval keyboard, run/edit/cancel callbacks, `handle_shell_message`, `_execute_raw_command`, `show_command_approval`, `_cancel_stuck_input`.
- **`handlers/shell_capture.py`** (~530 lines) — passive output monitoring, exit-code detection, baseline-diff fallback, glyph stripping, relay formatting, error-suggestion generation. Existing.
- **`handlers/shell_context.py`** (~65 lines) — shared `gather_llm_context`, `redact_for_llm`, `mark_telegram_command`, `_MODERN_TOOLS`, `_detect_shell_tools`. Breaks the `shell_commands ↔ shell_capture` circular import by owning the helpers both need. Already extracted.
- **`handlers/shell_prompt_orchestrator.py`** (NEW, ~120 lines) — single entry point for deciding when to run `setup_shell_prompt`. Owns the `skip`/`lazy-recovery`/`offer`/`auto` decision tree.
- **`providers/shell_infra.py`** (~270 lines) — mechanics of prompt-marker setup: `setup_shell_prompt`, `has_prompt_marker`, `match_prompt`, `detect_pane_shell`, `_wrap_setup_commands`, `_replace_setup_commands`, `_is_interactive_shell`, `KNOWN_SHELLS`, `PromptMatch`. Owns the shell-inventory knowledge. Already extracted.
- **`providers/shell.py`** (~80 lines) — the slim `ShellProvider` class only. Already slimmed.

## Encapsulated Knowledge

- **Prompt-marker setup policy** is owned entirely by `shell_prompt_orchestrator.py`. The decision tree (auto-setup vs. offer-keyboard vs. lazy-recovery vs. skip-respect vs. re-offer-on-provider-switch) lives in one function. No handler outside this file decides when to run setup.
- **Prompt-marker mechanics** are owned by `shell_infra.py`. How the marker is injected (which tmux keys, which wrap/replace command, which shell's syntax) is Shell-provider-specific knowledge and nothing else touches it.
- **NL→command generation rules** are owned by `shell_commands.py`. Only this file knows how to prompt the LLM, how to interpret the response (raw vs. approval-needed vs. dangerous), how to surface ambiguity.
- **Output extraction** is owned by `shell_capture.py`. Only this file knows how to find the `⌘N⌘` marker in pane text, extract the most recent command's output, detect exit code, and fall back to baseline-diff if the marker is missing.
- **Shared LLM context and redaction** — `shell_context.py` owns `gather_llm_context` (what pane slice + metadata to send as context) and `redact_for_llm` (secret patterns, env var names, token shapes). Both `shell_commands` and `shell_capture` use them; neither owns them.

## Subdomain Classification

**Core.** The shell provider is an active development area. NL→command generation and output relay are distinguishing features. The prompt-marker setup flow has been refined across three releases and still has known tradeoffs (wrap vs. replace mode; session-scoped skip). High volatility.

## Integration Contracts

### Inbound

| From                                                                                                                                     | Kind     | Contract                                                                |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------- |
| `handlers/text_handler` → `shell_commands.handle_shell_message(update, context)`                                                         | Contract | Standard PTB handler; routed when `WindowView.provider_name == "shell"` |
| PTB callback dispatcher → `shell_commands._dispatch`                                                                                     | Contract | Shell run/edit/cancel/confirm-danger callbacks                          |
| `polling_strategies.ShellRelayStrategy` → `shell_capture.check_passive_output(...)`                                                      | Contract | Per-window capture poll                                                 |
| `directory_callbacks._create_window_and_bind` (after shell topic creation) → `shell_prompt_orchestrator.ensure_setup(window_id, "auto")` | Contract | Single entry point                                                      |
| `window_callbacks._handle_bind` (external window bind) → `shell_prompt_orchestrator.ensure_setup(window_id, "external_bind")`            | Contract | Shows offer keyboard internally                                         |
| `transcript_discovery` (provider switch to shell detected) → `shell_prompt_orchestrator.ensure_setup(window_id, "provider_switch")`      | Contract | Honours skip flag                                                       |
| `shell_commands._ensure_prompt_marker` (called before every send) → `shell_prompt_orchestrator.ensure_setup(window_id, "lazy")`          | Contract | No-op if marker present                                                 |

### Outbound

| To                                                                 | Kind     | Contract                                                     |
| ------------------------------------------------------------------ | -------- | ------------------------------------------------------------ |
| `llm.get_completer()` → `CommandGenerator.generate(text, context)` | Contract | Returns `CommandResult` (command, is_dangerous, explanation) |
| `tmux_manager.send_keys`, `tmux_manager.capture_pane`              | Contract | Standard tmux ops                                            |
| `message_queue.enqueue_content_message(...)`                       | Contract | Relay output to Telegram                                     |
| `providers/shell_infra.setup_shell_prompt(window_id, clear=...)`   | Contract | Called only by orchestrator                                  |
| `providers/shell_infra.has_prompt_marker(window_id)`               | Contract | Idempotency check                                            |
| `providers/shell_infra.detect_pane_shell(window_id)`               | Contract | Shell inventory lookup                                       |

### The orchestrator API

```python
# handlers/shell_prompt_orchestrator.py
from typing import Literal

Trigger = Literal["auto", "external_bind", "provider_switch", "lazy"]

@dataclass
class _WindowOrchestratorState:
    skip_flag: bool = False
    last_setup_ts: float = 0.0
    was_offered: bool = False

_state: dict[str, _WindowOrchestratorState] = {}  # or fold into WindowState

async def ensure_setup(window_id: str, trigger: Trigger) -> None:
    """Single entry point for prompt-marker setup.

    auto           — run setup silently (directory-browser-created shell topics)
    external_bind  — show offer keyboard (user binds existing shell window)
    provider_switch — show offer keyboard (agent pane fell back to shell;
                      respects skip_flag from last session)
    lazy           — run setup only if marker is missing AND skip_flag not set
                    (called before every command send)
    """
    # ... policy decision tree
    pass

async def accept_offer(window_id: str) -> None:
    """User tapped 'Set up' in the offer keyboard."""
    pass

def record_skip(window_id: str) -> None:
    """User tapped 'Skip' in the offer keyboard. Session-scoped."""
    pass
```

## Change Vectors

- **Add a new shell (e.g. `nushell`, `elvish`)** — touches `shell_infra.KNOWN_SHELLS` + `_wrap_setup_commands` branches. No change to orchestrator or handlers.
- **Add a new setup trigger (e.g., "re-setup if tmux respawn-window was used")** — add a new `Trigger` literal + one caller. Policy change is local.
- **Tighten skip semantics (e.g., "persistent skip across bot restarts")** — touches `shell_prompt_orchestrator` only (state serialisation).
- **New LLM for command generation** — touches `llm/` configuration. No change to `shell_commands`.
- **Change the relay format (e.g., group consecutive short outputs)** — touches `shell_capture.relay_output()` only.
- **New dangerous-command detection rule** — touches `shell_commands.is_dangerous_command()` only.

## Refactor Plan

1. Create `handlers/shell_prompt_orchestrator.py`. Move the five scattered setup-decision predicates into one `ensure_setup(window_id, trigger)` function with an enum trigger kind.
2. Migrate the 5 call sites: `directory_callbacks`, `window_callbacks`, `transcript_discovery`, `shell_commands._ensure_prompt_marker`, `shell_capture` (read-side, if it triggers setup at all — verify). Each becomes a one-line call.
3. Move the per-window orchestrator state dict (`skip_flag`, `last_setup_ts`, `was_offered`) into the orchestrator. Optionally, fold into `WindowState` for persistence across bot restarts (requires a small migration).
4. Add a test harness: feed `ensure_setup` a synthetic window state and verify the decision branches (`auto` runs, `lazy` no-ops if marker present, `external_bind` defers to offer, `provider_switch` respects skip).
5. Leave `shell_infra.setup_shell_prompt` exactly as it is — it is the right layer for mechanics.

## Testability Goals

- **Unit-test the orchestrator decision tree** with a fake `has_prompt_marker` and a fake `setup_shell_prompt`, parameterised by trigger × (skip_flag × marker_present × was_offered). A table test covers every branch.
- **Unit-test `redact_for_llm`** (already in `shell_context.py`) — secret patterns, env vars, token shapes. Pure function.
- **Unit-test `gather_llm_context`** with a fixture pane text — pure function.
- **Unit-test `shell_capture._parse_output_with_marker`** with a fixture pane text and various marker positions.
- **Unit-test `shell_commands.is_dangerous_command`** — table test.
- **Integration-test `handle_shell_message`** with a mocked LLM completer (returns a safe command) and a mocked `tmux_manager.send_keys` — verify the command reaches tmux and the relay is enqueued.
- **Integration-test the offer-keyboard flow** with a fake orchestrator state — verify tapping Set up runs `setup_shell_prompt`, tapping Skip records `skip_flag=True`.
