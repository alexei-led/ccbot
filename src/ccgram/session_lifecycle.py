"""Session lifecycle management — single authority for all claude_task_state cleanup.

Owns the session_map diff logic: compares old vs. new session_map to detect
session changes and deleted windows. Returns a structured result so the
coordinator (SessionMonitor) can clean up its own per-session state.

Provides handle_session_end() as the single cleanup point for hook_events.py:
callers must NOT touch claude_task_state or subagent state directly.

Key class: SessionLifecycle. Module-level singleton: session_lifecycle.
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .claude_task_state import clear_subagents, claude_task_state

if TYPE_CHECKING:
    from .idle_tracker import IdleTracker

logger = structlog.get_logger()

_SessionMapError = (json.JSONDecodeError, OSError)


@dataclass
class ReconcileResult:
    """Result of a session_map reconciliation pass."""

    sessions_to_remove: set[str] = field(default_factory=set)
    new_windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_map: dict[str, dict[str, Any]] = field(default_factory=dict)


class SessionLifecycle:
    """Detects session_map changes and consolidates task-state cleanup."""

    def __init__(self) -> None:
        self._last_session_map: dict[str, dict[str, str]] = {}

    @property
    def last_session_map(self) -> dict[str, dict[str, str]]:
        return self._last_session_map

    def resolve_session_id(self, window_id: str) -> str | None:
        """Return the session_id for window_id from the last known session_map."""
        for wid, details in self._last_session_map.items():
            if wid.endswith(f":{window_id}") or wid == window_id:
                return details.get("session_id")
        return None

    def reconcile(
        self,
        current_map: dict[str, dict[str, Any]],
        idle_tracker: IdleTracker,
    ) -> ReconcileResult:
        """Diff current_map against last known map; clean up stale sessions.

        Calls claude_task_state.clear_window() for changed/deleted windows.
        Returns sessions to remove and new windows so the coordinator can
        clean up its own per-session state dicts.
        """
        result = ReconcileResult(current_map=current_map)

        old_windows = set(self._last_session_map.keys())
        current_windows = set(current_map.keys())

        # Session changed: window in both maps but session_id differs
        for window_id, old_details in self._last_session_map.items():
            new_details = current_map.get(window_id)
            if new_details and new_details["session_id"] != old_details["session_id"]:
                logger.info(
                    "Window '%s' session changed: %s -> %s",
                    window_id,
                    old_details["session_id"],
                    new_details["session_id"],
                )
                result.sessions_to_remove.add(old_details["session_id"])
                idle_tracker.clear_session(old_details["session_id"])
                claude_task_state.clear_window(window_id)

        # Deleted: window in old map but not current
        for window_id in old_windows - current_windows:
            old_sid = self._last_session_map[window_id]["session_id"]
            logger.info(
                "Window '%s' deleted, removing session %s",
                window_id,
                old_sid,
            )
            result.sessions_to_remove.add(old_sid)
            idle_tracker.clear_session(old_sid)
            claude_task_state.clear_window(window_id)

        # New windows
        for window_id in current_windows - old_windows:
            result.new_windows[window_id] = current_map[window_id]

        self._last_session_map = current_map
        return result

    def handle_session_end(self, window_id: str) -> None:
        """Called by hook_events on SessionEnd — clears all task and subagent state."""
        claude_task_state.clear_window(window_id)
        clear_subagents(window_id)

    def initialize(self, session_map: dict[str, dict[str, str]]) -> None:
        """Set initial session_map (called once at monitor startup)."""
        self._last_session_map = session_map


session_lifecycle = SessionLifecycle()
