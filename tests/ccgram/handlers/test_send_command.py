"""Tests for src/ccgram/handlers/send_command.py."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from ccgram.config import config
from ccgram.handlers.send_command import (
    _find_files,
    _format_file_label,
    _is_image,
    _list_directory,
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
        time.sleep(0.05)
        new = self._make_file(tmp_path / "new.txt")
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
