"""Tests for ccgram.utils: ccgram_dir, atomic_write_json, read_cwd_from_jsonl, read_session_metadata_from_jsonl, log_throttled, assert_sendable, handle_general_topic_message, is_general_topic."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from ccgram.utils import (
    _SCAN_LINES,
    _general_topic_pin_cache,
    _throttle_state,
    assert_sendable,
    atomic_write_json,
    ccgram_dir,
    handle_general_topic_message,
    is_general_topic,
    log_throttle_reset,
    log_throttle_sweep,
    log_throttled,
    read_cwd_from_jsonl,
    read_session_metadata_from_jsonl,
    shorten_path,
)


class TestCcgramDir:
    def test_returns_env_var_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CCGRAM_DIR", "/custom/config")
        assert ccgram_dir() == Path("/custom/config")

    def test_returns_default_without_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("CCGRAM_DIR", raising=False)
        monkeypatch.delenv("CCBOT_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert ccgram_dir() == tmp_path / ".ccgram"

    def test_falls_back_to_legacy_ccbot_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("CCGRAM_DIR", raising=False)
        monkeypatch.delenv("CCBOT_DIR", raising=False)
        legacy = tmp_path / ".ccbot"
        legacy.mkdir()
        (legacy / ".env").write_text("TELEGRAM_BOT_TOKEN=test\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert ccgram_dir() == legacy

    def test_falls_back_when_ccgram_dir_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("CCGRAM_DIR", raising=False)
        monkeypatch.delenv("CCBOT_DIR", raising=False)
        new = tmp_path / ".ccgram"
        new.mkdir()
        legacy = tmp_path / ".ccbot"
        legacy.mkdir()
        (legacy / ".env").write_text("TELEGRAM_BOT_TOKEN=test\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert ccgram_dir() == legacy

    def test_prefers_ccgram_when_it_has_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("CCGRAM_DIR", raising=False)
        monkeypatch.delenv("CCBOT_DIR", raising=False)
        new = tmp_path / ".ccgram"
        new.mkdir()
        (new / ".env").write_text("TELEGRAM_BOT_TOKEN=test\n")
        legacy = tmp_path / ".ccbot"
        legacy.mkdir()
        (legacy / ".env").write_text("TELEGRAM_BOT_TOKEN=old\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert ccgram_dir() == new


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


class TestLogThrottled:
    @pytest.fixture(autouse=True)
    def _clean_throttle_state(self):
        _throttle_state.clear()
        yield
        _throttle_state.clear()

    def test_first_call_logs(self):
        log = structlog.get_logger()
        log_throttled(log, "k1", "hello %s", "world", cooldown=60.0)
        assert "k1" in _throttle_state
        assert _throttle_state["k1"][1] == "hello world"

    def test_duplicate_within_cooldown_suppressed(self):
        t = 100.0
        log = structlog.get_logger()
        log_throttled(log, "k1", "msg", _clock=lambda: t, cooldown=60.0)
        _throttle_state["k1"] = (t, "msg")
        calls_before = dict(_throttle_state)
        log_throttled(log, "k1", "msg", _clock=lambda: t + 30, cooldown=60.0)
        assert _throttle_state["k1"] == calls_before["k1"]

    def test_logs_again_after_cooldown(self):
        t = 100.0
        log = structlog.get_logger()
        log_throttled(log, "k1", "msg", _clock=lambda: t, cooldown=60.0)
        old_ts = _throttle_state["k1"][0]
        log_throttled(log, "k1", "msg", _clock=lambda: t + 61, cooldown=60.0)
        assert _throttle_state["k1"][0] != old_ts

    def test_changed_message_logs_immediately(self):
        t = 100.0
        log = structlog.get_logger()
        log_throttled(log, "k1", "msg-a", _clock=lambda: t, cooldown=300.0)
        assert _throttle_state["k1"][1] == "msg-a"
        log_throttled(log, "k1", "msg-b", _clock=lambda: t + 1, cooldown=300.0)
        assert _throttle_state["k1"][1] == "msg-b"

    def test_reset_clears_matching_keys(self):
        _throttle_state["topic-probe:@1"] = (0.0, "err")
        _throttle_state["topic-probe:@2"] = (0.0, "err")
        _throttle_state["status-update:1:2"] = (0.0, "err")
        log_throttle_reset("topic-probe:")
        assert "topic-probe:@1" not in _throttle_state
        assert "topic-probe:@2" not in _throttle_state
        assert "status-update:1:2" in _throttle_state


class TestLogThrottleSweep:
    @pytest.fixture(autouse=True)
    def _clean_throttle_state(self):
        _throttle_state.clear()
        yield
        _throttle_state.clear()

    def test_removes_stale_entries(self):
        _throttle_state["old"] = (100.0, "msg")
        _throttle_state["fresh"] = (800.0, "msg")
        removed = log_throttle_sweep(max_age=600.0, _clock=lambda: 800.0)
        assert removed == 1
        assert "old" not in _throttle_state
        assert "fresh" in _throttle_state

    def test_empty_state_returns_zero(self):
        assert log_throttle_sweep() == 0

    def test_all_fresh_removes_nothing(self):
        _throttle_state["a"] = (100.0, "msg")
        _throttle_state["b"] = (200.0, "msg")
        removed = log_throttle_sweep(max_age=600.0, _clock=lambda: 300.0)
        assert removed == 0
        assert len(_throttle_state) == 2

    def test_all_stale_clears_everything(self):
        _throttle_state["a"] = (0.0, "msg")
        _throttle_state["b"] = (1.0, "msg")
        removed = log_throttle_sweep(max_age=10.0, _clock=lambda: 1000.0)
        assert removed == 2
        assert len(_throttle_state) == 0


class TestAssertSendable:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CCBOT_DIR", raising=False)

    def test_path_inside_state_dir_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        secret = state_dir / "state.json"
        secret.touch()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        with pytest.raises(ValueError, match="refusing to send state file"):
            assert_sendable(secret)

    def test_state_dir_itself_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        with pytest.raises(ValueError, match="refusing to send state file"):
            assert_sendable(state_dir)

    def test_path_outside_state_dir_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        safe_file = tmp_path / "project" / "file.txt"
        safe_file.parent.mkdir()
        safe_file.touch()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        assert_sendable(safe_file)

    def test_nonexistent_path_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        assert_sendable(tmp_path / "does" / "not" / "exist.txt")

    def test_sibling_dir_with_prefix_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        sibling = tmp_path / ".ccgram-uploads"
        sibling.mkdir()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        assert_sendable(sibling / "photo.jpg")

    def test_os_error_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        state_dir = tmp_path / ".ccgram"
        state_dir.mkdir()
        monkeypatch.setenv("CCGRAM_DIR", str(state_dir))
        original_resolve = Path.resolve

        def broken_resolve(self: Path, strict: bool = False) -> Path:
            if "file.txt" in str(self):
                raise OSError("simulated resolve failure")
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", broken_resolve)
        with pytest.raises(ValueError, match="cannot verify path safety"):
            assert_sendable("/some/file.txt")


class TestShortenPath:
    def test_subpath_shortened(self) -> None:
        assert (
            shorten_path("/home/user/project/src/file.py", "/home/user/project")
            == "src/file.py"
        )

    def test_not_subpath_unchanged(self) -> None:
        assert (
            shorten_path("/other/path/file.py", "/home/user/project")
            == "/other/path/file.py"
        )

    def test_cwd_none_unchanged(self) -> None:
        assert shorten_path("/some/path/file.py", None) == "/some/path/file.py"

    def test_empty_path_unchanged(self) -> None:
        assert shorten_path("", "/home/user") == ""

    def test_cwd_trailing_slash(self) -> None:
        assert (
            shorten_path("/home/user/project/src/f.py", "/home/user/project/")
            == "src/f.py"
        )

    def test_exact_cwd_match(self) -> None:
        result = shorten_path("/home/user/project", "/home/user/project")
        assert result == "/home/user/project"

    def test_relative_path_unchanged(self) -> None:
        assert shorten_path("src/file.py", "/home/user/project") == "src/file.py"

    def test_prefix_match_guard(self) -> None:
        assert (
            shorten_path("/home/userextra/file.py", "/home/user")
            == "/home/userextra/file.py"
        )


class TestHandleGeneralTopicMessage:
    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        _general_topic_pin_cache.clear()
        yield
        _general_topic_pin_cache.clear()

    @pytest.mark.asyncio
    async def test_first_message_sends_hint_and_pins(self) -> None:
        bot = AsyncMock()
        # No existing pinned message
        chat_info = MagicMock()
        chat_info.pinned_message = None
        bot.get_chat = AsyncMock(return_value=chat_info)

        message = AsyncMock()
        hint_msg = AsyncMock()
        message.reply_text = AsyncMock(return_value=hint_msg)

        await handle_general_topic_message(bot, message, chat_id=123)

        message.reply_text.assert_called_once()
        assert "named topic" in message.reply_text.call_args.args[0]
        hint_msg.pin.assert_called_once_with(disable_notification=True)
        assert _general_topic_pin_cache[123] is True

    @pytest.mark.asyncio
    async def test_subsequent_message_reacts_only(self) -> None:
        _general_topic_pin_cache[123] = True

        bot = AsyncMock()
        message = AsyncMock()

        await handle_general_topic_message(bot, message, chat_id=123)

        message.set_reaction.assert_called_once_with("\U0001f914")
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_detects_existing_pinned_bot_message(self) -> None:
        bot = AsyncMock()
        bot.id = 999
        pinned = MagicMock()
        pinned.from_user.id = 999
        chat_info = MagicMock()
        chat_info.pinned_message = pinned
        bot.get_chat = AsyncMock(return_value=chat_info)

        message = AsyncMock()

        await handle_general_topic_message(bot, message, chat_id=456)

        # Should detect pinned message and react instead of re-pinning
        message.set_reaction.assert_called_once_with("\U0001f914")
        message.reply_text.assert_not_called()
        assert _general_topic_pin_cache[456] is True

    @pytest.mark.asyncio
    async def test_ignores_pinned_message_from_other_bot(self) -> None:
        bot = AsyncMock()
        bot.id = 999
        pinned = MagicMock()
        pinned.from_user.id = 888  # different bot
        chat_info = MagicMock()
        chat_info.pinned_message = pinned
        bot.get_chat = AsyncMock(return_value=chat_info)

        message = AsyncMock()
        hint_msg = AsyncMock()
        message.reply_text = AsyncMock(return_value=hint_msg)

        await handle_general_topic_message(bot, message, chat_id=456)

        # Should send hint since pinned message is from a different bot
        message.reply_text.assert_called_once()
        hint_msg.pin.assert_called_once_with(disable_notification=True)

    @pytest.mark.asyncio
    async def test_pin_failure_does_not_crash_and_caches(self) -> None:
        from telegram.error import TelegramError

        bot = AsyncMock()
        chat_info = MagicMock()
        chat_info.pinned_message = None
        bot.get_chat = AsyncMock(return_value=chat_info)

        message = AsyncMock()
        hint_msg = AsyncMock()
        hint_msg.pin = AsyncMock(side_effect=TelegramError("no rights"))
        message.reply_text = AsyncMock(return_value=hint_msg)

        # Should not raise
        await handle_general_topic_message(bot, message, chat_id=789)
        # Cache should be set even though pin failed (one-shot guarantee)
        assert _general_topic_pin_cache[789] is True

    @pytest.mark.asyncio
    async def test_react_failure_does_not_crash(self) -> None:
        from telegram.error import TelegramError

        _general_topic_pin_cache[123] = True
        bot = AsyncMock()
        message = AsyncMock()
        message.set_reaction = AsyncMock(side_effect=TelegramError("forbidden"))

        # Should not raise
        await handle_general_topic_message(bot, message, chat_id=123)


class TestIsGeneralTopic:
    def test_general_topic_thread_id_1(self) -> None:
        message = MagicMock()
        message.message_thread_id = 1
        message.chat.is_forum = True
        assert is_general_topic(message) is True

    def test_general_topic_thread_id_none_in_forum(self) -> None:
        message = MagicMock()
        message.message_thread_id = None
        message.chat.is_forum = True
        assert is_general_topic(message) is True

    def test_named_topic(self) -> None:
        message = MagicMock()
        message.message_thread_id = 42
        message.chat.is_forum = True
        assert is_general_topic(message) is False

    def test_non_forum_context(self) -> None:
        message = MagicMock()
        message.message_thread_id = None
        message.chat.is_forum = False
        assert is_general_topic(message) is False

    def test_no_chat(self) -> None:
        message = MagicMock()
        message.chat = None
        message.message_thread_id = None
        assert is_general_topic(message) is False
