"""Tests for UserPreferences user directory favorites."""

from pathlib import Path

import pytest

from ccgram.user_preferences import UserPreferences


def _resolved(path: str) -> str:
    return str(Path(path).resolve())


@pytest.fixture
def prefs() -> UserPreferences:
    return UserPreferences(schedule_save=lambda: None)


class TestUserFavorites:
    @pytest.mark.parametrize("getter", ["get_user_starred", "get_user_mru"])
    def test_empty_default(self, prefs: UserPreferences, getter: str) -> None:
        assert getattr(prefs, getter)(100) == []

    def test_update_mru_adds_to_front(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru(100, "/home/user/proj1")
        assert prefs.get_user_mru(100) == [_resolved("/home/user/proj1")]

    def test_update_mru_dedupes(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru(100, "/tmp/proj")
        prefs.update_user_mru(100, "/tmp/other")
        prefs.update_user_mru(100, "/tmp/proj")
        assert prefs.get_user_mru(100) == [
            _resolved("/tmp/proj"),
            _resolved("/tmp/other"),
        ]

    def test_update_mru_caps_at_five(self, prefs: UserPreferences) -> None:
        for i in range(7):
            prefs.update_user_mru(100, f"/tmp/proj{i}")
        mru = prefs.get_user_mru(100)
        assert len(mru) == 5
        assert mru[0] == _resolved("/tmp/proj6")

    def test_update_mru_preserves_order(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru(100, "/tmp/a")
        prefs.update_user_mru(100, "/tmp/b")
        prefs.update_user_mru(100, "/tmp/c")
        assert prefs.get_user_mru(100) == [
            _resolved("/tmp/c"),
            _resolved("/tmp/b"),
            _resolved("/tmp/a"),
        ]

    def test_update_mru_resolves_relative_path(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru(100, "relative/proj")
        mru = prefs.get_user_mru(100)
        assert len(mru) == 1
        assert Path(mru[0]).is_absolute()
        assert mru[0] == _resolved("relative/proj")

    def test_toggle_star_adds(self, prefs: UserPreferences) -> None:
        assert prefs.toggle_user_star(100, "/tmp/proj") is True
        assert _resolved("/tmp/proj") in prefs.get_user_starred(100)

    def test_toggle_star_removes(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star(100, "/tmp/proj")
        assert prefs.toggle_user_star(100, "/tmp/proj") is False
        assert prefs.get_user_starred(100) == []

    def test_starred_multiple_paths(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star(100, "/tmp/a")
        prefs.toggle_user_star(100, "/tmp/b")
        starred = prefs.get_user_starred(100)
        assert len(starred) == 2
        assert _resolved("/tmp/a") in starred
        assert _resolved("/tmp/b") in starred

    @pytest.mark.parametrize(
        ("setup", "getter"),
        [
            ("update_user_mru", "get_user_mru"),
            ("toggle_user_star", "get_user_starred"),
        ],
    )
    def test_independent_per_user(
        self, prefs: UserPreferences, setup: str, getter: str
    ) -> None:
        getattr(prefs, setup)(100, "/tmp/user1")
        getattr(prefs, setup)(200, "/tmp/user2")
        assert getattr(prefs, getter)(100) != getattr(prefs, getter)(200)


class TestUserFavoritesPersistence:
    def test_roundtrip_via_to_dict_and_from_dict(self) -> None:
        prefs = UserPreferences(schedule_save=lambda: None)
        prefs.update_user_mru(100, "/tmp/proj1")
        prefs.toggle_user_star(100, "/tmp/proj2")
        prefs.update_user_window_offset(100, "@0", 42)

        data = prefs.to_dict()
        prefs2 = UserPreferences(schedule_save=lambda: None)
        prefs2.from_dict(data)

        assert prefs2.get_user_mru(100) == prefs.get_user_mru(100)
        assert prefs2.get_user_starred(100) == prefs.get_user_starred(100)
        assert prefs2.get_user_window_offset(100, "@0") == 42
