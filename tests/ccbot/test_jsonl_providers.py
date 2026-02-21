"""Provider-specific tests for Codex and Gemini (JsonlProvider subclasses).

Tests behavior that differs from the generic contract tests: resume syntax,
builtin command sets, capability flags, and shared JSONL parsing edge cases.
"""

import pytest

from ccbot.providers._jsonl import extract_content_blocks, parse_jsonl_line
from ccbot.providers.codex import CodexProvider
from ccbot.providers.gemini import GeminiProvider

# ── Shared hookless-provider tests (parametrized) ────────────────────────

HOOKLESS_PROVIDERS = [CodexProvider, GeminiProvider]


@pytest.fixture(params=HOOKLESS_PROVIDERS, ids=lambda cls: cls.__name__)
def hookless(request: pytest.FixtureRequest):
    return request.param()


class TestHooklessCapabilities:
    def test_hookless_flags(self, hookless) -> None:
        caps = hookless.capabilities
        assert caps.supports_hook is False
        assert caps.supports_continue is False

    def test_invalid_resume_id_raises(self, hookless) -> None:
        with pytest.raises(ValueError, match="Invalid resume_id"):
            hookless.make_launch_args(resume_id="abc; rm -rf /")


# ── Codex-specific ───────────────────────────────────────────────────────


class TestCodexLaunchArgs:
    def test_resume_uses_subcommand(self) -> None:
        codex = CodexProvider()
        result = codex.make_launch_args(resume_id="abc-123")
        assert result == "exec resume abc-123"


class TestCodexCommands:
    def test_returns_builtins(self) -> None:
        codex = CodexProvider()
        result = codex.discover_commands("/tmp/nonexistent")
        names = [c.name for c in result]
        assert len(result) == len(codex.capabilities.builtin_commands)
        for cmd in ("/exit", "/model", "/status", "/mode"):
            assert cmd in names


# ── Codex capabilities ───────────────────────────────────────────────────


class TestCodexCapabilities:
    def test_no_terminal_ui_patterns(self) -> None:
        codex = CodexProvider()
        assert codex.capabilities.terminal_ui_patterns == ()


# ── Gemini-specific ──────────────────────────────────────────────────────


class TestGeminiCapabilities:
    def test_declares_permission_prompt(self) -> None:
        gemini = GeminiProvider()
        assert "PermissionPrompt" in gemini.capabilities.terminal_ui_patterns


class TestGeminiLaunchArgs:
    def test_resume_uses_flag(self) -> None:
        gemini = GeminiProvider()
        result = gemini.make_launch_args(resume_id="abc-123")
        assert result == "--resume abc-123"


class TestGeminiTerminalStatus:
    """Gemini CLI interactive UI detection via parse_terminal_status."""

    SHELL_PERMISSION_PANE = (
        "some previous output\n"
        "\n"
        "Action Required\n"
        "? Shell pwd && git branch --show-current && git status -s && ls -F "
        "[current working directory /Users/alexei/Workspace] "
        "(Check current directory, git branch, status, and list …\n"
        "pwd && git branch --show-current && git status -s && ls -F\n"
        "Allow execution of: 'pwd, git, git, ls'?\n"
        "● 1. Allow once\n"
        "  2. Allow for this session\n"
        "  3. Allow for all future sessions\n"
        "  4. No, suggest changes (esc\n"
    )

    WRITE_PERMISSION_PANE = (
        "✦ I'll create the file now.\n"
        "\n"
        "Action Required\n"
        "? WriteFile /tmp/test.txt (Create test file)\n"
        "Allow write to: '/tmp/test.txt'?\n"
        "● 1. Allow once\n"
        "  2. Allow for this session\n"
        "  3. Allow for all future sessions\n"
        "  4. No, suggest changes (esc)\n"
    )

    def test_detects_shell_permission(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(self.SHELL_PERMISSION_PANE)
        assert status is not None
        assert status.is_interactive is True
        assert status.ui_type == "PermissionPrompt"

    def test_detects_write_permission(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(self.WRITE_PERMISSION_PANE)
        assert status is not None
        assert status.is_interactive is True
        assert status.ui_type == "PermissionPrompt"

    def test_permission_content_includes_options(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(self.SHELL_PERMISSION_PANE)
        assert status is not None
        assert "Allow once" in status.raw_text
        assert "Allow for this session" in status.raw_text
        assert "Action Required" in status.raw_text

    def test_returns_none_for_non_interactive_pane(self) -> None:
        gemini = GeminiProvider()
        pane = "Working on something...\nProcessing files\n"
        status = gemini.parse_terminal_status(pane)
        assert status is None

    def test_returns_none_for_normal_output(self) -> None:
        gemini = GeminiProvider()
        pane = "\u2726 Here is your answer.\n\nSome normal output text.\n> \n"
        status = gemini.parse_terminal_status(pane)
        assert status is None

    def test_returns_none_for_gemini_chrome(self) -> None:
        gemini = GeminiProvider()
        pane = (
            "✦ Here is your answer.\n"
            "[INSERT] ~/Workspace/ccbot (main)           "
            "no sandbox (see /docs)           "
            "/model Auto (Gemini 3) 100% context left | 375.5 MB\n"
        )
        status = gemini.parse_terminal_status(pane)
        assert status is None

    def test_no_interactive_when_bottom_marker_missing(self) -> None:
        pane = "Action Required\n? Shell ls -la\nAllow execution of: 'ls'?\n"
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(pane)
        assert status is None

    def test_no_false_positive_from_response_text(self) -> None:
        pane = (
            "\u2726 Here's what you need to know:\n"
            "\n"
            "Action Required: You must update the config file.\n"
            "Edit settings.json and set the flag to true.\n"
            "Then restart the service.\n"
            "> \n"
        )
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(pane)
        assert status is None


class TestGeminiPaneTitleStatus:
    """Gemini CLI pane-title-based state detection."""

    def test_working_title_returns_working_status(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status("some output", pane_title="Working: ✦")
        assert status is not None
        assert status.is_interactive is False
        assert status.display_label == "\u2026working"

    def test_action_required_title_with_matching_content(self) -> None:
        gemini = GeminiProvider()
        pane = (
            "Action Required\n"
            "? Shell ls\n"
            "Allow execution of: 'ls'?\n"
            "● 1. Allow once\n"
            "  2. No, suggest changes (esc\n"
        )
        status = gemini.parse_terminal_status(pane, pane_title="Action Required: ✋")
        assert status is not None
        assert status.is_interactive is True
        assert status.ui_type == "PermissionPrompt"

    def test_action_required_title_without_matching_content(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status(
            "some output", pane_title="Action Required: ✋"
        )
        assert status is not None
        assert status.is_interactive is True
        assert status.ui_type == "PermissionPrompt"

    def test_ready_title_returns_none(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status("some output", pane_title="Ready: ◇")
        assert status is None

    def test_empty_pane_title_uses_content_only(self) -> None:
        gemini = GeminiProvider()
        status = gemini.parse_terminal_status("normal output\n", pane_title="")
        assert status is None


class TestGeminiCommands:
    def test_returns_builtins(self) -> None:
        gemini = GeminiProvider()
        result = gemini.discover_commands("/tmp/nonexistent")
        names = [c.name for c in result]
        assert len(result) == len(gemini.capabilities.builtin_commands)
        for cmd in ("/clear", "/model", "/stats", "/resume", "/directories"):
            assert cmd in names


# ── JSONL parsing edge cases (extract_content_blocks) ────────────────────


class TestParseJsonlLine:
    def test_json_array_returns_none(self) -> None:
        assert parse_jsonl_line("[1, 2, 3]") is None

    def test_json_string_returns_none(self) -> None:
        assert parse_jsonl_line('"just a string"') is None

    def test_json_number_returns_none(self) -> None:
        assert parse_jsonl_line("42") is None


class TestExtractContentBlocks:
    def test_string_content(self) -> None:
        text, ct, pending = extract_content_blocks("hello world", {})
        assert text == "hello world"
        assert ct == "text"

    def test_non_list_non_string_returns_empty(self) -> None:
        text, ct, pending = extract_content_blocks(42, {})
        assert text == ""
        assert ct == "text"

    def test_none_content_returns_empty(self) -> None:
        text, ct, pending = extract_content_blocks(None, {})
        assert text == ""
        assert ct == "text"

    def test_non_dict_blocks_skipped(self) -> None:
        text, ct, pending = extract_content_blocks(["not a dict", 42], {})
        assert text == ""

    def test_tool_use_tracked_in_pending(self) -> None:
        blocks = [{"type": "tool_use", "id": "t1", "name": "Read"}]
        _, ct, pending = extract_content_blocks(blocks, {})
        assert ct == "tool_use"
        assert pending == {"t1": "Read"}

    def test_tool_result_clears_pending(self) -> None:
        blocks = [{"type": "tool_result", "tool_use_id": "t1"}]
        _, ct, pending = extract_content_blocks(blocks, {"t1": "Read"})
        assert ct == "tool_result"
        assert "t1" not in pending

    def test_tool_result_without_id_does_not_pop_empty(self) -> None:
        blocks = [{"type": "tool_result"}]
        pending = {"t1": "Read"}
        _, _, result = extract_content_blocks(blocks, pending)
        assert result == {"t1": "Read"}
