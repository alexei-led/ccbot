"""Gemini-specific provider tests — behavior that differs from the generic contracts."""

import pytest

from ccbot.providers.base import AgentMessage, AgentProvider, DiscoveredCommand
from ccbot.providers.gemini import GeminiProvider


@pytest.fixture
def gemini() -> GeminiProvider:
    return GeminiProvider()


class TestGeminiCapabilities:
    def test_name(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.name == "gemini"

    def test_no_hook_support(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.supports_hook is False

    def test_resume_supported(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.supports_resume is True

    def test_continue_not_supported(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.supports_continue is False

    def test_transcript_format(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.transcript_format == "jsonl"

    def test_no_terminal_ui_patterns(self, gemini: GeminiProvider) -> None:
        assert gemini.capabilities.terminal_ui_patterns == ()

    def test_protocol_conformance(self, gemini: GeminiProvider) -> None:
        assert isinstance(gemini, AgentProvider)


class TestGeminiLaunchArgs:
    def test_fresh_session(self, gemini: GeminiProvider) -> None:
        assert gemini.make_launch_args() == ""

    def test_resume_uses_flag(self, gemini: GeminiProvider) -> None:
        result = gemini.make_launch_args(resume_id="abc-123")
        assert result == "--resume abc-123"

    def test_empty_resume_id_returns_empty(self, gemini: GeminiProvider) -> None:
        assert gemini.make_launch_args(resume_id="") == ""

    def test_invalid_resume_id_raises(self, gemini: GeminiProvider) -> None:
        with pytest.raises(ValueError, match="Invalid resume_id"):
            gemini.make_launch_args(resume_id="abc; rm -rf /")

    def test_continue_ignored_when_unsupported(self, gemini: GeminiProvider) -> None:
        result = gemini.make_launch_args(use_continue=True)
        assert result == ""


class TestGeminiHookPayload:
    def test_always_returns_none(self, gemini: GeminiProvider) -> None:
        payload = {
            "session_id": "abc-123",
            "cwd": "/tmp/test",
            "transcript_path": "/tmp/test.jsonl",
            "window_key": "ccbot:@0",
        }
        assert gemini.parse_hook_payload(payload) is None

    def test_empty_payload_returns_none(self, gemini: GeminiProvider) -> None:
        assert gemini.parse_hook_payload({}) is None


class TestGeminiTranscript:
    def test_tool_use_sets_pending(self, gemini: GeminiProvider) -> None:
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
        _, pending = gemini.parse_transcript_entries(entries, {})
        assert "t1" in pending
        assert pending["t1"] == "Bash"

    def test_tool_result_resolves_pending(self, gemini: GeminiProvider) -> None:
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
        _, pending = gemini.parse_transcript_entries(entries, {"t1": "Bash"})
        assert "t1" not in pending

    def test_string_content_parsed(self, gemini: GeminiProvider) -> None:
        entries = [
            {"type": "user", "message": {"content": "hello gemini"}},
        ]
        messages, _ = gemini.parse_transcript_entries(entries, {})
        assert len(messages) == 1
        assert messages[0].text == "hello gemini"
        assert messages[0].role == "user"

    def test_skips_non_message_types(self, gemini: GeminiProvider) -> None:
        entries = [{"type": "summary", "message": {"content": "ignored"}}]
        messages, _ = gemini.parse_transcript_entries(entries, {})
        assert messages == []

    def test_mixed_content_blocks(self, gemini: GeminiProvider) -> None:
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me "},
                        {"type": "text", "text": "check that."},
                    ]
                },
            }
        ]
        messages, _ = gemini.parse_transcript_entries(entries, {})
        assert len(messages) == 1
        assert messages[0].text == "Let me check that."

    def test_non_dict_blocks_skipped(self, gemini: GeminiProvider) -> None:
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": ["plain string", {"type": "text", "text": "ok"}]
                },
            }
        ]
        messages, _ = gemini.parse_transcript_entries(entries, {})
        assert len(messages) == 1
        assert messages[0].text == "ok"


class TestGeminiTerminalStatus:
    def test_empty_returns_none(self, gemini: GeminiProvider) -> None:
        assert gemini.parse_terminal_status("") is None

    def test_whitespace_returns_none(self, gemini: GeminiProvider) -> None:
        assert gemini.parse_terminal_status("   \n   ") is None

    def test_uses_last_line(self, gemini: GeminiProvider) -> None:
        pane = "some output\nprocessing files...\n"
        result = gemini.parse_terminal_status(pane)
        assert result is not None
        assert result.raw_text == "processing files..."
        assert result.is_interactive is False

    def test_no_interactive_detection(self, gemini: GeminiProvider) -> None:
        pane = "  Would you like to proceed?\n  Yes     No\n"
        result = gemini.parse_terminal_status(pane)
        assert result is None or result.is_interactive is False


class TestGeminiHistory:
    def test_user_message(self, gemini: GeminiProvider) -> None:
        entry = {"type": "user", "message": {"content": "do something"}}
        result = gemini.parse_history_entry(entry)
        assert result is not None
        assert isinstance(result, AgentMessage)
        assert result.role == "user"
        assert result.text == "do something"

    def test_assistant_message_with_blocks(self, gemini: GeminiProvider) -> None:
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Here is "},
                    {"type": "text", "text": "the result"},
                ]
            },
        }
        result = gemini.parse_history_entry(entry)
        assert result is not None
        assert result.text == "Here is the result"

    def test_summary_returns_none(self, gemini: GeminiProvider) -> None:
        assert gemini.parse_history_entry({"type": "summary"}) is None

    def test_empty_content_returns_none(self, gemini: GeminiProvider) -> None:
        entry = {"type": "assistant", "message": {"content": []}}
        assert gemini.parse_history_entry(entry) is None

    def test_non_list_non_string_content(self, gemini: GeminiProvider) -> None:
        entry = {"type": "assistant", "message": {"content": 42}}
        assert gemini.parse_history_entry(entry) is None


class TestGeminiCommands:
    def test_returns_builtins(self, gemini: GeminiProvider) -> None:
        result = gemini.discover_commands("/tmp/nonexistent")
        assert len(result) == 11
        names = [c.name for c in result]
        assert "/clear" in names
        assert "/model" in names
        assert "/stats" in names
        assert "/resume" in names
        assert "/directories" in names

    def test_all_are_builtin_source(self, gemini: GeminiProvider) -> None:
        result = gemini.discover_commands("/tmp/nonexistent")
        assert all(isinstance(c, DiscoveredCommand) for c in result)
        assert all(c.source == "builtin" for c in result)

    def test_ignores_base_dir(self, gemini: GeminiProvider) -> None:
        result1 = gemini.discover_commands("/tmp/a")
        result2 = gemini.discover_commands("/tmp/b")
        assert [c.name for c in result1] == [c.name for c in result2]
