# AgentProvider Protocol — Prompt Marker Extension

## Functional Responsibilities

Define the stable contract through which generic handler code (specifically
`shell_prompt_orchestrator`) requests and verifies shell prompt marker setup
without importing any shell provider implementation detail.

The two new protocol methods close the last pathway by which a handler reaches
past the `AgentProvider` abstraction into `providers/shell_infra.py`.

## Encapsulated Knowledge

Only the `ShellProvider` implementation knows:

- the marker format injected by `setup_shell_prompt()`
- the tmux send-keys sequence required to inject it
- how to detect whether a captured pane contains the marker

The protocol surface exposes only the _intent_ (ensure the marker; check if
present) — not the mechanism.

## Side-Effect Contract

The existing `AgentProvider` docstring states providers are "stateless — they
receive input and return results without side effects." `ensure_prompt_marker`
breaks this: it performs tmux `send_keys` (a side effect on the external tmux
session).

The docstring must be updated to distinguish:

- **Query methods** (stateless): `parse_transcript_line`, `parse_terminal_status`,
  `prompt_marker_present`, etc.
- **Setup methods** (intentionally side-effectful): `ensure_prompt_marker` is the
  only one; it mutates external shell state.

For testability, `ShellProvider.ensure_prompt_marker` must accept injectable
`capture_fn` and `inject_fn` parameters (keyword-only, defaulting to the real
tmux implementations), consistent with the existing pattern in
`shell_infra.setup_shell_prompt`. The protocol signature does not carry these
parameters — injection is an implementation concern of `ShellProvider`, not a
protocol contract.

## Subdomain Classification

**Core** — The provider protocol is the primary abstraction boundary in the
system. Changes to it affect every provider implementation and every caller.
Protocol stability directly determines how expensive it is to add a new provider.

## Integration Contracts

### `AgentProvider` → `ShellProvider` (implements)

- **Direction**: `ShellProvider` satisfies the extended `AgentProvider` protocol
- **Contract type**: Contract
- **What is shared**: Two async/sync method signatures; no shared state
- **Contract definition**:

```python
async def ensure_prompt_marker(self, window_id: str) -> None:
    """Ensure the shell prompt marker is present in window_id.

    Inject the marker via send_keys if not already detected.
    No-op for providers that do not use a prompt marker.
    """

def prompt_marker_present(self, capture: str) -> bool:
    """Return True if capture contains a prompt marker line.

    For non-shell providers always returns True (no marker expected).
    For ShellProvider returns True iff match_prompt detects the marker.
    """
```

### `AgentProvider` → non-shell providers (default no-op)

- **Direction**: `base.py` supplies default implementations
- **Contract type**: Contract
- **What is shared**: Default `ensure_prompt_marker` is a no-op coroutine;
  default `prompt_marker_present` returns `True`
- **Contract definition**: implemented in `base.py` as protocol defaults

### `shell_prompt_orchestrator` → `AgentProvider` (calls)

- **Direction**: Orchestrator calls the two protocol methods
- **Contract type**: Contract (through protocol)
- **What is shared**: Method signatures only; no shell internals exposed
- **Contract definition**: orchestrator resolves provider via
  `get_provider_for_window(window_id)` and calls methods on the returned
  `AgentProvider` instance

## Change Vectors

- **New provider with prompt marker**: Implement `ensure_prompt_marker` and
  `prompt_marker_present` in the new provider. Zero handler changes.
- **Shell marker format change**: Update `ShellProvider` implementation only.
  The orchestrator and all callers are insulated.
- **Additional prompt-marker entry points**: Each new caller gets the same
  two-method contract; no import path changes needed.
