# Shell Prompt Orchestrator

## Functional Responsibilities

Central coordination point for all five sites that trigger shell prompt marker
setup. Ensures the prompt marker is present before shell output capture begins,
regardless of which code path created or resumed the shell window.

The five trigger sites are: initial window creation (directory browser), provider
switch to shell, lazy recovery on command send, post-`exec bash` restoration, and
shell topic adoption for external windows.

## Encapsulated Knowledge

The orchestrator knows:

- _when_ to request marker setup (the five trigger conditions)
- _whether_ to skip setup (user chose "Skip" during the session)
- the async coordination pattern (await provider, schedule if no event loop)

It does **not** know:

- how the marker is injected (delegated to `ShellProvider.ensure_prompt_marker`)
- what the marker looks like (delegated to `ShellProvider.prompt_marker_present`)
- anything about tmux send-keys sequences or shell detection

## Subdomain Classification

**Supporting** — Shell UX evolves (new trigger sites, new skip semantics) but
the business rules it coordinates are stable. Changes here are unlikely to
cascade beyond the shell subsystem.

## Integration Contracts

### `shell_prompt_orchestrator` → `AgentProvider.ensure_prompt_marker` (calls)

- **Direction**: Orchestrator → protocol
- **Contract type**: Contract
- **What is shared**: Method signature `async def ensure_prompt_marker(window_id: str) -> None`
- **Contract definition**: Orchestrator resolves provider via
  `get_provider_for_window(window_id)` then awaits `provider.ensure_prompt_marker(window_id)`
- **Change from current**: Replaces three deferred `from ..providers.shell_infra import setup_shell_prompt` imports

### `shell_prompt_orchestrator` → `AgentProvider.prompt_marker_present` (calls)

- **Direction**: Orchestrator → protocol
- **Contract type**: Contract
- **What is shared**: Method signature `def prompt_marker_present(capture: str) -> bool`
- **Contract definition**: Orchestrator calls `provider.prompt_marker_present(capture)` to check before re-injecting
- **Change from current**: Replaces deferred `from ..providers.shell_infra import has_prompt_marker` import

### `shell_prompt_orchestrator` → `window_query` (reads skip state)

- **Direction**: Orchestrator → contract layer
- **Contract type**: Contract
- **What is shared**: `view_window(window_id)` and `WindowView.prompt_marker_skip`
- **Contract definition**: Unchanged from current

## Change Vectors

- **New trigger site for marker setup**: Add a call to `ensure_setup(window_id)`
  from the new site. No imports change.
- **Skip semantics change**: Update orchestrator logic only; providers and
  callers are unaffected.
- **Marker format change**: Handled entirely in `ShellProvider`; orchestrator
  is insulated.
