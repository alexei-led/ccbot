"""Tests for src/ccgram/handlers/send_callbacks.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import CallbackQuery, InlineKeyboardMarkup, Message, Update, User

import pytest

from ccgram.handlers.callback_data import (
    CB_SEND_CANCEL,
    CB_SEND_DIR,
    CB_SEND_FILE,
    CB_SEND_PAGE,
    CB_SEND_UP,
)
from ccgram.handlers.send_callbacks import _dispatch
from ccgram.handlers.user_state import (
    SEND_CWD_KEY,
    SEND_ITEMS_KEY,
    SEND_PAGE_KEY,
    SEND_PATH_KEY,
    SEND_WINDOW_ID_KEY,
)


@pytest.fixture(autouse=True)
def _allow_all_users():
    with patch("ccgram.config.config.is_user_allowed", return_value=True):
        yield


def _make_query(data: str, user_id: int = 789, thread_id: int = 456) -> AsyncMock:
    msg = AsyncMock(spec=Message)
    msg.chat_id = 123
    msg.message_thread_id = thread_id

    query = AsyncMock(spec=CallbackQuery)
    query.data = data
    query.message = msg
    query.from_user = MagicMock(spec=User)
    query.from_user.id = user_id
    return query


def _make_update(
    query: AsyncMock, user_id: int = 789, thread_id: int = 456
) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = user_id

    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = user
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = thread_id
    return update


def _make_context(tmp_path: Path, window_id: str = "@0") -> MagicMock:
    ctx = MagicMock()
    ctx.bot = AsyncMock()
    ctx.user_data = {
        SEND_ITEMS_KEY: [tmp_path / "file.txt", tmp_path / "subdir"],
        SEND_PATH_KEY: str(tmp_path),
        SEND_CWD_KEY: str(tmp_path),
        SEND_WINDOW_ID_KEY: window_id,
        SEND_PAGE_KEY: 0,
    }
    return ctx


_BROWSER_RESULT = (
    "Browse /tmp/test",
    MagicMock(spec=InlineKeyboardMarkup),
    [Path("/tmp/test/a.txt")],
)


class TestStaleGuard:
    async def test_no_thread_id_answers_error(self, tmp_path: Path) -> None:
        query = _make_query(CB_SEND_CANCEL)
        update = _make_update(query, thread_id=456)
        update.effective_message.message_thread_id = None
        ctx = _make_context(tmp_path)

        with patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=None):
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Not in a topic", show_alert=True)

    async def test_window_mismatch_clears_state_and_alerts(
        self, tmp_path: Path
    ) -> None:
        query = _make_query(CB_SEND_CANCEL)
        update = _make_update(query)
        ctx = _make_context(tmp_path, window_id="@0")

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@99"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with(
            "Browser expired — use /send to restart", show_alert=True
        )
        assert SEND_WINDOW_ID_KEY not in ctx.user_data

    async def test_matching_window_proceeds(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("hello")
        query = _make_query(CB_SEND_CANCEL)
        update = _make_update(query)
        ctx = _make_context(tmp_path)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Cancelled")


class TestHandleFile:
    async def test_valid_file_uploads_and_clears_state(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("data")
        query = _make_query(f"{CB_SEND_FILE}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [f]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.validate_sendable", return_value=None
            ),
            patch(
                "ccgram.handlers.send_callbacks.upload_file", new_callable=AsyncMock
            ) as mock_upload,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            mock_router.resolve_chat_id.return_value = 123
            await _dispatch(update, ctx)

        mock_upload.assert_awaited_once()
        # Toast replaced with persistent ✅ reaction on the uploaded file.
        query.answer.assert_awaited_once_with()
        assert SEND_WINDOW_ID_KEY not in ctx.user_data
        query.message.delete.assert_awaited_once()

    async def test_upload_success_reacts_on_uploaded_message(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "report.txt"
        f.write_text("data")
        query = _make_query(f"{CB_SEND_FILE}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [f]

        sent_msg = MagicMock()
        sent_msg.chat_id = 123
        sent_msg.message_id = 8800

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.validate_sendable", return_value=None
            ),
            patch(
                "ccgram.handlers.send_callbacks.upload_file",
                new_callable=AsyncMock,
                return_value=sent_msg,
            ),
            patch(
                "ccgram.handlers.send_callbacks.react", new_callable=AsyncMock
            ) as mock_react,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            mock_router.resolve_chat_id.return_value = 123
            await _dispatch(update, ctx)

        mock_react.assert_awaited_once()
        args = mock_react.call_args.args
        assert args[1] == 123
        assert args[2] == 8800
        from ccgram.handlers.reactions import REACT_DONE

        assert args[3] == REACT_DONE

    async def test_upload_returns_none_skips_reaction(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("data")
        query = _make_query(f"{CB_SEND_FILE}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [f]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.validate_sendable", return_value=None
            ),
            patch(
                "ccgram.handlers.send_callbacks.upload_file",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "ccgram.handlers.send_callbacks.react", new_callable=AsyncMock
            ) as mock_react,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            mock_router.resolve_chat_id.return_value = 123
            await _dispatch(update, ctx)

        mock_react.assert_not_awaited()

    async def test_denied_file_shows_error(self, tmp_path: Path) -> None:
        f = tmp_path / "secret.txt"
        f.write_text("x")
        query = _make_query(f"{CB_SEND_FILE}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [f]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.validate_sendable",
                return_value="access denied",
            ),
            patch(
                "ccgram.handlers.send_callbacks.upload_file", new_callable=AsyncMock
            ) as mock_upload,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        mock_upload.assert_not_awaited()
        query.answer.assert_awaited_once_with(
            "Cannot send: access denied", show_alert=True
        )

    async def test_out_of_bounds_index_shows_error(self, tmp_path: Path) -> None:
        query = _make_query(f"{CB_SEND_FILE}99")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [tmp_path / "file.txt"]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Item not found", show_alert=True)

    async def test_invalid_index_shows_error(self, tmp_path: Path) -> None:
        query = _make_query(f"{CB_SEND_FILE}notanint")
        update = _make_update(query)
        ctx = _make_context(tmp_path)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Invalid selection")


class TestHandleDir:
    async def test_valid_dir_builds_browser_and_edits_message(
        self, tmp_path: Path
    ) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        query = _make_query(f"{CB_SEND_DIR}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [subdir]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.is_path_contained", return_value=True
            ),
            patch(
                "ccgram.handlers.send_callbacks.build_file_browser",
                return_value=_BROWSER_RESULT,
            ) as mock_browser,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        mock_browser.assert_called_once_with(subdir, Path(str(tmp_path)), 0)
        query.message.edit_text.assert_awaited_once()
        assert ctx.user_data[SEND_PATH_KEY] == str(subdir)
        assert ctx.user_data[SEND_PAGE_KEY] == 0

    async def test_dir_outside_cwd_shows_error(self, tmp_path: Path) -> None:
        evil_dir = Path("/tmp/evil")
        query = _make_query(f"{CB_SEND_DIR}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = [evil_dir]

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.is_path_contained", return_value=False
            ),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with(
            "Directory is outside project root", show_alert=True
        )

    async def test_out_of_bounds_dir_index_shows_error(self, tmp_path: Path) -> None:
        query = _make_query(f"{CB_SEND_DIR}5")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_ITEMS_KEY] = []

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Item not found", show_alert=True)


class TestHandlePage:
    async def test_valid_page_rebuilds_browser(self, tmp_path: Path) -> None:
        query = _make_query(f"{CB_SEND_PAGE}2")
        update = _make_update(query)
        ctx = _make_context(tmp_path)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.build_file_browser",
                return_value=_BROWSER_RESULT,
            ) as mock_browser,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        mock_browser.assert_called_once_with(
            Path(str(tmp_path)), Path(str(tmp_path)), 2
        )
        assert ctx.user_data[SEND_PAGE_KEY] == 2
        query.message.edit_text.assert_awaited_once()

    async def test_missing_path_shows_error(self, tmp_path: Path) -> None:
        query = _make_query(f"{CB_SEND_PAGE}0")
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_PATH_KEY] = ""

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Browser state lost", show_alert=True)


class TestHandleUp:
    async def test_at_cwd_answers_already_at_root(self, tmp_path: Path) -> None:
        query = _make_query(CB_SEND_UP)
        update = _make_update(query)
        ctx = _make_context(tmp_path)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Already at project root")

    async def test_below_cwd_navigates_parent(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        query = _make_query(CB_SEND_UP)
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_PATH_KEY] = str(subdir)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
            patch(
                "ccgram.handlers.send_callbacks.is_path_contained", return_value=True
            ),
            patch(
                "ccgram.handlers.send_callbacks.build_file_browser",
                return_value=_BROWSER_RESULT,
            ) as mock_browser,
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        mock_browser.assert_called_once_with(tmp_path, Path(str(tmp_path)), 0)
        assert ctx.user_data[SEND_PATH_KEY] == str(tmp_path)

    async def test_missing_state_shows_error(self, tmp_path: Path) -> None:
        query = _make_query(CB_SEND_UP)
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        ctx.user_data[SEND_PATH_KEY] = ""

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Browser state lost", show_alert=True)


class TestHandleCancel:
    async def test_cancel_clears_state_and_deletes_message(
        self, tmp_path: Path
    ) -> None:
        query = _make_query(CB_SEND_CANCEL)
        update = _make_update(query)
        ctx = _make_context(tmp_path)

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.answer.assert_awaited_once_with("Cancelled")
        query.message.delete.assert_awaited_once()
        assert SEND_WINDOW_ID_KEY not in ctx.user_data
        assert SEND_ITEMS_KEY not in ctx.user_data

    async def test_cancel_edits_on_delete_failure(self, tmp_path: Path) -> None:
        from telegram.error import TelegramError

        query = _make_query(CB_SEND_CANCEL)
        update = _make_update(query)
        ctx = _make_context(tmp_path)
        query.message.delete.side_effect = TelegramError("gone")

        with (
            patch("ccgram.handlers.send_callbacks.thread_router") as mock_router,
            patch("ccgram.handlers.send_callbacks.get_thread_id", return_value=456),
        ):
            mock_router.resolve_window_for_thread.return_value = "@0"
            await _dispatch(update, ctx)

        query.message.edit_text.assert_awaited_once_with("Cancelled")
