# Shell Handler Subsystem (`handlers/shell/`)

## Functional Responsibilities

A cohesive group of handler-layer modules that implement all shell-specific
behavior: output capture and prompt detection, NL→command routing and dangerous
command detection, LLM context gathering, and prompt marker orchestration.

These modules are only invoked when the active window provider is `shell`. They
form a closed subsystem with a single declared dependency on `providers.shell`
(and by re-export, `providers.shell_infra`).

Formalizing the subsystem as `handlers/shell/` makes two currently invisible
facts explicit in the directory listing:

1. These five files are a unit — changes in one often require awareness of others.
2. Their dependency on `providers.shell` is a package-level architectural decision,
   not an accidental collection of file-level imports.

## Encapsulated Knowledge

The shell subsystem owns:

- Prompt marker pattern matching (`match_prompt`, via `providers.shell` re-export)
- Output isolation — extracting command output between two prompt markers
- Exit code detection from pane capture
- Shell type detection (`detect_pane_shell`, via `providers.shell`)
- NL→command translation and dangerous-command detection
- LLM context assembly (environment, working directory, recent output)
- Prompt marker lifecycle orchestration (five trigger sites)

It does **not** own:

- The marker format itself (defined in `ShellProvider`)
- The send-keys mechanism (delegated to `ShellProvider.ensure_prompt_marker`)
- Provider resolution (delegated to `get_provider_for_window`)
- Message routing (entry points called from `text_handler` and `window_tick`)

## Subdomain Classification

**Supporting** — Shell UX is a distinguishing feature but not the core business
value (routing Telegram messages to AI agents). Shell behavior evolves but
changes are contained within the subsystem.

## Integration Contracts

### `handlers/shell/` → `providers.shell` (declared subsystem dependency)

- **Direction**: Shell handlers → shell provider implementation
- **Contract type**: Functional (intentional — these are the shell handlers)
- **What is shared**: `match_prompt`, `KNOWN_SHELLS`, `detect_pane_shell`
- **Contract definition**: Imported at the top of affected modules; explicit
  in the package `__init__.py` which lists `providers.shell` as a declared
  external dependency of this sub-package
- **Rationale**: The balance rule tolerates functional coupling at low distance.
  Shell handlers will never run for any other provider — the coupling is not
  incidental, it is load-bearing. Formalizing it at the package level makes the
  dependency auditable rather than implicit.

### `handlers/shell/` → `AgentProvider` protocol (for orchestrator)

- **Direction**: `shell_prompt_orchestrator` → protocol
- **Contract type**: Contract
- **What is shared**: `ensure_prompt_marker(window_id)`, `prompt_marker_present(capture)`
- **Contract definition**: Protocol methods on `AgentProvider`; resolved via
  `get_provider_for_window(window_id)`

### External callers → `handlers/shell/` public API

- **Direction**: `text_handler`, `window_tick`, `directory_callbacks` → subsystem
- **Contract type**: Contract (public entry points re-exported from `__init__.py`)
- **What is shared**:
  - `handle_shell_message(update, context, wid)` — NL→command routing entry point
  - `ensure_setup(window_id)` — prompt marker orchestration entry point
  - `extract_output(capture, ...)` — output isolation for passive relay
  - `is_shell_idle(capture)` — idle detection for polling cycle
- **Contract definition**: `handlers/shell/__init__.py` re-exports these four
  entry points; internal module structure is package-private

### `handlers/shell/` → `window_query` (reads window state)

- **Direction**: Shell handlers → contract read layer
- **Contract type**: Contract
- **What is shared**: `view_window(window_id)`, relevant `WindowView` fields
- **Contract definition**: Unchanged from current

## Change Vectors

- **New shell capability** (e.g., multi-turn command history): Add a module
  inside `handlers/shell/`; update `__init__.py` to re-export the new entry
  point if needed. No changes outside the sub-package.
- **Shell prompt format change**: Update `ShellProvider` (marker injection) and
  the subsystem's output isolation logic. Changes stay within `providers.shell`
  and `handlers/shell/`.
- **New provider that also uses prompt markers**: Implement `ensure_prompt_marker`
  and `prompt_marker_present` in the new provider. The shell subsystem does not
  need to change — it is shell-specific by design.
- **Removing shell provider**: Delete `handlers/shell/` and `providers.shell`.
  No shell-specific code leaks into generic handlers.
