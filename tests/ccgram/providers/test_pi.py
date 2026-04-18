from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ccgram.providers.pi import (
    PiProvider,
    _candidate_transcripts,
    encode_cwd_dirname,
)
from ccgram.providers.pi_format import (
    canonical_tool_name,
    extract_text,
    format_tool_result_text,
    normalize_pending,
    parse_assistant,
    parse_bash_execution,
    parse_session_header,
    parse_tool_result,
    parse_user,
    read_session_header,
)


class TestEncodeCwdDirname:
    @pytest.mark.parametrize(
        ("cwd", "expected"),
        [
            ("/Users/alexei/Workspace/ccgram", "--Users-alexei-Workspace-ccgram--"),
            ("/tmp/foo/", "--tmp-foo--"),
            ("/tmp/foo", "--tmp-foo--"),
            ("/", "----"),
            ("/a", "--a--"),
            ("/a/b", "--a-b--"),
            ("C:\\Users\\x", "--C--Users-x--"),
            ("/has:colon/path", "--has-colon-path--"),
        ],
    )
    def test_encodes(self, cwd: str, expected: str) -> None:
        assert encode_cwd_dirname(cwd) == expected


class TestCanonicalToolName:
    @pytest.mark.parametrize(
        ("raw", "display"),
        [
            ("bash", "Bash"),
            ("BASH", "Bash"),
            ("read", "Read"),
            ("edit", "Edit"),
            ("webfetch", "WebFetch"),
            ("web_fetch", "WebFetch"),
            ("unknown_tool", "unknown_tool"),
        ],
    )
    def test_aliases(self, raw: str, display: str) -> None:
        assert canonical_tool_name(raw) == display


class TestExtractText:
    def test_string(self) -> None:
        assert extract_text("hi") == "hi"

    def test_block_array(self) -> None:
        blocks = [{"type": "text", "text": "a "}, {"type": "text", "text": "b"}]
        assert extract_text(blocks) == "a b"

    def test_skips_non_text(self) -> None:
        blocks = [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "visible"},
            {"type": "image", "data": "..."},
        ]
        assert extract_text(blocks) == "visible"

    def test_empty(self) -> None:
        assert extract_text([]) == ""
        assert extract_text(None) == ""
        assert extract_text(123) == ""


class TestFormatToolResultText:
    def test_empty_returns_done(self) -> None:
        assert format_tool_result_text("bash", "") == "Done"

    def test_bash_always_quoted(self) -> None:
        out = format_tool_result_text("bash", "one line")
        assert "1 lines" in out
        assert "one line" in out

    def test_short_non_bash_inline(self) -> None:
        assert format_tool_result_text("read", "x") == "x"

    def test_long_non_bash_quoted(self) -> None:
        output = "l1\nl2\nl3\nl4\nl5"
        rendered = format_tool_result_text("read", output)
        assert "5 lines" in rendered
        assert "l1" in rendered


class TestParseSessionHeader:
    def test_ok(self) -> None:
        entry = {
            "type": "session",
            "version": 3,
            "id": "019d9fcf-3663-750a-b941-946136546d38",
            "cwd": "/Users/alexei/Workspace/ccgram",
        }
        assert parse_session_header(entry) == {
            "id": "019d9fcf-3663-750a-b941-946136546d38",
            "cwd": "/Users/alexei/Workspace/ccgram",
        }

    @pytest.mark.parametrize(
        "entry",
        [
            {"type": "message", "id": "x", "cwd": "/"},
            {"type": "session", "cwd": "/"},
            {"type": "session", "id": "x"},
            {"type": "session", "id": "", "cwd": "/"},
            {"type": "session", "id": "x", "cwd": ""},
        ],
    )
    def test_rejects(self, entry: dict) -> None:
        assert parse_session_header(entry) is None


class TestReadSessionHeader:
    def test_reads_first_line(self, tmp_path: Path) -> None:
        path = tmp_path / "a.jsonl"
        path.write_text(
            '{"type":"session","id":"abc-123","cwd":"/x","version":3}\n'
            '{"type":"message","id":"y"}\n'
        )
        assert read_session_header(str(path)) == {"id": "abc-123", "cwd": "/x"}

    def test_missing_file(self, tmp_path: Path) -> None:
        assert read_session_header(str(tmp_path / "nope.jsonl")) is None

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert read_session_header(str(path)) is None

    def test_malformed_first_line(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text("not json\n")
        assert read_session_header(str(path)) is None


class TestParseUser:
    def test_text_blocks(self) -> None:
        msg = {"role": "user", "content": [{"type": "text", "text": "analyze g"}]}
        [m] = parse_user(msg)
        assert m.role == "user"
        assert m.content_type == "text"
        assert m.text == "analyze g"

    def test_empty_returns_nothing(self) -> None:
        assert parse_user({"role": "user", "content": []}) == []
        assert parse_user({"role": "user", "content": ""}) == []


class TestParseAssistant:
    def test_text_only(self) -> None:
        msg = {
            "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
        }
        msgs, pending = parse_assistant(msg, {})
        assert len(msgs) == 1
        assert msgs[0].content_type == "text"
        assert msgs[0].text == "hello"
        assert pending == {}

    def test_text_and_tool_calls(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "running tools"},
                {
                    "type": "toolCall",
                    "id": "t1",
                    "name": "bash",
                    "arguments": {"command": "ls -la"},
                },
                {
                    "type": "toolCall",
                    "id": "t2",
                    "name": "read",
                    "arguments": {"path": "foo.py"},
                },
            ],
        }
        msgs, pending = parse_assistant(msg, {})
        assert [m.content_type for m in msgs] == ["text", "tool_use", "tool_use"]
        assert msgs[1].tool_use_id == "t1"
        assert msgs[1].tool_name == "Bash"
        assert "ls -la" in msgs[1].text
        assert msgs[2].tool_use_id == "t2"
        assert msgs[2].tool_name == "Read"
        assert pending == {"t1": ("bash", "Bash"), "t2": ("read", "Read")}

    def test_skips_thinking(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "public"},
            ],
        }
        msgs, _ = parse_assistant(msg, {})
        assert len(msgs) == 1
        assert msgs[0].text == "public"

    def test_api_error_surfaces(self) -> None:
        msg = {
            "role": "assistant",
            "content": [],
            "stopReason": "error",
            "errorMessage": '400 {"error":"bad model"}',
        }
        msgs, _ = parse_assistant(msg, {})
        assert len(msgs) == 1
        assert msgs[0].content_type == "text"
        assert "API error" in msgs[0].text
        assert "bad model" in msgs[0].text

    def test_empty_content_no_error_no_output(self) -> None:
        msgs, _ = parse_assistant({"role": "assistant", "content": []}, {})
        assert msgs == []


class TestParseToolResult:
    def test_pairs_with_pending(self) -> None:
        pending = {"t1": ("bash", "Bash")}
        msg = {
            "role": "toolResult",
            "toolCallId": "t1",
            "toolName": "bash",
            "content": [{"type": "text", "text": "one\ntwo\nthree\nfour"}],
            "isError": False,
        }
        [out], pending = parse_tool_result(msg, pending)
        assert out.content_type == "tool_result"
        assert out.tool_use_id == "t1"
        assert out.tool_name == "Bash"
        assert "4 lines" in out.text
        assert pending == {}

    def test_fallback_without_pending(self) -> None:
        msg = {
            "role": "toolResult",
            "toolCallId": "unknown",
            "toolName": "read",
            "content": [{"type": "text", "text": "ok"}],
        }
        [out], _ = parse_tool_result(msg, {})
        assert out.tool_name == "Read"
        assert out.text == "ok"

    def test_error_flag(self) -> None:
        msg = {
            "role": "toolResult",
            "toolCallId": "t1",
            "toolName": "bash",
            "content": [{"type": "text", "text": "boom"}],
            "isError": True,
        }
        [out], _ = parse_tool_result(msg, {})
        assert out.text == "Error: boom"


class TestParseBashExecution:
    def test_happy_path(self) -> None:
        [out] = parse_bash_execution(
            {"role": "bashExecution", "command": "ls", "output": "a\nb"}
        )
        assert "$ ls" in out.text
        assert "a\nb" in out.text

    def test_excluded_from_context(self) -> None:
        assert (
            parse_bash_execution(
                {
                    "role": "bashExecution",
                    "command": "echo x",
                    "output": "x",
                    "excludeFromContext": True,
                }
            )
            == []
        )

    def test_non_zero_exit(self) -> None:
        [out] = parse_bash_execution(
            {"role": "bashExecution", "command": "false", "output": "", "exitCode": 1}
        )
        assert "exit code 1" in out.text


class TestNormalizePending:
    def test_accepts_tuple(self) -> None:
        assert normalize_pending({"x": ("bash", "Bash")}) == {"x": ("bash", "Bash")}

    def test_accepts_legacy_string(self) -> None:
        assert normalize_pending({"x": "bash"}) == {"x": ("bash", "Bash")}

    def test_rejects_garbage(self) -> None:
        assert normalize_pending({"x": 123, "y": None}) == {}

    def test_non_dict(self) -> None:
        assert normalize_pending(None) == {}
        assert normalize_pending([]) == {}


class TestMakeLaunchArgs:
    def setup_method(self) -> None:
        self.provider = PiProvider()

    def test_fresh(self) -> None:
        assert self.provider.make_launch_args() == ""

    def test_continue(self) -> None:
        assert self.provider.make_launch_args(use_continue=True) == "--continue"

    def test_session_by_uuid(self) -> None:
        uuid = "019d9fcf-3663-750a-b941-946136546d38"
        assert self.provider.make_launch_args(resume_id=uuid) == f"--session {uuid}"

    def test_session_by_path(self) -> None:
        args = self.provider.make_launch_args(resume_id="/tmp/a.jsonl")
        assert args == "--session /tmp/a.jsonl"

    def test_shell_quoting_path_with_space(self) -> None:
        args = self.provider.make_launch_args(resume_id="/tmp/has space.jsonl")
        assert args == "--session '/tmp/has space.jsonl'"

    def test_resume_wins_over_continue(self) -> None:
        args = self.provider.make_launch_args(resume_id="x", use_continue=True)
        assert args == "--session x"


class TestParseTranscriptLine:
    def setup_method(self) -> None:
        self.provider = PiProvider()

    def test_passes_through_session_header(self) -> None:
        line = '{"type":"session","id":"abc","cwd":"/x"}'
        out = self.provider.parse_transcript_line(line)
        assert out == {"type": "session", "id": "abc", "cwd": "/x"}

    def test_unwraps_message_envelope(self) -> None:
        line = json.dumps(
            {
                "type": "message",
                "id": "m1",
                "parentId": "m0",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}],
                },
            }
        )
        out = self.provider.parse_transcript_line(line)
        assert out is not None
        assert out["type"] == "user"
        assert out["id"] == "m1"
        assert out["parentId"] == "m0"
        assert out["message"]["content"][0]["text"] == "hi"

    def test_rejects_empty(self) -> None:
        assert self.provider.parse_transcript_line("") is None
        assert self.provider.parse_transcript_line("not json") is None

    def test_rejects_message_without_role(self) -> None:
        line = '{"type":"message","message":{"content":[]}}'
        assert self.provider.parse_transcript_line(line) is None


class TestDiscoverTranscript:
    def _write_session(self, path: Path, session_id: str, cwd: str) -> Path:
        path.write_text(
            json.dumps({"type": "session", "id": session_id, "cwd": cwd, "version": 3})
            + "\n"
        )
        return path

    def test_returns_newest_matching_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ccgram.providers.pi._PI_SESSIONS_DIR", tmp_path)
        cwd = "/real/project"
        session_dir = tmp_path / encode_cwd_dirname(cwd)
        session_dir.mkdir()
        older = self._write_session(session_dir / "old.jsonl", "s1", cwd)
        newer = self._write_session(session_dir / "new.jsonl", "s2", cwd)
        now = time.time()
        import os

        os.utime(older, (now - 100, now - 100))
        os.utime(newer, (now, now))

        monkeypatch.setattr("pathlib.Path.resolve", lambda self, strict=False: self)
        provider = PiProvider()
        ev = provider.discover_transcript(cwd, "ccgram:@0", max_age=0)
        assert ev is not None
        assert ev.session_id == "s2"
        assert ev.transcript_path == str(newer)
        assert ev.window_key == "ccgram:@0"

    def test_empty_cwd_returns_none(self) -> None:
        assert PiProvider().discover_transcript("", "ccgram:@0") is None

    def test_missing_dir_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ccgram.providers.pi._PI_SESSIONS_DIR", tmp_path)
        assert PiProvider().discover_transcript("/no/such/place", "ccgram:@0") is None


class TestCapabilities:
    def test_shape(self) -> None:
        caps = PiProvider().capabilities
        assert caps.name == "pi"
        assert caps.launch_command == "pi"
        assert caps.supports_hook is False
        assert caps.supports_resume is True
        assert caps.supports_continue is True
        assert caps.transcript_format == "jsonl"
        assert caps.supports_incremental_read is True
        assert "/compact" in caps.builtin_commands


class TestDiscoverCommands:
    def test_returns_builtins(self) -> None:
        cmds = PiProvider().discover_commands("")
        names = {c.name for c in cmds}
        assert "/compact" in names
        assert "/tree" in names
        assert all(c.source == "builtin" for c in cmds)


class TestRealSessionFixture:
    FIXTURE = Path(
        "/Users/alexei/.pi/agent/sessions/"
        "--Users-alexei-Workspace-ccgram--/"
        "2026-04-18T08-57-30-467Z_019d9fcf-3663-750a-b941-946136546d38.jsonl"
    )

    def _skip_if_missing(self) -> None:
        if not self.FIXTURE.is_file():
            pytest.skip(f"live fixture missing: {self.FIXTURE}")

    def test_pairs_all_tool_calls(self) -> None:
        self._skip_if_missing()
        provider = PiProvider()
        entries: list[dict] = []
        for line in self.FIXTURE.read_text().splitlines():
            parsed = provider.parse_transcript_line(line)
            if parsed is not None:
                entries.append(parsed)

        assert entries, "expected non-empty fixture"
        assert entries[0]["type"] == "session"

        _, pending = provider.parse_transcript_entries(entries, {})
        assert pending == {}, (
            f"{len(pending)} unpaired toolCall(s) — parser dropped results"
        )


class TestIntegrationWithCandidateTranscripts:
    def test_sorts_newest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("ccgram.providers.pi._PI_SESSIONS_DIR", tmp_path)
        cwd = "/demo"
        d = tmp_path / encode_cwd_dirname(cwd)
        d.mkdir()
        (d / "a.jsonl").write_text("{}\n")
        (d / "b.jsonl").write_text("{}\n")
        import os

        now = time.time()
        os.utime(d / "a.jsonl", (now - 200, now - 200))
        os.utime(d / "b.jsonl", (now, now))
        result = _candidate_transcripts(cwd)
        assert [p.name for _, p in result] == ["b.jsonl", "a.jsonl"]
