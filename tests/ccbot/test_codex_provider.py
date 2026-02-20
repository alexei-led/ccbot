"""Codex-specific provider tests — behavior that differs from the generic contracts."""

import pytest

from ccbot.providers.base import AgentMessage, AgentProvider, DiscoveredCommand
from ccbot.providers.codex import CodexProvider


@pytest.fixture
def codex() -> CodexProvider:
    return CodexProvider()


class TestCodexCapabilities:
    def test_name(self, codex: CodexProvider) -> None:
        assert codex.capabilities.name == "codex"

    def test_no_hook_support(self, codex: CodexProvider) -> None:
        assert codex.capabilities.supports_hook is False

    def test_resume_supported(self, codex: CodexProvider) -> None:
        assert codex.capabilities.supports_resume is True

    def test_continue_not_supported(self, codex: CodexProvider) -> None:
        assert codex.capabilities.supports_continue is False

    def test_transcript_format(self, codex: CodexProvider) -> None:
        assert codex.capabilities.transcript_format == "jsonl"

    def test_no_terminal_ui_patterns(self, codex: CodexProvider) -> None:
        assert codex.capabilities.terminal_ui_patterns == ()

    def test_protocol_conformance(self, codex: CodexProvider) -> None:
        assert isinstance(codex, AgentProvider)


class TestCodexLaunchArgs:
    def test_fresh_session(self, codex: CodexProvider) -> None:
        assert codex.make_launch_args() == ""

    def test_resume_uses_subcommand(self, codex: CodexProvider) -> None:
        result = codex.make_launch_args(resume_id="abc-123")
        assert result == "exec resume abc-123"

    def test_empty_resume_id_returns_empty(self, codex: CodexProvider) -> None:
        assert codex.make_launch_args(resume_id="") == ""

    def test_invalid_resume_id_raises(self, codex: CodexProvider) -> None:
        with pytest.raises(ValueError, match="Invalid resume_id"):
            codex.make_launch_args(resume_id="abc; rm -rf /")

    def test_continue_ignored_when_unsupported(self, codex: CodexProvider) -> None:
        result = codex.make_launch_args(use_continue=True)
        assert result == ""


class TestCodexHookPayload:
    def test_always_returns_none(self, codex: CodexProvider) -> None:
        payload = {
            "session_id": "abc-123",
            "cwd": "/tmp/test",
            "transcript_path": "/tmp/test.jsonl",
            "window_key": "ccbot:@0",
        }
        assert codex.parse_hook_payload(payload) is None

    def test_empty_payload_returns_none(self, codex: CodexProvider) -> None:
        assert codex.parse_hook_payload({}) is None


class TestCodexTranscript:
    def test_tool_use_sets_pending(self, codex: CodexProvider) -> None:
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}
                    ]
                },
            }
        ]
        _, pending = codex.parse_transcript_entries(entries, {})
        assert "t1" in pending
        assert pending["t1"] == "Bash"

    def test_tool_result_resolves_pending(self, codex: CodexProvider) -> None:
        entries = [
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                    ]
                },
            }
        ]
        _, pending = codex.parse_transcript_entries(entries, {"t1": "Bash"})
        assert "t1" not in pending

    def test_string_content_parsed(self, codex: CodexProvider) -> None:
        entries = [
            {"type": "user", "message": {"content": "hello codex"}},
        ]
        messages, _ = codex.parse_transcript_entries(entries, {})
        assert len(messages) == 1
        assert messages[0].text == "hello codex"
        assert messages[0].role == "user"

    def test_skips_non_message_types(self, codex: CodexProvider) -> None:
        entries = [{"type": "summary", "message": {"content": "ignored"}}]
        messages, _ = codex.parse_transcript_entries(entries, {})
        assert messages == []


class TestCodexTerminalStatus:
    def test_empty_returns_none(self, codex: CodexProvider) -> None:
        assert codex.parse_terminal_status("") is None

    def test_whitespace_returns_none(self, codex: CodexProvider) -> None:
        assert codex.parse_terminal_status("   \n   ") is None

    def test_uses_last_line(self, codex: CodexProvider) -> None:
        pane = "some output\nprocessing files...\n"
        result = codex.parse_terminal_status(pane)
        assert result is not None
        assert result.raw_text == "processing files..."
        assert result.is_interactive is False

    def test_no_interactive_detection(self, codex: CodexProvider) -> None:
        pane = "  Would you like to proceed?\n  Yes     No\n"
        result = codex.parse_terminal_status(pane)
        assert result is None or result.is_interactive is False


class TestCodexHistory:
    def test_user_message(self, codex: CodexProvider) -> None:
        entry = {"type": "user", "message": {"content": "do something"}}
        result = codex.parse_history_entry(entry)
        assert result is not None
        assert isinstance(result, AgentMessage)
        assert result.role == "user"
        assert result.text == "do something"

    def test_assistant_message_with_blocks(self, codex: CodexProvider) -> None:
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Here is "},
                    {"type": "text", "text": "the result"},
                ]
            },
        }
        result = codex.parse_history_entry(entry)
        assert result is not None
        assert result.text == "Here is the result"

    def test_summary_returns_none(self, codex: CodexProvider) -> None:
        assert codex.parse_history_entry({"type": "summary"}) is None

    def test_empty_content_returns_none(self, codex: CodexProvider) -> None:
        entry = {"type": "assistant", "message": {"content": []}}
        assert codex.parse_history_entry(entry) is None


class TestCodexCommands:
    def test_returns_builtins(self, codex: CodexProvider) -> None:
        result = codex.discover_commands("/tmp/nonexistent")
        assert len(result) == 4
        names = [c.name for c in result]
        assert "/exit" in names
        assert "/model" in names
        assert "/status" in names
        assert "/mode" in names

    def test_all_are_builtin_source(self, codex: CodexProvider) -> None:
        result = codex.discover_commands("/tmp/nonexistent")
        assert all(isinstance(c, DiscoveredCommand) for c in result)
        assert all(c.source == "builtin" for c in result)

    def test_ignores_base_dir(self, codex: CodexProvider) -> None:
        result1 = codex.discover_commands("/tmp/a")
        result2 = codex.discover_commands("/tmp/b")
        assert [c.name for c in result1] == [c.name for c in result2]
