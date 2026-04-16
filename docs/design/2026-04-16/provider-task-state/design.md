# Provider Task State Abstraction

## Functional Responsibilities

Close the Claude-specific leak in `transcript_reader.py` by adding task-state tracking to the `AgentProvider` protocol. After this change, `transcript_reader.py` never checks `provider.capabilities.name` — it uses capability flags and protocol methods exclusively.

## Encapsulated Knowledge

Each provider encapsulates its own task-state tracking logic:

- `ClaudeProvider` knows about `claude_task_state`, task snapshots, and how to seed/apply task entries from JSONL transcripts
- Other providers return no-ops — they don't have task-state models (yet)
- `transcript_reader.py` knows only that some providers support task tracking via `capabilities.supports_task_tracking`

## Subdomain Classification

**Supporting** — task-state tracking is Claude-specific UX (live task list in Telegram status bubble). Not a competitive differentiator. Low volatility — the Claude task-state model is stable and rarely changes.

The **provider protocol** itself is **Core** — it's the abstraction boundary that enables multi-agent CLI support.

## Changes

### 1. Add capability flag to `ProviderCapabilities`

In `providers/base.py`:

```python
@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    # ... existing fields ...
    supports_task_tracking: bool = False  # NEW
```

Set to `True` only in `ClaudeProvider.capabilities`.

### 2. Add protocol methods with default implementations

In `providers/base.py`, add to `AgentProvider`:

```python
async def seed_task_state(
    self,
    window_id: str,
    session_id: str,
    transcript_path: str,
) -> None:
    """Seed task tracking state from transcript on session start.

    Called once when a new session is discovered, before incremental
    entry processing begins. Default: no-op.
    """

def apply_task_entries(
    self,
    window_id: str,
    session_id: str,
    entries: list[dict[str, Any]],
) -> None:
    """Apply parsed transcript entries to task tracking state.

    Called on each batch of new transcript entries. Default: no-op.
    """
```

These are **not** abstract — they have default no-op implementations on the Protocol itself (same pattern as the existing `scrape_current_mode`).

### 3. Implement in `ClaudeProvider`

In `providers/claude.py`:

```python
async def seed_task_state(
    self, window_id: str, session_id: str, transcript_path: str
) -> None:
    from ..claude_task_state import claude_task_state
    claude_task_state.seed_from_transcript(window_id, session_id, transcript_path)

def apply_task_entries(
    self, window_id: str, session_id: str, entries: list[dict[str, Any]]
) -> None:
    from ..claude_task_state import claude_task_state
    claude_task_state.apply_entries(window_id, session_id, entries)
```

Both use deferred imports (consistent with existing pattern in `claude.py`).

### 4. Update `transcript_reader.py`

Replace the two name-check blocks:

**Before (L127-128):**

```python
if provider.capabilities.name == "claude" and window_id:
    await self._seed_claude_task_state(window_id, session_id, file_path)
```

**After:**

```python
if provider.capabilities.supports_task_tracking and window_id:
    await provider.seed_task_state(window_id, session_id, file_path)
```

**Before (L152-153):**

```python
if provider.capabilities.name == "claude" and window_id:
    claude_task_state.apply_entries(window_id, session_id, new_entries)
```

**After:**

```python
if provider.capabilities.supports_task_tracking and window_id:
    provider.apply_task_entries(window_id, session_id, new_entries)
```

### 5. Remove `_seed_claude_task_state` from `TranscriptReader`

The private method `_seed_claude_task_state` in `transcript_reader.py` moves into `ClaudeProvider.seed_task_state`. The `claude_task_state` import in `transcript_reader.py` can be removed (it's only used for `apply_entries` at L153 and the seed method).

Check remaining `claude_task_state` imports in `transcript_reader.py` — L18 imports `claude_task_state` for the `apply_entries` call. After the refactor, `transcript_reader.py` should have **zero imports from `claude_task_state`**.

### 6. Shell abstraction leaks — accepted

The shell handler imports (`match_prompt`, `KNOWN_SHELLS`, `detect_pane_shell`, `has_prompt_marker`, `setup_shell_prompt`) are accepted as balanced coupling per the review. Shell prompt detection is a supporting subdomain with low volatility — `BALANCE = (STRENGTH XOR DISTANCE) OR NOT VOLATILITY` is satisfied by low volatility.

Document this decision in the architecture doc's "Design Decisions" section.

## Integration Contracts

### `transcript_reader` -> `AgentProvider` protocol

- **Direction**: `transcript_reader` depends on `AgentProvider`
- **Contract type**: Contract coupling (protocol methods + capability flags)
- **What is shared**: The fact that some providers have task-state tracking. The `seed_task_state` / `apply_task_entries` method signatures.
- **Contract definition**: `AgentProvider` protocol in `providers/base.py`

### `ClaudeProvider` -> `claude_task_state`

- **Direction**: `ClaudeProvider` depends on `claude_task_state`
- **Contract type**: Functional coupling (knows Claude's task-state model)
- **What is shared**: `claude_task_state.seed_from_transcript()`, `claude_task_state.apply_entries()` — Claude-specific task tracking internals
- **Why this is balanced**: High strength but low distance (same package) and low volatility (supporting subdomain). `STRENGTH XOR DISTANCE = true`.

### Shell handlers -> `providers.shell` / `providers.shell_infra`

- **Direction**: Shell handlers depend on shell provider internals
- **Contract type**: Intrusive coupling (bypasses protocol)
- **What is shared**: `match_prompt`, `KNOWN_SHELLS`, `detect_pane_shell`, `has_prompt_marker`, `setup_shell_prompt`
- **Why accepted**: Low volatility (supporting subdomain). `BALANCE = NOT VOLATILITY = true`. Accepted per review.

## Change Vectors

- **New provider with task tracking**: set `supports_task_tracking = True` in its `ProviderCapabilities`, implement `seed_task_state` and `apply_task_entries`. No changes to `transcript_reader.py`.
- **New task-state operation**: add a method to the protocol with a default no-op. Implement in providers that support it. `transcript_reader.py` gains a new call gated by `supports_task_tracking`.
- **Removing Claude task tracking**: set `supports_task_tracking = False` on `ClaudeProvider`. No changes to generic code.
