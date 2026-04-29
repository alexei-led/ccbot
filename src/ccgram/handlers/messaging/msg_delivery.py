"""Message delivery state for inter-agent messaging.

Owns the per-window delivery tracking state shared between the Message Broker
(write path) and the Messaging Telegram UI (read path for loop alert callbacks).

Key components:
  - DeliveryState: per-window delivery tracking dataclass
  - MessageDeliveryStrategy: state-owning class with rate limiting and loop detection
  - delivery_strategy: module-level singleton
  - clear_delivery_state / reset_delivery_state: cleanup helpers
"""

import time
from dataclasses import dataclass, field

from ...topic_state_registry import topic_state


# ── Constants ──────────────────────────────────────────────────────────

# Rate limiting: max messages per window per window (5 min).
_RATE_WINDOW_SECONDS = 300.0

# Loop detection: max exchanges between a pair before pausing.
_LOOP_THRESHOLD = 5

# Loop detection window (seconds).
_LOOP_WINDOW_SECONDS = 600.0


# ── Per-window delivery state ──────────────────────────────────────────


@dataclass
class DeliveryState:
    """Per-window delivery tracking state."""

    delivery_timestamps: list[float] = field(default_factory=list)
    loop_counts: dict[str, list[float]] = field(default_factory=dict)
    paused_peers: set[str] = field(default_factory=set)
    notified_shell_ids: set[str] = field(default_factory=set)


class MessageDeliveryStrategy:
    """Owns per-window delivery state for broker message injection.

    Follows the TerminalStatusStrategy pattern: state dict keyed by
    qualified window ID, get_state/clear_state, module-level singleton.
    """

    def __init__(self) -> None:
        self._states: dict[str, DeliveryState] = {}
        self._crash_recovery_done = False

    def is_crash_recovery_done(self) -> bool:
        return self._crash_recovery_done

    def mark_crash_recovery_done(self) -> None:
        self._crash_recovery_done = True

    def get_state(self, window_id: str) -> DeliveryState:
        return self._states.setdefault(window_id, DeliveryState())

    def clear_state(self, window_id: str) -> None:
        self._states.pop(window_id, None)

    def reset_all_state(self) -> None:
        self._states.clear()

    def check_rate_limit(self, window_id: str, max_rate: int) -> bool:
        """Return True if the window is within rate limits."""
        state = self.get_state(window_id)
        now = time.monotonic()
        cutoff = now - _RATE_WINDOW_SECONDS
        state.delivery_timestamps = [t for t in state.delivery_timestamps if t > cutoff]
        return len(state.delivery_timestamps) < max_rate

    def record_delivery(self, window_id: str) -> None:
        """Record a delivery timestamp for rate limiting."""
        state = self.get_state(window_id)
        state.delivery_timestamps.append(time.monotonic())

    def check_loop(self, window_a: str, window_b: str) -> bool:
        """Return True if a messaging loop is detected between two windows.

        A loop is detected when there are _LOOP_THRESHOLD or more exchanges
        between the same pair within _LOOP_WINDOW_SECONDS.
        """
        pair_key = _pair_key(window_a, window_b)
        state_a = self.get_state(window_a)
        now = time.monotonic()
        cutoff = now - _LOOP_WINDOW_SECONDS

        timestamps = state_a.loop_counts.get(pair_key, [])
        timestamps = [t for t in timestamps if t > cutoff]
        state_a.loop_counts[pair_key] = timestamps

        return len(timestamps) >= _LOOP_THRESHOLD

    def record_exchange(self, window_a: str, window_b: str) -> None:
        """Record a message exchange between two windows for loop detection.

        Records on both sides so check_loop works regardless of argument order.
        """
        pair_key = _pair_key(window_a, window_b)
        now = time.monotonic()
        for wid in (window_a, window_b):
            self.get_state(wid).loop_counts.setdefault(pair_key, []).append(now)

    def is_paused(self, window_id: str, peer_id: str) -> bool:
        """Check if delivery from peer_id to window_id is paused."""
        return peer_id in self.get_state(window_id).paused_peers

    def pause_peer(self, window_id: str, peer_id: str) -> None:
        """Pause delivery from peer_id to window_id."""
        self.get_state(window_id).paused_peers.add(peer_id)

    def unpause_peer(self, window_id: str, peer_id: str) -> None:
        """Resume delivery from peer_id to window_id."""
        self.get_state(window_id).paused_peers.discard(peer_id)

    def allow_more(self, window_a: str, window_b: str) -> None:
        """Clear loop counts and unpause to allow more exchanges."""
        pair_key = _pair_key(window_a, window_b)
        for wid in (window_a, window_b):
            state = self.get_state(wid)
            state.loop_counts.pop(pair_key, None)
            state.paused_peers.discard(window_a)
            state.paused_peers.discard(window_b)


# ── Module-level singleton ─────────────────────────────────────────────

delivery_strategy = MessageDeliveryStrategy()


@topic_state.register("qualified")
def clear_delivery_state(window_id: str) -> None:
    delivery_strategy.clear_state(window_id)


def reset_delivery_state() -> None:
    delivery_strategy.reset_all_state()


# ── Helpers ────────────────────────────────────────────────────────────


def _pair_key(a: str, b: str) -> str:
    """Canonical key for a window pair (order-independent)."""
    return f"{min(a, b)}|{max(a, b)}"
