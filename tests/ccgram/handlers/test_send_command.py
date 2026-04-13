"""Tests for src/ccgram/handlers/send_command.py."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from ccgram.config import config
from telegram import InlineKeyboardMarkup

from ccgram.handlers.callback_data import (
    CB_SEND_CANCEL,
    CB_SEND_DIR,
    CB_SEND_FILE,
    CB_SEND_PAGE,
    CB_SEND_UP,
)
from ccgram.handlers.send_command import (
    _find_files,
    _format_file_label,
    _is_image,
    _list_directory,
    build_file_browser,
    build_search_results,
)


class TestIsImage:
    def test_png_is_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "photo.png") is True

    def test_jpg_is_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "photo.jpg") is True

    def test_jpeg_is_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "photo.jpeg") is True

    def test_gif_is_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "anim.gif") is True

    def test_webp_is_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "image.webp") is True

    def test_txt_not_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "readme.txt") is False

    def test_py_not_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "main.py") is False

    def test_pdf_not_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "report.pdf") is False

    def test_case_insensitive_png(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "PHOTO.PNG") is True

    def test_case_insensitive_jpg(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "Img.JPG") is True

    def test_no_extension_not_image(self, tmp_path: Path) -> None:
        assert _is_image(tmp_path / "Makefile") is False


class TestFindFiles:
    def _make_file(self, path: Path, content: str = "x") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_glob_pattern_matches(self, tmp_path: Path) -> None:
        self._make_file(tmp_path / "a.txt")
        self._make_file(tmp_path / "b.txt")
        self._make_file(tmp_path / "c.py")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "*.txt")
        names = {p.name for p in results}
        assert "a.txt" in names
        assert "b.txt" in names
        assert "c.py" not in names

    def test_exact_match_returned_directly(self, tmp_path: Path) -> None:
        f = self._make_file(tmp_path / "sub" / "report.txt")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "sub/report.txt")
        assert results == [f]

    def test_substring_search_fallback(self, tmp_path: Path) -> None:
        self._make_file(tmp_path / "my_report_2024.txt")
        self._make_file(tmp_path / "other.txt")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "report")
        names = {p.name for p in results}
        assert "my_report_2024.txt" in names
        assert "other.txt" not in names

    def test_depth_limit_respected(self, tmp_path: Path) -> None:
        shallow = self._make_file(tmp_path / "a" / "file.txt")
        deep = self._make_file(tmp_path / "a" / "b" / "c" / "deep.txt")
        with (
            patch("ccgram.handlers.send_command.validate_sendable", return_value=None),
            patch.object(config, "send_search_depth", 2),
        ):
            results = _find_files(tmp_path, "*.txt")
        assert shallow in results
        assert deep not in results

    def test_excluded_dirs_skipped(self, tmp_path: Path) -> None:
        normal = self._make_file(tmp_path / "src" / "module.txt")
        excluded = self._make_file(tmp_path / "node_modules" / "dep.txt")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "*.txt")
        assert normal in results
        assert excluded not in results

    def test_max_results_cap(self, tmp_path: Path) -> None:
        for i in range(10):
            self._make_file(tmp_path / f"file{i}.txt")
        with (
            patch("ccgram.handlers.send_command.validate_sendable", return_value=None),
            patch.object(config, "send_max_results", 3),
        ):
            results = _find_files(tmp_path, "*.txt")
        assert len(results) == 3

    def test_validate_sendable_filters_denied(self, tmp_path: Path) -> None:
        self._make_file(tmp_path / "allowed.txt")
        self._make_file(tmp_path / "denied.txt")

        def fake_validate(path: Path, cwd: Path) -> str | None:
            return None if path.name == "allowed.txt" else "denied"

        with patch(
            "ccgram.handlers.send_command.validate_sendable", side_effect=fake_validate
        ):
            results = _find_files(tmp_path, "*.txt")
        names = {p.name for p in results}
        assert "allowed.txt" in names
        assert "denied.txt" not in names

    def test_empty_results(self, tmp_path: Path) -> None:
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "*.xyz")
        assert results == []

    def test_sorted_by_mtime_desc(self, tmp_path: Path) -> None:
        old = self._make_file(tmp_path / "old.txt")
        new = self._make_file(tmp_path / "new.txt")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "*.txt")
        assert results[0] == new
        assert results[1] == old

    def test_glob_question_mark(self, tmp_path: Path) -> None:
        self._make_file(tmp_path / "file1.txt")
        self._make_file(tmp_path / "file2.txt")
        self._make_file(tmp_path / "other.txt")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "file?.txt")
        names = {p.name for p in results}
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "other.txt" not in names

    def test_exact_match_nonexistent_falls_back_to_substring(
        self, tmp_path: Path
    ) -> None:
        self._make_file(tmp_path / "my_notes.txt")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            results = _find_files(tmp_path, "notes")
        assert any(p.name == "my_notes.txt" for p in results)


class TestListDirectory:
    def test_dirs_and_files_separated(self, tmp_path: Path) -> None:
        (tmp_path / "subdir").mkdir()
        f = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            dirs, files = _list_directory(tmp_path, tmp_path)
        assert any(p.name == "subdir" for p in dirs)
        assert any(p.name == "file.txt" for p in files)

    def test_dirs_sorted_alphabetically(self, tmp_path: Path) -> None:
        for name in ["zebra", "alpha", "middle"]:
            (tmp_path / name).mkdir()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            dirs, _ = _list_directory(tmp_path, tmp_path)
        names = [p.name for p in dirs]
        assert names == sorted(names, key=str.lower)

    def test_files_sorted_alphabetically(self, tmp_path: Path) -> None:
        for name in ["zebra.txt", "alpha.txt", "middle.txt"]:
            (tmp_path / name).write_text("x", encoding="utf-8")
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            _, files = _list_directory(tmp_path, tmp_path)
        names = [p.name for p in files]
        assert names == sorted(names, key=str.lower)

    def test_noise_dirs_excluded(self, tmp_path: Path) -> None:
        for name in ["node_modules", "__pycache__", "src"]:
            (tmp_path / name).mkdir()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            dirs, _ = _list_directory(tmp_path, tmp_path)
        names = {p.name for p in dirs}
        assert "node_modules" not in names
        assert "__pycache__" not in names
        assert "src" in names

    def test_hidden_dirs_excluded(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "visible").mkdir()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            dirs, _ = _list_directory(tmp_path, tmp_path)
        names = {p.name for p in dirs}
        assert ".git" not in names
        assert "visible" in names

    def test_denied_files_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "allowed.txt").write_text("x", encoding="utf-8")
        (tmp_path / "secret.pem").write_text("x", encoding="utf-8")

        def fake_validate(path: Path, cwd: Path) -> str | None:
            return None if path.name == "allowed.txt" else "denied"

        with patch(
            "ccgram.handlers.send_command.validate_sendable", side_effect=fake_validate
        ):
            _, files = _list_directory(tmp_path, tmp_path)
        names = {p.name for p in files}
        assert "allowed.txt" in names
        assert "secret.pem" not in names

    def test_empty_directory(self, tmp_path: Path) -> None:
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            dirs, files = _list_directory(tmp_path, tmp_path)
        assert dirs == []
        assert files == []


class TestFormatFileLabel:
    def test_bytes_size(self, tmp_path: Path) -> None:
        f = tmp_path / "small.txt"
        f.write_bytes(b"x" * 500)
        label = _format_file_label(f, tmp_path)
        assert "500 B" in label
        assert "small.txt" in label

    def test_kb_size(self, tmp_path: Path) -> None:
        f = tmp_path / "medium.txt"
        f.write_bytes(b"x" * 2048)
        label = _format_file_label(f, tmp_path)
        assert "2.0 KB" in label

    def test_mb_size(self, tmp_path: Path) -> None:
        f = tmp_path / "large.bin"
        f.write_bytes(b"x" * (2 * 1024 * 1024))
        label = _format_file_label(f, tmp_path)
        assert "2.0 MB" in label

    def test_short_path_not_truncated(self, tmp_path: Path) -> None:
        f = tmp_path / "hi.txt"
        f.write_bytes(b"x" * 10)
        label = _format_file_label(f, tmp_path)
        assert label.startswith("hi.txt")
        assert "…" not in label

    def test_long_path_truncated_with_ellipsis(self, tmp_path: Path) -> None:
        sub = tmp_path / "very" / "long" / "nested"
        sub.mkdir(parents=True)
        f = sub / "somefile_with_a_long_name.txt"
        f.write_bytes(b"x" * 100)
        label = _format_file_label(f, tmp_path)
        assert len(label) <= 30
        assert "…" in label
        assert "KB" in label or "B" in label

    def test_size_suffix_always_preserved_when_truncated(self, tmp_path: Path) -> None:
        sub = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaa"
        sub.mkdir()
        f = sub / "bbbbbbbbbbbbbbbbbbbbbbbbbbb.txt"
        f.write_bytes(b"x" * 1024)
        label = _format_file_label(f, tmp_path)
        assert "KB" in label
        assert len(label) <= 30

    def test_relative_path_used(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        f = sub / "module.py"
        f.write_bytes(b"x" * 50)
        label = _format_file_label(f, tmp_path)
        assert label.startswith("src/module.py") or "src" in label

    def test_outside_cwd_uses_name(self, tmp_path: Path) -> None:
        other = tmp_path.parent / "other.txt"
        other.write_bytes(b"x" * 10)
        label = _format_file_label(other, tmp_path)
        assert "other.txt" in label


class TestBuildFileBrowser:
    def test_returns_tuple_of_text_markup_items(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        text, markup, items = build_file_browser(tmp_path, tmp_path, 0)
        assert isinstance(text, str)
        assert isinstance(markup, InlineKeyboardMarkup)
        assert isinstance(items, list)
        assert all(isinstance(p, Path) for p in items)

    def test_text_contains_path_indicator(self, tmp_path: Path) -> None:
        text, _, _ = build_file_browser(tmp_path, tmp_path, 0)
        assert "📂" in text

    def test_dirs_before_files_in_items(self, tmp_path: Path) -> None:
        d = tmp_path / "adir"
        d.mkdir()
        f = tmp_path / "zfile.txt"
        f.write_bytes(b"x")
        _, _, items = build_file_browser(tmp_path, tmp_path, 0)
        dir_indices = [i for i, p in enumerate(items) if p.is_dir()]
        file_indices = [i for i, p in enumerate(items) if p.is_file()]
        assert max(dir_indices) < min(file_indices)

    def test_dir_buttons_use_cb_send_dir_prefix(self, tmp_path: Path) -> None:
        d = tmp_path / "mydir"
        d.mkdir()
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any(isinstance(cb, str) and cb.startswith(CB_SEND_DIR) for cb in all_cb)

    def test_file_buttons_use_cb_send_file_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_bytes(b"data")
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any(isinstance(cb, str) and cb.startswith(CB_SEND_FILE) for cb in all_cb)

    def test_item_count_matches_dirs_plus_files(self, tmp_path: Path) -> None:
        (tmp_path / "d1").mkdir()
        (tmp_path / "d2").mkdir()
        (tmp_path / "f1.txt").write_bytes(b"a")
        (tmp_path / "f2.txt").write_bytes(b"b")
        _, _, items = build_file_browser(tmp_path, tmp_path, 0)
        assert len(items) == 4

    def test_pagination_page0_and_page1_differ(self, tmp_path: Path) -> None:
        for i in range(12):
            (tmp_path / f"file{i:02d}.txt").write_bytes(b"x")
        _, markup0, _ = build_file_browser(tmp_path, tmp_path, 0)
        _, markup1, _ = build_file_browser(tmp_path, tmp_path, 1)
        cb0 = {btn.callback_data for row in markup0.inline_keyboard for btn in row}
        cb1 = {btn.callback_data for row in markup1.inline_keyboard for btn in row}
        file_cb0 = {
            cb for cb in cb0 if isinstance(cb, str) and cb.startswith(CB_SEND_FILE)
        }
        file_cb1 = {
            cb for cb in cb1 if isinstance(cb, str) and cb.startswith(CB_SEND_FILE)
        }
        assert file_cb0 != file_cb1

    def test_pagination_indicators_present_when_multipage(self, tmp_path: Path) -> None:
        for i in range(12):
            (tmp_path / f"file{i:02d}.txt").write_bytes(b"x")
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_text = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("/" in t for t in all_text)

    def test_no_pagination_when_few_items(self, tmp_path: Path) -> None:
        (tmp_path / "only.txt").write_bytes(b"x")
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert not any(
            isinstance(cb, str) and cb.startswith(CB_SEND_PAGE) for cb in all_cb
        )

    def test_parent_button_present_when_not_at_cwd(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        _, markup, _ = build_file_browser(sub, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_UP in all_cb

    def test_parent_button_absent_when_at_cwd(self, tmp_path: Path) -> None:
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_UP not in all_cb

    def test_cancel_button_always_present(self, tmp_path: Path) -> None:
        _, markup, _ = build_file_browser(tmp_path, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_CANCEL in all_cb

    def test_cancel_present_in_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        _, markup, _ = build_file_browser(sub, tmp_path, 0)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_CANCEL in all_cb

    def test_empty_directory(self, tmp_path: Path) -> None:
        text, markup, items = build_file_browser(tmp_path, tmp_path, 0)
        assert items == []
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_CANCEL in all_cb


class TestBuildSearchResults:
    def test_file_buttons_use_cb_send_file_prefix(self, tmp_path: Path) -> None:
        f1 = tmp_path / "alpha.txt"
        f2 = tmp_path / "beta.txt"
        f1.write_bytes(b"a")
        f2.write_bytes(b"b")
        _, markup, _ = build_search_results([f1, f2], tmp_path)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        file_cbs = [
            cb for cb in all_cb if isinstance(cb, str) and cb.startswith(CB_SEND_FILE)
        ]
        assert len(file_cbs) == 2

    def test_cancel_button_present(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_bytes(b"x")
        _, markup, _ = build_search_results([f], tmp_path)
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_CANCEL in all_cb

    def test_returns_shown_subset(self, tmp_path: Path) -> None:
        paths = []
        for i in range(30):
            p = tmp_path / f"f{i:02d}.txt"
            p.write_bytes(b"x")
            paths.append(p)
        _, _, shown = build_search_results(paths, tmp_path)
        assert len(shown) == 24  # _ITEMS_PER_PAGE * 3 = 8 * 3

    def test_empty_list(self, tmp_path: Path) -> None:
        text, markup, shown = build_search_results([], tmp_path)
        assert shown == []
        all_cb = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert CB_SEND_CANCEL in all_cb
        assert not any(
            isinstance(cb, str) and cb.startswith(CB_SEND_FILE) for cb in all_cb
        )

    def test_text_shows_match_count(self, tmp_path: Path) -> None:
        f = tmp_path / "x.txt"
        f.write_bytes(b"x")
        text, _, _ = build_search_results([f], tmp_path)
        assert "1" in text


# ---------------------------------------------------------------------------
# Helpers for _upload_file and send_command tests
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock  # noqa: E402 (appended)

import pytest  # noqa: E402
from telegram.error import TelegramError  # noqa: E402

from ccgram.handlers.send_command import _upload_file, send_command  # noqa: E402
from ccgram.handlers.user_state import (  # noqa: E402
    SEND_CWD_KEY,
    SEND_ITEMS_KEY,
    SEND_PAGE_KEY,
    SEND_PATH_KEY,
    SEND_WINDOW_ID_KEY,
)


def _make_update(
    user_id: int = 1, thread_id: int = 42, text: str = "/send"
) -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock(id=user_id)
    msg = AsyncMock()
    msg.text = text
    msg.message_thread_id = thread_id
    msg.chat_id = -100123
    update.message = msg
    update.callback_query = None
    return update


def _make_context(user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {} if user_data is None else user_data
    ctx.bot = AsyncMock()
    return ctx


class TestUploadFile:
    async def test_image_calls_send_photo(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.png"
        f.write_bytes(b"imgdata")
        bot = AsyncMock()
        await _upload_file(bot, chat_id=-100, thread_id=5, path=f)
        bot.send_photo.assert_awaited_once()
        call_kwargs = bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == -100
        assert call_kwargs["message_thread_id"] == 5
        assert call_kwargs["filename"] == "photo.png"

    async def test_non_image_calls_send_document(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_bytes(b"pdfdata")
        bot = AsyncMock()
        await _upload_file(bot, chat_id=-100, thread_id=5, path=f)
        bot.send_document.assert_awaited_once()
        call_kwargs = bot.send_document.call_args.kwargs
        assert call_kwargs["filename"] == "report.pdf"

    async def test_telegram_error_is_reraised(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        bot = AsyncMock()
        bot.send_document.side_effect = TelegramError("flood")
        with pytest.raises(TelegramError):
            await _upload_file(bot, chat_id=-100, thread_id=5, path=f)

    async def test_jpg_calls_send_photo(self, tmp_path: Path) -> None:
        f = tmp_path / "img.jpg"
        f.write_bytes(b"jpgdata")
        bot = AsyncMock()
        await _upload_file(bot, chat_id=-100, thread_id=5, path=f)
        bot.send_photo.assert_awaited_once()
        bot.send_document.assert_not_awaited()


class TestSendCommand:
    @pytest.fixture(autouse=True)
    def _patches(self):
        with (
            patch("ccgram.config.Config.is_user_allowed", return_value=True),
            patch("ccgram.handlers.send_command.thread_router") as mock_tr,
            patch("ccgram.handlers.send_command.session_manager") as mock_sm,
        ):
            self.mock_tr = mock_tr
            self.mock_sm = mock_sm
            mock_tr.resolve_window_for_thread.return_value = "@1"
            mock_tr.resolve_chat_id.return_value = -100123
            ws = MagicMock()
            ws.cwd = None  # overridden per test
            mock_sm.get_window_state.return_value = ws
            mock_sm.view_window.return_value = ws
            self.ws = ws
            yield

    async def test_no_message_returns_early(self) -> None:
        update = MagicMock()
        update.message = None
        ctx = _make_context()
        await send_command(update, ctx)
        ctx.bot.send_document.assert_not_awaited()

    async def test_unauthorized_user(self) -> None:
        with patch("ccgram.config.Config.is_user_allowed", return_value=False):
            update = _make_update()
            ctx = _make_context()
            await send_command(update, ctx)
            assert SEND_WINDOW_ID_KEY not in ctx.user_data

    async def test_not_in_topic(self) -> None:
        update = _make_update(thread_id=1)
        ctx = _make_context()
        await send_command(update, ctx)

    async def test_no_window_bound(self) -> None:
        self.mock_tr.resolve_window_for_thread.return_value = None
        update = _make_update()
        ctx = _make_context()
        await send_command(update, ctx)

    async def test_cwd_unavailable(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path / "nonexistent")
        update = _make_update()
        ctx = _make_context()
        await send_command(update, ctx)

    async def test_view_window_returns_none_handled_gracefully(self) -> None:
        # Window is bound (resolve_window_for_thread succeeds), but
        # view_window returns None (window state was wiped after binding).
        # The new None guard at send_command.py should reject cleanly
        # instead of raising AttributeError.
        self.mock_sm.view_window.return_value = None
        update = _make_update()
        ctx = _make_context()
        await send_command(update, ctx)

    async def test_no_args_builds_browser(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        (tmp_path / "file.txt").write_bytes(b"x")
        update = _make_update(text="/send")
        ctx = _make_context()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            await send_command(update, ctx)
        assert ctx.user_data[SEND_PATH_KEY] == str(tmp_path)
        assert ctx.user_data[SEND_CWD_KEY] == str(tmp_path)
        assert ctx.user_data[SEND_PAGE_KEY] == 0
        assert ctx.user_data[SEND_WINDOW_ID_KEY] == "@1"
        assert isinstance(ctx.user_data[SEND_ITEMS_KEY], list)

    async def test_glob_single_match_uploads(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        f = tmp_path / "report.txt"
        f.write_bytes(b"data")
        update = _make_update(text="/send *.txt")
        ctx = _make_context()
        with (
            patch("ccgram.handlers.send_command.validate_sendable", return_value=None),
            patch(
                "ccgram.handlers.send_command._upload_file", new_callable=AsyncMock
            ) as mock_up,
        ):
            await send_command(update, ctx)
        mock_up.assert_awaited_once_with(ctx.bot, -100123, 42, f)

    async def test_glob_multiple_matches_shows_keyboard(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        for i in range(3):
            (tmp_path / f"file{i}.txt").write_bytes(b"x")
        update = _make_update(text="/send *.txt")
        ctx = _make_context()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            await send_command(update, ctx)
        assert ctx.user_data[SEND_ITEMS_KEY] is not None
        assert len(ctx.user_data[SEND_ITEMS_KEY]) == 3

    async def test_glob_no_match_sends_error(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        update = _make_update(text="/send *.xyz")
        ctx = _make_context()
        with patch("ccgram.handlers.send_command.validate_sendable", return_value=None):
            await send_command(update, ctx)

    async def test_exact_path_uploads(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        f = tmp_path / "exact.txt"
        f.write_bytes(b"data")
        update = _make_update(text="/send exact.txt")
        ctx = _make_context()
        with (
            patch("ccgram.handlers.send_command.validate_sendable", return_value=None),
            patch(
                "ccgram.handlers.send_command._upload_file", new_callable=AsyncMock
            ) as mock_up,
        ):
            await send_command(update, ctx)
        mock_up.assert_awaited_once_with(ctx.bot, -100123, 42, f)

    async def test_exact_path_denied_by_security(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        f = tmp_path / "secret.key"
        f.write_bytes(b"key")
        update = _make_update(text="/send secret.key")
        ctx = _make_context()
        with (
            patch(
                "ccgram.handlers.send_command.validate_sendable",
                return_value="File appears to contain credentials",
            ),
            patch(
                "ccgram.handlers.send_command._upload_file", new_callable=AsyncMock
            ) as mock_up,
        ):
            await send_command(update, ctx)
        mock_up.assert_not_awaited()

    async def test_text_pattern_falls_back_to_find_files(self, tmp_path: Path) -> None:
        self.ws.cwd = str(tmp_path)
        f = tmp_path / "my_report_2024.txt"
        f.write_bytes(b"data")
        update = _make_update(text="/send report")
        ctx = _make_context()
        with (
            patch("ccgram.handlers.send_command.validate_sendable", return_value=None),
            patch(
                "ccgram.handlers.send_command._upload_file", new_callable=AsyncMock
            ) as mock_up,
        ):
            await send_command(update, ctx)
        mock_up.assert_awaited_once()
