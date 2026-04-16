"""Read-only session resolution — free functions wrapping session_resolver.

Provides handler modules with direct access to session resolution without
importing SessionManager. Follows the same decoupling pattern as window_query.py.

Key functions:
  resolve_session_for_window: find ClaudeSession for a tmux window
  find_users_for_session: find users bound to a session
  get_recent_messages: read paginated message history
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session_resolver import ClaudeSession


async def resolve_session_for_window(window_id: str) -> "ClaudeSession | None":
    """Resolve the Claude session for a tmux window, or None if not found."""
    from .session_resolver import session_resolver

    return await session_resolver.resolve_session_for_window(window_id)


def find_users_for_session(session_id: str) -> list[tuple[int, str, int]]:
    """Return list of (user_id, window_id, thread_id) for all users bound to a session."""
    from .session_resolver import session_resolver

    return session_resolver.find_users_for_session(session_id)


async def get_recent_messages(
    window_id: str,
    *,
    start_byte: int = 0,
    end_byte: int | None = None,
) -> tuple[list[dict], int]:
    """Get user/assistant messages for a window's session.

    Returns (messages, total_count). Supports byte-range filtering.
    """
    from .session_resolver import session_resolver

    return await session_resolver.get_recent_messages(
        window_id, start_byte=start_byte, end_byte=end_byte
    )
