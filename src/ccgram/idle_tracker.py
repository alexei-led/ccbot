"""Per-session idle timer tracking.

Stores the last-activity monotonic timestamp for each session. Accepts only
session_id inputs — window_id→session_id resolution is the caller's
responsibility (see SessionLifecycle.record_hook_activity).

Key class: IdleTracker.
"""

import time


class IdleTracker:
    """Tracks per-session activity timestamps for idle detection."""

    def __init__(self) -> None:
        self._last_activity: dict[str, float] = {}  # session_id -> monotonic time

    def record_activity(self, session_id: str, ts: float | None = None) -> None:
        """Record that session_id was active at ts (defaults to now)."""
        self._last_activity[session_id] = ts if ts is not None else time.monotonic()

    def get_last_activity(self, session_id: str) -> float | None:
        """Return the last activity timestamp for session_id, or None."""
        return self._last_activity.get(session_id)

    def clear_session(self, session_id: str) -> None:
        """Remove tracking for session_id."""
        self._last_activity.pop(session_id, None)
