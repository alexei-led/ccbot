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
from typing import Any, Literal, Self

from .state_persistence import unwired_save

logger = structlog.get_logger()

APPROVAL_MODES: frozenset[str] = frozenset({"normal", "yolo"})
DEFAULT_APPROVAL_MODE = "normal"
YOLO_APPROVAL_MODE = "yolo"

BATCH_MODES: frozenset[str] = frozenset({"batched", "verbose"})
DEFAULT_BATCH_MODE = "batched"

NOTIFICATION_MODES: tuple[str, ...] = ("all", "errors_only", "muted")

TOOL_CALL_VISIBILITY_MODES: tuple[str, ...] = ("default", "shown", "hidden")
DEFAULT_TOOL_CALL_VISIBILITY: str = "default"

WINDOW_ORIGINS: frozenset[str] = frozenset(
    {"manual_discovered", "ccgram_created", "external"}
)
DEFAULT_WINDOW_ORIGIN = "manual_discovered"
CCGRAM_CREATED_WINDOW_ORIGIN = "ccgram_created"
MANUAL_DISCOVERED_WINDOW_ORIGIN = "manual_discovered"
EXTERNAL_WINDOW_ORIGIN = "external"

PaneState = Literal["active", "idle", "blocked", "dead"]
PANE_STATES: frozenset[str] = frozenset({"active", "idle", "blocked", "dead"})
DEFAULT_PANE_STATE: PaneState = "idle"


class _Sentinel:
    """Marker for "argument not provided" — distinct from ``None``."""

    __slots__ = ()


_SENTINEL = _Sentinel()


@dataclass
class PaneInfo:
    """Per-pane runtime state inside a tmux window.

    Attributes:
        pane_id: tmux pane id (e.g. ``%5``); unique within a tmux server.
        name: User-supplied pane name (None if never renamed).
        provider: Detected provider name for the pane (claude/codex/.../shell).
        last_active_ts: Unix timestamp of last detected activity.
        state: Current pane state — active/idle/blocked/dead.
        subscribed: Forward output of this pane to the bound topic when True.
    """

    pane_id: str
    name: str | None = None
    provider: str = ""
    last_active_ts: float = 0.0
    state: PaneState = DEFAULT_PANE_STATE
    subscribed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"pane_id": self.pane_id}
        if self.name is not None:
            d["name"] = self.name
        if self.provider:
            d["provider"] = self.provider
        if self.last_active_ts:
            d["last_active_ts"] = self.last_active_ts
        if self.state != DEFAULT_PANE_STATE:
            d["state"] = self.state
        if self.subscribed:
            d["subscribed"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        raw_state = data.get("state", DEFAULT_PANE_STATE)
        state: PaneState = raw_state if raw_state in PANE_STATES else DEFAULT_PANE_STATE
        return cls(
            pane_id=data.get("pane_id", ""),
            name=data.get("name"),
            provider=data.get("provider", ""),
            last_active_ts=float(data.get("last_active_ts", 0.0) or 0.0),
            state=state,
            subscribed=bool(data.get("subscribed", False)),
        )


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
        tool_call_visibility: "default" | "shown" | "hidden"
        external: True for windows owned by external tools (emdash) — never killed by ccgram
        origin: Lifecycle origin. Manual/external windows are never auto-killed by ccgram.
        panes: Per-pane runtime state, keyed by tmux pane id (e.g. ``%5``).
        pane_lifecycle_notify: Per-window override for pane created/closed
            notifications. ``None`` means "use the global config default".
    """

    session_id: str = ""
    cwd: str = ""
    window_name: str = ""
    transcript_path: str = ""
    notification_mode: str = "all"
    provider_name: str = ""
    approval_mode: str = DEFAULT_APPROVAL_MODE
    batch_mode: str = DEFAULT_BATCH_MODE
    tool_call_visibility: str = DEFAULT_TOOL_CALL_VISIBILITY
    external: bool = False
    origin: str = DEFAULT_WINDOW_ORIGIN
    panes: dict[str, PaneInfo] = field(default_factory=dict)
    pane_lifecycle_notify: bool | None = None

    def to_dict(self) -> dict[str, Any]:  # noqa: C901
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
        if self.tool_call_visibility != DEFAULT_TOOL_CALL_VISIBILITY:
            d["tool_call_visibility"] = self.tool_call_visibility
        if self.external:
            d["external"] = True
        if self.origin != DEFAULT_WINDOW_ORIGIN:
            d["origin"] = self.origin
        if self.panes:
            d["panes"] = {pid: p.to_dict() for pid, p in self.panes.items()}
        if self.pane_lifecycle_notify is not None:
            d["pane_lifecycle_notify"] = self.pane_lifecycle_notify
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:  # noqa: C901
        raw_panes = data.get("panes") or {}
        panes: dict[str, PaneInfo] = {}
        if isinstance(raw_panes, dict):
            for pid, pdata in raw_panes.items():
                if not isinstance(pdata, dict):
                    continue
                pane = PaneInfo.from_dict(
                    {**pdata, "pane_id": pdata.get("pane_id", pid)}
                )
                panes[pid] = pane
        return cls(
            session_id=data.get("session_id", ""),
            cwd=data.get("cwd", ""),
            window_name=data.get("window_name", ""),
            transcript_path=data.get("transcript_path", ""),
            notification_mode=data.get("notification_mode", "all"),
            provider_name=data.get("provider_name", ""),
            approval_mode=data.get("approval_mode", DEFAULT_APPROVAL_MODE),
            batch_mode=data.get("batch_mode", DEFAULT_BATCH_MODE),
            tool_call_visibility=data.get(
                "tool_call_visibility", DEFAULT_TOOL_CALL_VISIBILITY
            ),
            external=data.get("external", False),
            origin=(
                data.get("origin", DEFAULT_WINDOW_ORIGIN)
                if data.get("origin", DEFAULT_WINDOW_ORIGIN) in WINDOW_ORIGINS
                else DEFAULT_WINDOW_ORIGIN
            ),
            panes=panes,
            pane_lifecycle_notify=data.get("pane_lifecycle_notify"),
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

    def set_window_origin(self, window_id: str, origin: str) -> None:
        """Set the lifecycle origin for a window."""
        if origin not in WINDOW_ORIGINS:
            raise ValueError(f"Invalid window origin: {origin!r}")
        state = self.get_window_state(window_id)
        if state.origin == origin:
            return
        state.origin = origin
        if origin == EXTERNAL_WINDOW_ORIGIN:
            state.external = True
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

    def has_window(self, window_id: str) -> bool:
        """Return True if window_id has a tracked state entry."""
        return window_id in self.window_states

    def iter_window_ids(self) -> list[str]:
        """Return all tracked window IDs as a snapshot list."""
        return list(self.window_states)

    def remove_window(self, window_id: str) -> bool:
        """Remove window state entry and schedule persistence.

        Returns True if the entry existed and was removed.
        """
        if window_id not in self.window_states:
            return False
        del self.window_states[window_id]
        self._schedule_save()
        return True

    # ------------------------------------------------------------------
    # Pane management
    # ------------------------------------------------------------------

    def get_pane(self, window_id: str, pane_id: str) -> PaneInfo | None:
        """Return the PaneInfo for a window/pane pair, or None if missing."""
        state = self.window_states.get(window_id)
        if state is None:
            return None
        return state.panes.get(pane_id)

    def upsert_pane(
        self,
        window_id: str,
        pane_id: str,
        *,
        name: str | None | _Sentinel = _SENTINEL,
        provider: str | None = None,
        last_active_ts: float | None = None,
        state: PaneState | None = None,
        subscribed: bool | None = None,
    ) -> PaneInfo:
        """Create or update a PaneInfo entry and schedule a save.

        Only fields that are explicitly passed are mutated; this lets callers
        update one attribute without clobbering the rest. ``name`` accepts
        ``None`` as a real value (clearing the name), so a sentinel is used to
        distinguish "not provided" from "set to None".
        """
        window_state = self.get_window_state(window_id)
        pane = window_state.panes.get(pane_id)
        if pane is None:
            pane = PaneInfo(pane_id=pane_id)
            window_state.panes[pane_id] = pane
        if not isinstance(name, _Sentinel):
            pane.name = name
        if provider is not None:
            pane.provider = provider
        if last_active_ts is not None:
            pane.last_active_ts = last_active_ts
        if state is not None:
            if state not in PANE_STATES:
                raise ValueError(f"Invalid pane state: {state!r}")
            pane.state = state
        if subscribed is not None:
            pane.subscribed = subscribed
        self._schedule_save()
        return pane

    def remove_pane(self, window_id: str, pane_id: str) -> bool:
        """Remove a pane entry. Returns True if the entry existed."""
        state = self.window_states.get(window_id)
        if state is None or pane_id not in state.panes:
            return False
        del state.panes[pane_id]
        self._schedule_save()
        return True

    def get_pane_lifecycle_notify(self, window_id: str, default: bool) -> bool:
        """Effective pane lifecycle notification setting for a window.

        Returns the per-window override when set, otherwise ``default``
        (typically the global config flag).
        """
        state = self.window_states.get(window_id)
        if state is None or state.pane_lifecycle_notify is None:
            return default
        return state.pane_lifecycle_notify

    def set_pane_lifecycle_notify(self, window_id: str, value: bool | None) -> None:
        """Persist the per-window pane lifecycle notification override.

        Pass ``None`` to clear the override and fall back to the global default.
        """
        state = self.get_window_state(window_id)
        if state.pane_lifecycle_notify == value:
            return
        state.pane_lifecycle_notify = value
        self._schedule_save()

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def set_window_provider(
        self,
        window_id: str,
        provider_name: str,
        *,
        cwd: str | None = None,
        new_provider_supports_hook: bool = True,
    ) -> None:
        """Set the provider for a window. Empty string resets to config default.

        Always saves state unconditionally. When *cwd* is provided, persists it
        in the same write so provider/cwd updates stay atomic.

        When switching to a hookless provider (e.g. shell), invokes the
        ``_on_hookless_provider_switch`` callback so the caller can clear the
        stale session_map.json entry without a circular import.

        ``new_provider_supports_hook`` must be resolved by the caller (e.g.
        via ``registry.get(provider_name).capabilities.supports_hook``) so
        this layer stays free of provider imports.
        """
        state = self.get_window_state(window_id)
        old_provider = state.provider_name
        state.provider_name = provider_name
        if cwd:
            state.cwd = cwd

        # Guards: (1) only on real provider change, (2) only when non-empty
        # (empty string is a reset-to-default and must NOT trigger cleanup),
        # (3) only for hookless providers. Session fields are cleared only when
        # set, but the hookless-switch callback is always invoked for hookless.
        if (
            old_provider != provider_name
            and provider_name
            and not new_provider_supports_hook
        ):
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
    # Tool-call visibility
    # ------------------------------------------------------------------

    _TOOL_CALL_VISIBILITY_MODES = TOOL_CALL_VISIBILITY_MODES

    def get_tool_call_visibility(self, window_id: str) -> str:
        """Get tool-call visibility for a window (default: 'default')."""
        state = self.window_states.get(window_id)
        return state.tool_call_visibility if state else DEFAULT_TOOL_CALL_VISIBILITY

    def set_tool_call_visibility(self, window_id: str, mode: str) -> None:
        """Set tool-call visibility for a window."""
        if mode not in self._TOOL_CALL_VISIBILITY_MODES:
            raise ValueError(f"Invalid tool_call_visibility: {mode!r}")
        state = self.get_window_state(window_id)
        if state.tool_call_visibility != mode:
            state.tool_call_visibility = mode
            self._schedule_save()

    def cycle_tool_call_visibility(self, window_id: str) -> str:
        """Cycle tool-call visibility: default → shown → hidden → default. Returns new mode."""
        current = self.get_tool_call_visibility(window_id)
        modes = self._TOOL_CALL_VISIBILITY_MODES
        idx = modes.index(current) if current in modes else 0
        new_mode = modes[(idx + 1) % len(modes)]
        self.set_tool_call_visibility(window_id, new_mode)
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
