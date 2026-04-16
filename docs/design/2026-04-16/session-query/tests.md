# session_query — Test Specification

## Unit Tests

### test_resolve_session_for_window_delegates

- **Scenario**: Call `session_query.resolve_session_for_window(wid)` with a known window
- **Expected behavior**: Returns the same `ClaudeSession` as `session_resolver.resolve_session_for_window(wid)`

### test_find_users_for_session_delegates

- **Scenario**: Call `session_query.find_users_for_session(sid)` with a known session
- **Expected behavior**: Returns the same `list[tuple[int, str, int]]` as `session_resolver.find_users_for_session(sid)`

### test_get_recent_messages_delegates

- **Scenario**: Call `session_query.get_recent_messages(wid)` with a known window
- **Expected behavior**: Returns the same `tuple[list[dict], int]` as `session_resolver.get_recent_messages(wid)`

### test_get_recent_messages_with_byte_range

- **Scenario**: Call with `start_byte=1000, end_byte=2000`
- **Expected behavior**: Parameters forwarded to `session_resolver` correctly

## Integration Contract Tests

### test_message_routing_uses_session_query

- **Scenario**: `message_routing.py` calls `session_query.find_users_for_session` and `session_query.resolve_session_for_window`
- **Expected behavior**: Import path is `from ..session_query import ...`, not `from ..session import session_manager`

### test_history_uses_session_query

- **Scenario**: `history.py` calls `session_query.get_recent_messages`
- **Expected behavior**: Import path is `from ..session_query import ...`

## Boundary Tests

### test_resolve_nonexistent_window

- **Scenario**: `session_query.resolve_session_for_window("@999")`
- **Expected behavior**: Returns `None`

### test_find_users_unknown_session

- **Scenario**: `session_query.find_users_for_session("no-such-uuid")`
- **Expected behavior**: Returns `[]`

### test_get_messages_no_transcript

- **Scenario**: `session_query.get_recent_messages("@999")` for window with no transcript
- **Expected behavior**: Returns `([], 0)`

## Behavior Tests

### test_session_query_lazy_import

- **Scenario**: Import `session_query` at module level
- **Expected behavior**: Does not trigger import of `session_resolver` until a function is actually called. Matches the existing deferred-import pattern.
