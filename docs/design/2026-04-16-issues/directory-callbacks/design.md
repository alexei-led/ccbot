# Directory Callbacks — Provider Detection Cleanup

## Functional Responsibilities

Handles the inline keyboard callbacks for the directory browser: directory
navigation, provider selection, and window creation. The provider selection
step determines whether the chosen command is a shell binary, and if so,
auto-configures the prompt marker on creation.

## Encapsulated Knowledge

The module knows the directory browser state machine and the callbacks that
advance it. It does not need to know which specific binary names constitute
shell executables — that knowledge belongs in the provider layer.

## Subdomain Classification

**Supporting** — UI flow for a specific bot command. Changes when new providers
are added or directory browser UX evolves.

## Integration Contracts

### `directory_callbacks` → `providers.__init__.detect_provider_from_command` (calls)

- **Direction**: Handler → provider detection API
- **Contract type**: Contract
- **What is shared**: Function signature `detect_provider_from_command(basename: str) -> str | None`
- **Contract definition**: Returns `"shell"` if the command is a known shell binary, otherwise a provider name or `None`
- **Change from current**: Replaces `from ccgram.providers.shell import KNOWN_SHELLS` + set membership check

**Before:**

```python
from ccgram.providers.shell import KNOWN_SHELLS
...
if cmd in KNOWN_SHELLS:
    # treat as shell
```

**After:**

```python
from ccgram.providers import detect_provider_from_command
...
if detect_provider_from_command(cmd) == "shell":
    # treat as shell
```

The behavior is identical — `detect_provider_from_command` already checks
`KNOWN_SHELLS` internally — but the caller no longer reaches into the provider
implementation to do the check itself.

## Change Vectors

- **New shell binary added** (e.g., `nu`, `elvish`): Update `KNOWN_SHELLS` in
  `providers.shell_infra` only. `directory_callbacks` picks up the change
  automatically through `detect_provider_from_command`.
- **New provider type recognized in directory browser**: Update
  `detect_provider_from_command` in `providers/__init__.py`. Directory callbacks
  unchanged.
