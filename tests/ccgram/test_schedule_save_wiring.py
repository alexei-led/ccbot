"""Tests for fail-loud _schedule_save defaults on persistence singletons.

The four state singletons (window_store, thread_router, user_preferences,
session_map_sync) start with a default _schedule_save callback that raises
RuntimeError when called. SessionManager.__post_init__ replaces it with the
real persistence callback. This guarantees that any test or caller that
mutates a singleton before SessionManager has been instantiated fails
loudly instead of silently dropping the save.
"""

from __future__ import annotations

import pytest

from ccgram.session_map import SessionMapSync
from ccgram.state_persistence import unwired_save
from ccgram.thread_router import ThreadRouter
from ccgram.user_preferences import UserPreferences
from ccgram.window_state_store import WindowStateStore


class TestUnwiredSave:
    def test_default_raises_with_owner_name(self) -> None:
        cb = unwired_save("MyOwner")
        with pytest.raises(RuntimeError, match="MyOwner._schedule_save was called"):
            cb()

    @pytest.mark.parametrize(
        ("singleton_factory", "owner"),
        [
            (WindowStateStore, "WindowStateStore"),
            (ThreadRouter, "ThreadRouter"),
            (UserPreferences, "UserPreferences"),
            (SessionMapSync, "SessionMapSync"),
        ],
    )
    def test_singleton_starts_with_unwired_default(
        self, singleton_factory: type, owner: str
    ) -> None:
        instance = singleton_factory()
        with pytest.raises(RuntimeError, match=f"{owner}._schedule_save was called"):
            instance._schedule_save()


class TestSessionManagerWiresAllSingletons:
    def test_post_init_replaces_unwired_defaults(self) -> None:
        # SessionManager.__post_init__ wires every singleton's _schedule_save
        # to its own _save_state. After construction, calling _schedule_save
        # on any singleton must NOT raise.
        from ccgram.session import SessionManager

        sm = SessionManager()
        # Calling these should not raise — they delegate to sm._save_state.
        # We don't assert behavior beyond "no RuntimeError" since the real
        # save path is async and depends on event loop state.
        from ccgram.session_map import session_map_sync
        from ccgram.thread_router import thread_router
        from ccgram.user_preferences import user_preferences
        from ccgram.window_state_store import window_store

        for singleton in (
            window_store,
            thread_router,
            user_preferences,
            session_map_sync,
        ):
            assert singleton._schedule_save is not None
            # Confirm it's no longer the unwired default by calling it.
            # _save_state may schedule via asyncio if a loop is running,
            # otherwise saves synchronously — either path is fine here.
            singleton._schedule_save()

        # Cleanup so the singleton state doesn't leak to other tests.
        del sm
