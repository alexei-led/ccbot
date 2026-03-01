"""Tests for ccbot.utils: ccbot_dir, atomic_write_json, read_cwd_from_jsonl, read_session_metadata_from_jsonl."""

import json
from pathlib import Path

import pytest

from ccbot.utils import (
    _SCAN_LINES,
    atomic_write_json,
    ccbot_dir,
    read_cwd_from_jsonl,
    read_session_metadata_from_jsonl,
)


class TestCcbotDir:
    def test_returns_env_var_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CCBOT_DIR", "/custom/config")
        assert ccbot_dir() == Path("/custom/config")

    def test_returns_default_without_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CCBOT_DIR", raising=False)
        assert ccbot_dir() == Path.home() / ".ccbot"


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path: Path):
        target = tmp_path / "data.json"
        atomic_write_json(target, {"key": "value"})
        result = json.loads(target.read_text(encoding="utf-8"))
        assert result == {"key": "value"}

    def test_creates_parent_directories(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c" / "data.json"
        atomic_write_json(target, [1, 2, 3])
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == [1, 2, 3]

    def test_round_trip(self, tmp_path: Path):
        data = {"users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]}
        target = tmp_path / "round_trip.json"
        atomic_write_json(target, data)
        assert json.loads(target.read_text(encoding="utf-8")) == data

    def test_no_temp_files_left_on_success(self, tmp_path: Path):
        target = tmp_path / "clean.json"
        atomic_write_json(target, {"ok": True})
        remaining = list(tmp_path.glob(".*tmp*"))
        assert remaining == []


class TestReadCwdFromJsonl:
    def test_cwd_in_first_entry(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(json.dumps({"cwd": "/home/user/project"}) + "\n")
        assert read_cwd_from_jsonl(f) == "/home/user/project"

    def test_cwd_in_second_entry(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "init"}),
            json.dumps({"cwd": "/found/here"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        assert read_cwd_from_jsonl(f) == "/found/here"

    def test_no_cwd_returns_empty(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "init"}),
            json.dumps({"type": "message", "text": "hello"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        assert read_cwd_from_jsonl(f) == ""

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert read_cwd_from_jsonl(tmp_path / "nonexistent.jsonl") == ""

    def test_scan_limit_stops_reading(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        filler = [json.dumps({"type": "init"}) for _ in range(_SCAN_LINES)]
        filler.append(json.dumps({"cwd": "/too/late"}))
        f.write_text("\n".join(filler) + "\n")
        assert read_cwd_from_jsonl(f) == ""

    def test_malformed_json_lines_skipped(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            "not valid json{{{",
            json.dumps({"cwd": "/found/after/garbage"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        assert read_cwd_from_jsonl(f) == "/found/after/garbage"

    def test_non_string_cwd_ignored(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"cwd": 123}),
            json.dumps({"cwd": "/real/path"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        assert read_cwd_from_jsonl(f) == "/real/path"


class TestReadSessionMetadataFromJsonl:
    def test_extracts_cwd_and_summary(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "cwd": "/my/project",
                    "message": {"content": "Fix the bug"},
                }
            ),
        ]
        f.write_text("\n".join(lines) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/my/project"
        assert summary == "Fix the bug"

    def test_cwd_and_summary_on_different_lines(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"cwd": "/my/project"}),
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": "Hello"},
                }
            ),
        ]
        f.write_text("\n".join(lines) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/my/project"
        assert summary == "Hello"

    def test_cwd_only(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text(json.dumps({"cwd": "/my/project"}) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/my/project"
        assert summary == ""

    def test_summary_only(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        entry = {"type": "user", "message": {"content": "Hello"}}
        f.write_text(json.dumps(entry) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == ""
        assert summary == "Hello"

    def test_missing_file_returns_empty(self, tmp_path: Path):
        cwd, summary = read_session_metadata_from_jsonl(tmp_path / "gone.jsonl")
        assert cwd == ""
        assert summary == ""

    def test_scan_limit_stops_reading(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        filler = [json.dumps({"type": "init"}) for _ in range(_SCAN_LINES)]
        filler.append(json.dumps({"cwd": "/too/late"}))
        f.write_text("\n".join(filler) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == ""
        assert summary == ""

    def test_malformed_json_lines_skipped(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            "not valid json{{{",
            json.dumps(
                {
                    "type": "user",
                    "cwd": "/my/project",
                    "message": {"content": "After garbage"},
                }
            ),
        ]
        f.write_text("\n".join(lines) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/my/project"
        assert summary == "After garbage"

    def test_stops_early_when_both_found(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "cwd": "/proj",
                    "message": {"content": "Go"},
                }
            ),
            json.dumps({"cwd": "/should/not/reach"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/proj"
        assert summary == "Go"

    def test_non_dict_jsonl_lines_skipped(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            "[1, 2, 3]",
            '"bare string"',
            json.dumps({"cwd": "/my/project"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        cwd, summary = read_session_metadata_from_jsonl(f)
        assert cwd == "/my/project"
        assert summary == ""

    def test_extracts_text_from_content_blocks(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        entry = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "Fix the bug"}]},
        }
        f.write_text(json.dumps(entry) + "\n")
        _, summary = read_session_metadata_from_jsonl(f)
        assert summary == "Fix the bug"

    def test_truncates_long_summary(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        long_text = "x" * 200
        entry = {"type": "user", "message": {"content": long_text}}
        f.write_text(json.dumps(entry) + "\n")
        _, summary = read_session_metadata_from_jsonl(f)
        assert len(summary) == 80

    def test_skips_non_user_entries_for_summary(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot"}),
            json.dumps({"type": "assistant", "message": {"content": "I will help"}}),
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": [{"type": "text", "text": "Second msg"}]},
                }
            ),
        ]
        f.write_text("\n".join(lines) + "\n")
        _, summary = read_session_metadata_from_jsonl(f)
        assert summary == "Second msg"
