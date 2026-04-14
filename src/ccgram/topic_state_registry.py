"""Centralized registry for per-topic and per-window cleanup functions.

Modules register their cleanup callbacks at import time via the
``@topic_state.register(scope)`` decorator.  ``cleanup.py`` calls
``topic_state.clear_all(...)`` to dispatch all registered cleanups in a
single call, replacing 14+ lazy imports with one registry lookup.

Scopes:
  - topic: keyed by (user_id, thread_id)
  - window: keyed by window_id
  - qualified: keyed by qualified_id (e.g. "ccgram:@0")
  - chat: keyed by (chat_id, thread_id)
"""

from collections.abc import Callable

import structlog

logger = structlog.get_logger()

_VALID_SCOPES = frozenset({"topic", "window", "qualified", "chat"})


class TopicStateRegistry:
    """Registry for per-topic / per-window cleanup functions."""

    def __init__(self) -> None:
        self._cleanups: dict[str, list[Callable[..., None]]] = {
            s: [] for s in _VALID_SCOPES
        }

    def register(
        self, scope: str
    ) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """Decorator that registers a cleanup function under *scope*.

        Deduplicates: the same function object is stored at most once per scope.

        Raises ``ValueError`` for unknown scopes.
        """
        if scope not in _VALID_SCOPES:
            msg = f"Unknown cleanup scope {scope!r}; valid: {sorted(_VALID_SCOPES)}"
            raise ValueError(msg)

        def decorator(fn: Callable) -> Callable:
            bucket = self._cleanups[scope]
            if fn not in bucket:
                bucket.append(fn)
            return fn

        return decorator

    def register_bound(self, scope: str, method: Callable[..., None]) -> None:
        """Register a bound method (or any callable) under *scope*.

        Unlike the ``register`` decorator, this accepts an already-bound method
        and stores it directly.  Intended for strategy classes that register
        cleanup in ``__init__``.
        """
        if scope not in _VALID_SCOPES:
            msg = f"Unknown cleanup scope {scope!r}; valid: {sorted(_VALID_SCOPES)}"
            raise ValueError(msg)
        bucket = self._cleanups[scope]
        if method not in bucket:
            bucket.append(method)

    def _reset_for_testing(self) -> None:
        """Clear all registered callbacks.  Only for use in tests."""
        for bucket in self._cleanups.values():
            bucket.clear()

    # -- dispatch helpers --------------------------------------------------

    def clear_topic(self, user_id: int, thread_id: int) -> None:
        for fn in self._cleanups["topic"]:
            _safe_call(fn, user_id, thread_id)

    def clear_window(self, window_id: str) -> None:
        for fn in self._cleanups["window"]:
            _safe_call(fn, window_id)

    def clear_qualified(self, qualified_id: str) -> None:
        for fn in self._cleanups["qualified"]:
            _safe_call(fn, qualified_id)

    def clear_chat(self, chat_id: int, thread_id: int) -> None:
        for fn in self._cleanups["chat"]:
            _safe_call(fn, chat_id, thread_id)

    def clear_all(
        self,
        user_id: int,
        thread_id: int,
        *,
        window_id: str | None = None,
        qualified_id: str | None = None,
        chat_id: int | None = None,
    ) -> None:
        """Dispatch all registered cleanups for a closing topic."""
        self.clear_topic(user_id, thread_id)
        if chat_id is not None:
            self.clear_chat(chat_id, thread_id)
        if window_id:
            self.clear_window(window_id)
        if qualified_id:
            self.clear_qualified(qualified_id)


def _safe_call(fn: Callable, *args: object) -> None:
    try:
        fn(*args)
    except (
        OSError,
        ValueError,
        LookupError,
        TypeError,
        RuntimeError,
        AttributeError,
        ImportError,
    ):
        name = getattr(fn, "__qualname__", repr(fn))
        logger.warning("cleanup_function_failed", fn=name, exc_info=True)


topic_state = TopicStateRegistry()
