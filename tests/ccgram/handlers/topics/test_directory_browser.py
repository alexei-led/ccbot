"""Tests for directory browser favorites and hidden dirs."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ccgram.handlers.callback_data import (
    CB_DIR_CANCEL,
    CB_WT_CONFIRM,
    CB_WT_EDIT_NAME,
    CB_WT_NEW,
    CB_WT_USE_CURRENT,
)
from ccgram.handlers.topics.directory_browser import (
    build_directory_browser,
    build_worktree_confirm,
    build_worktree_picker,
    get_favorites,
)
from ccgram.user_preferences import UserPreferences


@pytest.fixture
def mock_session_manager():
    with patch(
        "ccgram.handlers.topics.directory_browser.user_preferences",
        spec=UserPreferences,
    ) as mgr:
        mgr.get_user_starred.return_value = []
        mgr.get_user_mru.return_value = []
        yield mgr


class TestGetFavorites:
    def test_none_user_id_returns_empty(self) -> None:
        favorites, starred = get_favorites(None)
        assert favorites == []
        assert starred == set()

    def test_empty_when_no_favorites(self, mock_session_manager: Mock) -> None:
        favorites, starred = get_favorites(100)
        assert favorites == []
        assert starred == set()

    def test_starred_first_then_mru(
        self, tmp_path: Path, mock_session_manager: Mock
    ) -> None:
        starred_dir = str(tmp_path / "starred")
        mru_dirs = [str(tmp_path / "mru1"), str(tmp_path / "mru2")]
        for d in [starred_dir, *mru_dirs]:
            Path(d).mkdir()

        mock_session_manager.get_user_starred.return_value = [starred_dir]
        mock_session_manager.get_user_mru.return_value = mru_dirs

        favorites, starred = get_favorites(100)
        assert favorites == [starred_dir, *mru_dirs]
        assert starred == {starred_dir}

    @pytest.mark.parametrize(
        ("starred_names", "mru_names", "expected_count"),
        [
            (["exists", "missing"], [], 1),
            (["dup"], ["dup"], 1),
        ],
        ids=["filters_nonexistent", "deduplicates"],
    )
    def test_filtering(
        self,
        tmp_path: Path,
        mock_session_manager: Mock,
        starred_names: list[str],
        mru_names: list[str],
        expected_count: int,
    ) -> None:
        for name in {*starred_names, *mru_names} - {"missing"}:
            (tmp_path / name).mkdir()

        mock_session_manager.get_user_starred.return_value = [
            str(tmp_path / n) for n in starred_names
        ]
        mock_session_manager.get_user_mru.return_value = [
            str(tmp_path / n) for n in mru_names
        ]

        favorites, _starred = get_favorites(100)
        assert len(favorites) == expected_count

    def test_caps_at_five(self, tmp_path: Path, mock_session_manager: Mock) -> None:
        dirs = [tmp_path / f"dir{i}" for i in range(8)]
        for d in dirs:
            d.mkdir()

        mock_session_manager.get_user_starred.return_value = [
            str(dirs[0]),
            str(dirs[1]),
        ]
        mock_session_manager.get_user_mru.return_value = [str(d) for d in dirs[2:]]

        favorites, _starred = get_favorites(100)
        assert len(favorites) == 5

    def test_handles_oserror_on_is_dir(self, mock_session_manager: Mock) -> None:
        mock_session_manager.get_user_starred.return_value = ["/invalid/path"]

        favorites, _starred = get_favorites(100)
        assert favorites == []


class TestHiddenDirs:
    def test_hidden_dirs_excluded_by_default(
        self, tmp_path: Path, mock_session_manager: Mock
    ) -> None:
        (tmp_path / "visible").mkdir()
        (tmp_path / ".hidden").mkdir()

        with patch("ccgram.handlers.topics.directory_browser.config") as mock_cfg:
            mock_cfg.show_hidden_dirs = False
            _text, _kb, subdirs = build_directory_browser(str(tmp_path))

        assert "visible" in subdirs
        assert ".hidden" not in subdirs

    def test_hidden_dirs_shown_when_enabled(
        self, tmp_path: Path, mock_session_manager: Mock
    ) -> None:
        (tmp_path / "visible").mkdir()
        (tmp_path / ".hidden").mkdir()

        with patch("ccgram.handlers.topics.directory_browser.config") as mock_cfg:
            mock_cfg.show_hidden_dirs = True
            _text, _kb, subdirs = build_directory_browser(str(tmp_path))

        assert "visible" in subdirs
        assert ".hidden" in subdirs


def _callback_data_values(keyboard) -> list[str]:
    return [
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data is not None
    ]


class TestBuildWorktreePicker:
    def test_three_rows_one_button_each(self) -> None:
        _text, kb = build_worktree_picker("/home/u/proj", "main")
        rows = kb.inline_keyboard
        assert [len(r) for r in rows] == [1, 1, 1]

    def test_callbacks_and_branch_in_label(self) -> None:
        _text, kb = build_worktree_picker("/home/u/proj", "develop")
        values = _callback_data_values(kb)
        assert values == [CB_WT_USE_CURRENT, CB_WT_NEW, CB_DIR_CANCEL]
        use_current_label = kb.inline_keyboard[0][0].text
        assert "develop" in use_current_label

    def test_text_includes_repo_and_branch(self) -> None:
        text, _kb = build_worktree_picker("/home/u/proj", "feat/x")
        assert "/home/u/proj" in text
        assert "feat/x" in text

    def test_callback_data_within_budget(self) -> None:
        _text, kb = build_worktree_picker("/home/u/proj", "main")
        for value in _callback_data_values(kb):
            assert len(value.encode()) <= 64


class TestBuildWorktreeConfirm:
    def test_three_rows_one_button_each(self) -> None:
        _text, kb = build_worktree_confirm(
            "/home/u/proj", "ccg/feature", "/home/u/proj.worktrees/ccg-feature", False
        )
        assert [len(r) for r in kb.inline_keyboard] == [1, 1, 1]

    def test_callbacks_and_branch_in_text(self) -> None:
        text, kb = build_worktree_confirm(
            "/home/u/proj", "ccg/feature", "/home/u/proj.worktrees/ccg-feature", False
        )
        assert _callback_data_values(kb) == [
            CB_WT_CONFIRM,
            CB_WT_EDIT_NAME,
            CB_DIR_CANCEL,
        ]
        assert "ccg/feature" in text
        assert "/home/u/proj.worktrees/ccg-feature" in text

    def test_dirty_warning_shown_only_when_dirty(self) -> None:
        clean_text, _ = build_worktree_confirm(
            "/home/u/proj", "ccg/x", "/home/u/proj.worktrees/ccg-x", False
        )
        dirty_text, _ = build_worktree_confirm(
            "/home/u/proj", "ccg/x", "/home/u/proj.worktrees/ccg-x", True
        )
        assert "uncommitted" not in clean_text
        assert "uncommitted" in dirty_text

    def test_callback_data_within_budget(self) -> None:
        _text, kb = build_worktree_confirm(
            "/home/u/proj", "ccg/feature", "/home/u/proj.worktrees/ccg-feature", True
        )
        for value in _callback_data_values(kb):
            assert len(value.encode()) <= 64
