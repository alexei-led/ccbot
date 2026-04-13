# Provider Abstraction

## Functional Responsibilities

Unified interface for agent CLI backends — Claude Code, Codex, Gemini, and shell. Each provider implements the `AgentProvider` protocol and declares its capabilities via `ProviderCapabilities`. The layer handles: launch argument construction, hook payload parsing, transcript file reading, per-entry parsing, terminal status scraping, history rendering, command discovery, and per-provider auto-detection from running processes.

Files:

- **`providers/base.py`** — `AgentProvider` protocol, `ProviderCapabilities` dataclass, shared event types (`SessionStartEvent`, `AgentMessage`, `StatusUpdate`, `DiscoveredCommand`, `HookEvent`). `UUID_RE` / `RESUME_ID_RE` regex constants. After refactor, **adds `scrape_current_mode` method** to the protocol.
- **`providers/registry.py`** — `ProviderRegistry` maps provider names to factories; caches singleton instances.
- **`providers/_jsonl.py`** — shared JSONL parsing base class for Codex and Gemini.
- **`providers/claude.py`** — `ClaudeProvider`; owns hook parsing, `--resume` semantics, JSONL incremental reads, `pyte` / spinner status detection. **After refactor, owns Claude mode-line scraping** (moved from `toolbar_callbacks`).
- **`providers/codex.py`** — `CodexProvider`; owns Codex's `resume` flow, JSONL parsing, activity-heuristic status.
- **`providers/gemini.py`** — `GeminiProvider`; owns whole-file JSON transcript reading, pane title parsing for detection.
- **`providers/shell.py`** — slim `ShellProvider` class; delegates mechanics to `shell_infra.py`.
- **`providers/shell_infra.py`** — prompt-marker mechanics (`setup_shell_prompt`, `has_prompt_marker`, `match_prompt`, `detect_pane_shell`, shell inventory).
- **`providers/codex_status.py`** — Codex status snapshot builder.
- **`providers/codex_format.py`** — Codex interactive prompt formatter.
- **`providers/process_detection.py`** — `ps -t`-based foreground process detection for provider auto-detection when the pane command is a JS runtime wrapper.
- **`providers/__init__.py`** — `get_provider_for_window(window_id)`, `get_provider(name)`, `detect_provider_from_pane(...)`, `detect_provider_from_command(...)`. The resolution entry points.

## Encapsulated Knowledge

Each concrete provider owns knowledge that nothing else in ccgram should touch:

- **Claude** — `UUID_RE` session id format, `--resume {id}` flag, JSONL line schema (`type`, `message.content[]`, `tool_use`, `tool_result`, `parent_uuid`), hook stdin JSON schema, pyte + spinner status detection, mode-line sentinel strings ("auto-accept edits", "Plan mode", "Full tool access"), command discovery under `~/.claude/skills/` and `~/.claude/commands/`.
- **Codex** — `resume` subcommand, JSONL schema, activity-timestamp-based status.
- **Gemini** — JSON whole-file transcript, pane-title-based detection, `--resume idx/latest`.
- **Shell** — `$SHELL` detection, `KNOWN_SHELLS` (bash/zsh/fish/dash/sh/xonsh), `wrap` vs. `replace` prompt mode, `C-c` tmux key as "cancel input".

Handlers should not know any of this. When a handler needs to know "how does Claude format its resume argument", it asks `provider.make_launch_args(...)`. When it needs to know "what mode is the agent in", it asks `provider.scrape_current_mode(window_id)`.

## Subdomain Classification

**Core internal / low taxonomic volatility.** Each existing provider's internal behaviour evolves (new tool formats, new event types), which is high volatility. Adding a new provider row (Aider, Cursor) is unlikely — confirmed by the maintainer — which makes the _axis of "how many providers"_ low volatility. This distinction matters because it downgrades the urgency of fully provider-agnostic handler code.

`providers/base.py` is the most stable file in the layer. Concrete providers see more change.

## Integration Contracts

### Inbound

| From                                                           | Kind     | Contract                            |
| -------------------------------------------------------------- | -------- | ----------------------------------- |
| `handlers/*` → `get_provider_for_window(window_id)`            | Contract | Returns `AgentProvider \| None`     |
| `CLI commands` (doctor, status) → `get_provider(name)`         | Contract | Returns concrete provider or raises |
| `handlers/window_callbacks` → `detect_provider_from_pane(...)` | Contract | Auto-detection                      |
| `session.py` → `detect_provider_from_command(...)`             | Contract | Fast-path from basename             |

### Outbound

| To                                                                    | Kind     | Contract             |
| --------------------------------------------------------------------- | -------- | -------------------- |
| `hook.py` → `ClaudeProvider.parse_hook_payload(payload)`              | Contract | Inbound hook stdin   |
| `session_monitor` → `provider.read_transcript_file(...)`              | Contract | Incremental read     |
| `polling_coordinator` → `provider.build_status_snapshot(...)`         | Contract | Terminal status      |
| `toolbar_callbacks` → `provider.scrape_current_mode(window_id)` (NEW) | Contract | Mode label or `None` |
| `session_resolver` → `provider.parse_transcript_entries(...)`         | Contract | Transcript parsing   |
| `cc_commands` → `provider.discover_commands(base_dir)`                | Contract | Command discovery    |

### The new capability

```python
# providers/base.py — append to AgentProvider protocol
async def scrape_current_mode(self, window_id: str) -> str | None:
    """Return a short label describing the agent's current mode.

    Implementations capture the pane text and parse provider-specific
    mode indicators. Return None if the provider doesn't support reading
    mode state (default) or if no mode line is present in the capture.

    Examples:
      Claude: "Edit", "Plan", "Full", "Def"
      Gemini: "YOLO" / None
      Codex: None (no mode line)
      Shell: None
    """
    return None
```

```python
# providers/claude.py — implementation
async def scrape_current_mode(self, window_id: str) -> str | None:
    from ..tmux_manager import tmux_manager
    capture = await tmux_manager.capture_pane(window_id)
    if not capture:
        return None
    mode_line = self._find_mode_line(capture)
    if mode_line is None:
        return None
    return self._mode_short_label(mode_line)

def _find_mode_line(self, capture: str) -> str | None:
    # ... regex + sentinel search, moved from toolbar_callbacks
    pass

def _mode_short_label(self, mode_line: str) -> str:
    # ... moved from toolbar_callbacks
    pass
```

## Change Vectors

- **New capability flag** (e.g., `has_yolo_confirmation`) — add to `ProviderCapabilities`, set on concrete providers, consume in handlers. No change to handlers that don't care.
- **New provider** — add a new file in `providers/`, register factory in `registry.py`. Handlers using capability flags and the provider interface work unchanged.
- **Claude tool format change** — `providers/claude.py` only. Handlers see the abstracted `AgentMessage` / `HookEvent` data types.
- **New hook event type** — add parser in `hook.py` (write-side) and `session_monitor`/`hook_events` (read-side). The `AgentProvider` protocol is unaffected unless the event needs a new parse method.
- **New mode line format** in Claude Code — touches `providers/claude.py::scrape_current_mode` only. Toolbar code unaffected.
- **Break the `providers/__init__.py → session_manager` lazy import cycle** — change `get_provider_for_window(window_id)` to `get_provider_for_window(window_id, provider_name)` and make callers pass the name from the `WindowView` they already have. Morning review recommendation; still valid.

## Refactor Plan (scope for this review)

1. Add `scrape_current_mode` to `AgentProvider` protocol with a default `return None`.
2. Move mode-scraping code (`_scrape_current_mode`, `_find_mode_line`, `_mode_short_label`) from `toolbar_callbacks.py` to `providers/claude.py`.
3. Update `toolbar_callbacks._refresh_button_label` to call `get_provider_for_window(window_id).scrape_current_mode(window_id)`.
4. Add a `has_yolo_confirmation` capability flag (or similar) and set it on `ClaudeProvider`. Replace the `provider_name == "claude"` string check in `directory_callbacks.py:593`.
5. (Optional) Break the `providers/__init__.py → session_manager` lazy import by adding a `provider_name: str | None = None` parameter to `get_provider_for_window`. When provided, skip the session lookup.

## Testability Goals

- **Unit-test `ClaudeProvider.scrape_current_mode`** with saved pane text fixtures for each mode ("Edit", "Plan", "Full", "Def"). Pure function of string → string after a mockable `tmux_manager.capture_pane`.
- **Unit-test `ProviderCapabilities`** — frozen dataclass, no logic to test directly; but capability-gated handler branches are testable with fake providers.
- **Unit-test each provider's `parse_hook_payload`** with fixture JSON.
- **Unit-test each provider's `parse_transcript_entries`** with fixture JSONL lines.
- **Unit-test `detect_provider_from_command("claude")` → `ClaudeProvider`** and the JS runtime fallback path.
- **Integration-test `get_provider_for_window`** with a synthetic `WindowState.provider_name = "codex"` — verify the correct provider instance is returned.
