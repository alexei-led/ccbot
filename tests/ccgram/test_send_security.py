from pathlib import Path

import pytest

from ccgram.send_security import validate_send_path


@pytest.fixture()
def tmp_cwd(tmp_path: Path) -> Path:
    return tmp_path


def test_valid_file_within_cwd(tmp_cwd: Path) -> None:
    target = tmp_cwd / "report.txt"
    target.touch()
    assert validate_send_path(target, tmp_cwd) is True


def test_valid_nested_file(tmp_cwd: Path) -> None:
    subdir = tmp_cwd / "output"
    subdir.mkdir()
    target = subdir / "result.json"
    target.touch()
    assert validate_send_path(target, tmp_cwd) is True


def test_path_traversal_rejected(tmp_cwd: Path) -> None:
    outside = tmp_cwd.parent / "secret.txt"
    assert validate_send_path(outside, tmp_cwd) is False


def test_path_traversal_dotdot_rejected(tmp_cwd: Path) -> None:
    traversal = tmp_cwd / ".." / "secret.txt"
    assert validate_send_path(traversal, tmp_cwd) is False


def test_ccgram_uploads_dir_rejected(tmp_cwd: Path) -> None:
    uploads = tmp_cwd / ".ccgram-uploads"
    uploads.mkdir()
    target = uploads / "photo.jpg"
    target.touch()
    assert validate_send_path(target, tmp_cwd) is False


def test_ccgram_uploads_nested_rejected(tmp_cwd: Path) -> None:
    uploads = tmp_cwd / ".ccgram-uploads" / "sub"
    uploads.mkdir(parents=True)
    target = uploads / "file.txt"
    target.touch()
    assert validate_send_path(target, tmp_cwd) is False


def test_hidden_file_allowed_by_default(tmp_cwd: Path) -> None:
    target = tmp_cwd / ".env"
    target.touch()
    assert validate_send_path(target, tmp_cwd) is True


def test_hidden_file_rejected_when_configured(tmp_cwd: Path) -> None:
    target = tmp_cwd / ".env"
    target.touch()
    assert validate_send_path(target, tmp_cwd, allow_hidden=False) is False


def test_hidden_dir_rejected_when_configured(tmp_cwd: Path) -> None:
    hidden = tmp_cwd / ".git"
    hidden.mkdir()
    target = hidden / "config"
    target.touch()
    assert validate_send_path(target, tmp_cwd, allow_hidden=False) is False


def test_non_hidden_file_allowed_when_hidden_disabled(tmp_cwd: Path) -> None:
    target = tmp_cwd / "main.py"
    target.touch()
    assert validate_send_path(target, tmp_cwd, allow_hidden=False) is True


def test_symlink_within_cwd_allowed(tmp_cwd: Path) -> None:
    real_file = tmp_cwd / "actual.txt"
    real_file.touch()
    link = tmp_cwd / "link.txt"
    link.symlink_to(real_file)
    assert validate_send_path(link, tmp_cwd) is True


def test_symlink_outside_cwd_rejected(tmp_cwd: Path) -> None:
    outside = tmp_cwd.parent / "outside.txt"
    outside.touch()
    link = tmp_cwd / "bad_link.txt"
    link.symlink_to(outside)
    assert validate_send_path(link, tmp_cwd) is False


def test_oserror_on_bad_path_returns_false() -> None:
    assert validate_send_path("\x00invalid", "/tmp") is False


def test_path_as_strings(tmp_cwd: Path) -> None:
    target = tmp_cwd / "data.csv"
    target.touch()
    assert validate_send_path(str(target), str(tmp_cwd)) is True


def test_cwd_itself_is_valid(tmp_cwd: Path) -> None:
    assert validate_send_path(tmp_cwd, tmp_cwd) is True
