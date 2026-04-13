"""Window state storage — per-window mode and session metadata.

Owns the WindowState dataclass and all window-scoped mode settings
(approval, batch, notification). Extracted from SessionManager so that
providers, handlers, and tests can import window state without pulling in
the full session management stack.

Key class: WindowStateStore (singleton instantiated as ``window_store``).
Key types: WindowState, APPROVAL_MODES, BATCH_MODES, NOTIFICATION_MODES.
"""

from __future__ import annotations

import structlog
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Self

from .state_persistence import unwired_save

logger = structlog.get_logger()

APPROVAL_MODES: frozenset[str] = frozenset({"normal", "yolo"})
DEFAULT_APPROVAL_MODE = "normal"
YOLO_APPROVAL_MODE = "yolo"

BATCH_MODES: frozenset[str] = frozenset({"batched", "verbose"})
DEFAULT_BATCH_MODE = "batched"

NOTIFICATION_MODES: tuple[str, ...] = ("all", "errors_only", "muted")


@dataclass
class WindowState:
    """Persistent state for a tmux window.

    Attributes:
        session_id: Associated Claude session ID (empty if not yet detected)
        cwd: Working directory for direct file path construction
        window_name: Display name of the window
        transcript_path: Direct path to JSONL transcript file (from hook payload)
        notification_mode: "all" | "errors_only" | "muted"
        provider_name: Name of the agent provider for this window
        approval_mode: "normal" | "yolo"
        batch_mode: "batched" | "verbose"
        external: True for windows owned by external tools (emdash) — never killed by ccgram
    """

    session_id: str = ""
    cwd: str = ""
    window_name: str = ""
    transcript_path: str = ""
    notification_mode: str = "all"
    provider_name: str = ""
    approval_mode: str = DEFAULT_APPROVAL_MODE
    batch_mode: str = DEFAULT_BATCH_MODE
    external: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "cwd": self.cwd,
        }
        if self.window_name:
            d["window_name"] = self.window_name
        if self.transcript_path:
            d["transcript_path"] = self.transcript_path
        if self.notification_mode != "all":
            d["notification_mode"] = self.notification_mode
        if self.provider_name:
            d["provider_name"] = self.provider_name
        if self.approval_mode != DEFAULT_APPROVAL_MODE:
            d["approval_mode"] = self.approval_mode
        if self.batch_mode != DEFAULT_BATCH_MODE:
            d["batch_mode"] = self.batch_mode
        if self.external:
            d["external"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            session_id=data.get("session_id", ""),
            cwd=data.get("cwd", ""),
            window_name=data.get("window_name", ""),
            transcript_path=data.get("transcript_path", ""),
            notification_mode=data.get("notification_mode", "all"),
            provider_name=data.get("provider_name", ""),
            approval_mode=data.get("approval_mode", DEFAULT_APPROVAL_MODE),
            batch_mode=data.get("batch_mode", DEFAULT_BATCH_MODE),
            external=data.get("external", False),
        )


@dataclass
class WindowStateStore:
    """Per-window mode and session metadata store.

    Owns the window_states dict and all methods for reading/writing
    per-window settings: notification mode, approval mode, batch mode,
    provider name, and session/cwd association.

    Persistence is delegated: the ``_schedule_save`` callback (set by
    SessionManager) triggers a debounced save after mutations.

    The ``_on_hookless_provider_switch`` callback (also set by
    SessionManager) is called when switching to a hookless provider so
    session_map.json can be cleaned up without a circular dependency.
    """

    window_states: dict[str, WindowState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._schedule_save: Callable[[], None] = unwired_save("WindowStateStore")
        self._on_hookless_provider_switch: Callable[[str], None] = lambda _wid: None

    def reset(self) -> None:
        """Clear all state. Used for test isolation."""
        self.window_states.clear()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize window_states for state.json persistence."""
        return {k: v.to_dict() for k, v in self.window_states.items()}

    def from_dict(self, data: dict[str, Any]) -> None:
        """Load window_states from state.json data."""
        self.window_states = {
            k: WindowState.from_dict(v) for k, v in data.items() if isinstance(v, dict)
        }

    # ------------------------------------------------------------------
    # Core get/create
    # ------------------------------------------------------------------

    def get_window_state(self, window_id: str) -> WindowState:
        """Get or create window state."""
        if window_id not in self.window_states:
            self.window_states[window_id] = WindowState()
        return self.window_states[window_id]

    def update_cwd(self, window_id: str, cwd: str) -> None:
        """Update CWD for a window and schedule persistence."""
        if window_id in self.window_states:
            self.window_states[window_id].cwd = cwd
            self._schedule_save()

    def clear_session_fields(self, window_id: str) -> None:
        """Clear session_id and cwd for a window (session file gone)."""
        if window_id in self.window_states:
            self.window_states[window_id].session_id = ""
            self.window_states[window_id].cwd = ""
            self._schedule_save()

    def clear_window_session(self, window_id: str) -> None:
        """Clear session association for a window (e.g., after /clear command)."""
        state = self.get_window_state(window_id)
        state.session_id = ""
        state.notification_mode = "all"
        self._schedule_save()
        logger.info("Cleared session for window_id %s", window_id)

    def get_session_id_for_window(self, window_id: str) -> str | None:
        """Look up session_id for a window from window_states."""
        state = self.window_states.get(window_id)
        return state.session_id if state and state.session_id else None

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def set_window_provider(
        self,
        window_id: str,
        provider_name: str,
        *,
        cwd: str | None = None,
    ) -> None:
        """Set the provider for a window. Empty string resets to config default.

        Always saves state unconditionally. When *cwd* is provided, persists it
        in the same write so provider/cwd updates stay atomic.

        When switching to a hookless provider (e.g. shell), invokes the
        ``_on_hookless_provider_switch`` callback so the caller can clear the
        stale session_map.json entry without a circular import.
        """
        state = self.get_window_state(window_id)
        old_provider = state.provider_name
        state.provider_name = provider_name
        if cwd:
            state.cwd = cwd

        # When switching away from a hook-based provider to a hookless one,
        # clear stale session data and notify caller to update session_map.json.
        if old_provider != provider_name and provider_name:
            from .providers import registry

            new_prov = registry.get(provider_name)
            if not new_prov.capabilities.supports_hook:
                if state.session_id:
                    state.session_id = ""
                    state.transcript_path = ""
                self._on_hookless_provider_switch(window_id)

        self._schedule_save()

    # ------------------------------------------------------------------
    # Notification mode
    # ------------------------------------------------------------------

    _NOTIFICATION_MODES = NOTIFICATION_MODES

    def get_notification_mode(self, window_id: str) -> str:
        """Get notification mode for a window (default: 'all')."""
        state = self.window_states.get(window_id)
        return state.notification_mode if state else "all"

    def set_notification_mode(self, window_id: str, mode: str) -> None:
        """Set notification mode for a window."""
        if mode not in self._NOTIFICATION_MODES:
            raise ValueError(f"Invalid notification mode: {mode!r}")
        state = self.get_window_state(window_id)
        if state.notification_mode != mode:
            state.notification_mode = mode
            self._schedule_save()

    def cycle_notification_mode(self, window_id: str) -> str:
        """Cycle notification mode: all → errors_only → muted → all. Returns new mode."""
        current = self.get_notification_mode(window_id)
        modes = self._NOTIFICATION_MODES
        idx = modes.index(current) if current in modes else 0
        new_mode = modes[(idx + 1) % len(modes)]
        self.set_notification_mode(window_id, new_mode)
        return new_mode

    # ------------------------------------------------------------------
    # Approval mode
    # ------------------------------------------------------------------

    def get_approval_mode(self, window_id: str) -> str:
        """Get approval mode for a window (default: 'normal')."""
        state = self.window_states.get(window_id)
        mode = state.approval_mode if state else DEFAULT_APPROVAL_MODE
        return mode if mode in APPROVAL_MODES else DEFAULT_APPROVAL_MODE

    def set_window_approval_mode(self, window_id: str, mode: str) -> None:
        """Set approval mode for a window."""
        normalized = mode.lower()
        if normalized not in APPROVAL_MODES:
            raise ValueError(f"Invalid approval mode: {mode!r}")
        state = self.get_window_state(window_id)
        state.approval_mode = normalized
        self._schedule_save()

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------

    def get_batch_mode(self, window_id: str) -> str:
        """Get batch mode for a window (default: 'batched')."""
        state = self.window_states.get(window_id)
        mode = state.batch_mode if state else DEFAULT_BATCH_MODE
        return mode if mode in BATCH_MODES else DEFAULT_BATCH_MODE

    def set_batch_mode(self, window_id: str, mode: str) -> None:
        """Set batch mode for a window."""
        if mode not in BATCH_MODES:
            raise ValueError(f"Invalid batch mode: {mode!r}")
        state = self.get_window_state(window_id)
        if state.batch_mode != mode:
            state.batch_mode = mode
            self._schedule_save()

    def cycle_batch_mode(self, window_id: str) -> str:
        """Toggle batch mode: batched ↔ verbose. Returns new mode."""
        current = self.get_batch_mode(window_id)
        new_mode = "verbose" if current == "batched" else "batched"
        self.set_batch_mode(window_id, new_mode)
        return new_mode

    # ------------------------------------------------------------------
    # Stale state pruning
    # ------------------------------------------------------------------

    def prune_stale_window_states(
        self,
        live_window_ids: set[str],
        session_map_wids: set[str],
        bound_window_ids: set[str],
    ) -> bool:
        """Remove window_states not in session_map, not bound, and not live.

        Returns True if any changes were made.
        """
        stale = [
            wid
            for wid in self.window_states
            if (
                wid not in session_map_wids
                and wid not in bound_window_ids
                and wid not in live_window_ids
            )
        ]
        if not stale:
            return False
        for wid in stale:
            logger.info("Pruning stale window_state: %s", wid)
            del self.window_states[wid]
        self._schedule_save()
        return True


window_store = WindowStateStore()
