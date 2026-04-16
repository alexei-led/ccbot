# session_query — Read-Only Session Resolution

## Functional Responsibilities

Provide read-only free functions for session resolution, decoupling handler modules from `SessionManager` for session/transcript lookups. Follows the same pattern as `window_query.py`.

Three functions:

- `resolve_session_for_window(window_id)` — find the Claude session object for a window
- `find_users_for_session(session_id)` — find which users/threads are bound to a session
- `get_recent_messages(window_id, *, start_byte, end_byte)` — read recent transcript messages

## Encapsulated Knowledge

This module knows:

- How to import and call `session_resolver` (the lazy-import pattern)
- The return types of session resolution (`ClaudeSession`, message lists)

It does NOT know about `SessionManager`, persistence, or write operations.

## Subdomain Classification

**Core** — transcript resolution and message history are central to the product's message routing and history display.

## Integration Contracts

### `session_query` -> `session_resolver`

- **Direction**: `session_query` depends on `session_resolver`
- **Contract type**: Contract coupling (read-only wrapper over `session_resolver`'s public API)
- **What is shared**: `ClaudeSession` type, message list format, byte offset protocol
- **Contract definition**: Free functions matching `session_resolver`'s method signatures

### Handlers -> `session_query`

- **Direction**: `message_routing.py`, `history.py` depend on `session_query`
- **Contract type**: Contract coupling (read-only free functions)
- **What is shared**: Session resolution results

## Change Vectors

- **New session query**: add a free function here. `SessionManager` not touched.
- **Changing session resolution internals**: only `session_resolver` changes. `session_query` adapts its wrapper if the signature changes.
- **Adding a new caller**: import `session_query` instead of `session_manager`. No facade expansion.
