"""Tests for terminal_parser — regex-based detection of Claude Code UI elements."""

import pytest

from ccbot.terminal_parser import (
    extract_bash_output,
    extract_interactive_content,
    find_chrome_boundary,
    format_status_display,
    is_interactive_ui,
    is_likely_spinner,
    parse_status_line,
    strip_pane_chrome,
)

# ── is_likely_spinner ────────────────────────────────────────────────────


class TestIsLikelySpinner:
    @pytest.mark.parametrize(
        "char",
        ["·", "✻", "✽", "✶", "✳", "✢"],
        ids=[
            "middle_dot",
            "heavy_asterisk",
            "heavy_teardrop",
            "six_star",
            "eight_star",
            "cross",
        ],
    )
    def test_known_spinners(self, char: str):
        assert is_likely_spinner(char) is True

    @pytest.mark.parametrize(
        "char",
        ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        ids=[f"braille_{i}" for i in range(10)],
    )
    def test_braille_spinners(self, char: str):
        assert is_likely_spinner(char) is True

    @pytest.mark.parametrize(
        "char",
        ["─", "│", "┌", "┐", ">", "|"],
        ids=["h_line", "v_line", "corner_tl", "corner_tr", "gt", "pipe"],
    )
    def test_non_spinners_box_drawing(self, char: str):
        assert is_likely_spinner(char) is False

    @pytest.mark.parametrize(
        "char",
        ["A", "z", "0", " ", ""],
        ids=["upper_a", "lower_z", "digit", "space", "empty"],
    )
    def test_non_spinners_common(self, char: str):
        assert is_likely_spinner(char) is False

    def test_math_symbol_detected(self):
        assert is_likely_spinner("∑") is True

    def test_other_symbol_detected(self):
        assert is_likely_spinner("⚡") is True


# ── parse_status_line ────────────────────────────────────────────────────


_SEPARATOR = "─" * 30


class TestParseStatusLine:
    @pytest.mark.parametrize(
        ("spinner", "rest", "expected"),
        [
            ("·", "Working on task", "Working on task"),
            ("✻", "  Reading file  ", "Reading file"),
            ("✽", "Thinking deeply", "Thinking deeply"),
            ("✶", "Analyzing code", "Analyzing code"),
            ("✳", "Processing input", "Processing input"),
            ("✢", "Building project", "Building project"),
        ],
    )
    def test_spinner_chars(self, spinner: str, rest: str, expected: str):
        pane = f"some output\n{spinner}{rest}\n{_SEPARATOR}\n"
        assert parse_status_line(pane) == expected

    @pytest.mark.parametrize(
        ("spinner", "text"),
        [
            ("⠋", "Loading modules"),
            ("⠹", "Compiling assets"),
            ("⠏", "Fetching data"),
        ],
    )
    def test_braille_spinners_detected(self, spinner: str, text: str):
        pane = f"some output\n{spinner} {text}\n{_SEPARATOR}\n"
        assert parse_status_line(pane) == text

    @pytest.mark.parametrize(
        "pane",
        [
            pytest.param("just normal text\nno spinners here\n", id="no_spinner"),
            pytest.param("", id="empty"),
            pytest.param(
                f"some output\n· bullet point\nmore text\n{_SEPARATOR}\n",
                id="spinner_not_above_separator",
            ),
        ],
    )
    def test_returns_none(self, pane: str):
        assert parse_status_line(pane) is None

    def test_adaptive_scan_finds_distant_separator(self):
        pane = f"✻ Doing work\n{_SEPARATOR}\n" + "trailing\n" * 16
        assert parse_status_line(pane) == "Doing work"

    def test_ignores_bullet_points(self):
        pane = (
            "Here are some items:\n"
            "· first item\n"
            "· second item\n"
            "normal line\n"
            f"{_SEPARATOR}\n"
        )
        assert parse_status_line(pane) is None

    def test_bottom_up_scan_with_chrome(self):
        pane = f"output\n✻ Doing work\n{_SEPARATOR}\n❯\n"
        assert parse_status_line(pane) == "Doing work"

    def test_two_separator_layout(self):
        pane = (
            "output\n"
            "✶ Perusing… (3m 35s)\n"
            "\n"
            f"{_SEPARATOR}\n"
            "❯ \n"
            f"{_SEPARATOR}\n"
            "   ⎇ main  ~/Workspace/proj  ✱ Opus 4.6\n"
        )
        assert parse_status_line(pane) == "Perusing… (3m 35s)"

    def test_two_separator_no_blank_line(self):
        pane = (
            "output\n"
            "✶ Working hard\n"
            f"{_SEPARATOR}\n"
            "❯ \n"
            f"{_SEPARATOR}\n"
            "   ⎇ main  ✱ Opus 4.6\n"
        )
        assert parse_status_line(pane) == "Working hard"

    def test_uses_fixture(self, sample_pane_status_line: str):
        assert parse_status_line(sample_pane_status_line) == "Reading file src/main.py"


# ── extract_interactive_content ──────────────────────────────────────────


class TestExtractInteractiveContent:
    def test_exit_plan_mode(self, sample_pane_exit_plan: str):
        result = extract_interactive_content(sample_pane_exit_plan)
        assert result is not None
        assert result.name == "ExitPlanMode"
        assert "Would you like to proceed?" in result.content
        assert "ctrl-g to edit in" in result.content

    def test_exit_plan_mode_variant(self):
        pane = (
            "  Claude has written up a plan\n  ─────\n  Details here\n  Esc to cancel\n"
        )
        result = extract_interactive_content(pane)
        assert result is not None
        assert result.name == "ExitPlanMode"
        assert "Claude has written up a plan" in result.content

    def test_ask_user_multi_tab(self, sample_pane_ask_user_multi_tab: str):
        result = extract_interactive_content(sample_pane_ask_user_multi_tab)
        assert result is not None
        assert result.name == "AskUserQuestion"
        assert "←" in result.content

    def test_ask_user_single_tab(self, sample_pane_ask_user_single_tab: str):
        result = extract_interactive_content(sample_pane_ask_user_single_tab)
        assert result is not None
        assert result.name == "AskUserQuestion"
        assert "Enter to select" in result.content

    def test_permission_prompt(self, sample_pane_permission: str):
        result = extract_interactive_content(sample_pane_permission)
        assert result is not None
        assert result.name == "PermissionPrompt"
        assert "Do you want to proceed?" in result.content

    def test_restore_checkpoint(self):
        pane = (
            "  Restore the code to a previous state?\n"
            "  ─────\n"
            "  Some details\n"
            "  Enter to continue\n"
        )
        result = extract_interactive_content(pane)
        assert result is not None
        assert result.name == "RestoreCheckpoint"
        assert "Restore the code" in result.content

    def test_settings(self):
        pane = "  Settings: press tab to cycle\n  ─────\n  Option 1\n  Esc to cancel\n"
        result = extract_interactive_content(pane)
        assert result is not None
        assert result.name == "Settings"
        assert "Settings:" in result.content

    def test_select_model(self):
        pane = (
            " Select model\n"
            " Switch between Claude models.\n"
            "\n"
            " ❯ 1. Default (recommended) ✔  Opus 4.6\n"
            "   2. Sonnet                   Sonnet 4.6\n"
            "\n"
            " ▌▌▌ Medium effort ← → to adjust\n"
            "\n"
            " Enter to confirm · Esc to exit\n"
        )
        result = extract_interactive_content(pane)
        assert result is not None
        assert result.name == "SelectModel"
        assert "Select model" in result.content
        assert "Enter to confirm" in result.content

    @pytest.mark.parametrize(
        "pane",
        [
            pytest.param("$ echo hello\nhello\n$\n", id="no_ui"),
            pytest.param("", id="empty"),
        ],
    )
    def test_returns_none(self, pane: str):
        assert extract_interactive_content(pane) is None

    def test_min_gap_too_small_returns_none(self):
        pane = "  Do you want to proceed?\n  Esc to cancel\n"
        assert extract_interactive_content(pane) is None


# ── is_interactive_ui ────────────────────────────────────────────────────


class TestIsInteractiveUI:
    def test_true_when_ui_present(self, sample_pane_exit_plan: str):
        assert is_interactive_ui(sample_pane_exit_plan) is True

    def test_false_when_no_ui(self, sample_pane_no_ui: str):
        assert is_interactive_ui(sample_pane_no_ui) is False

    def test_false_for_empty_string(self):
        assert is_interactive_ui("") is False


# ── strip_pane_chrome ───────────────────────────────────────────────────


class TestStripPaneChrome:
    def test_strips_from_separator(self):
        lines = [
            "some output",
            "more output",
            "─" * 30,
            "❯",
            "─" * 30,
            "  [Opus 4.6] Context: 34%",
        ]
        assert strip_pane_chrome(lines) == ["some output", "more output"]

    def test_no_separator_returns_all(self):
        lines = ["line 1", "line 2", "line 3"]
        assert strip_pane_chrome(lines) == lines

    def test_short_separator_not_triggered(self):
        lines = ["output", "─" * 10, "more output"]
        assert strip_pane_chrome(lines) == lines

    def test_adaptive_scan_finds_distant_separator(self):
        # Separator at line 0 with 15 content lines — adaptive scan finds it
        lines = ["─" * 30] + [f"line {i}" for i in range(14)]
        assert strip_pane_chrome(lines) == []

    def test_content_above_separator_preserved(self):
        content = [f"line {i}" for i in range(20)]
        chrome = ["─" * 30, "❯", "─" * 30, "  [Opus 4.6] Context: 34%"]
        lines = content + chrome
        assert strip_pane_chrome(lines) == content


# ── extract_bash_output ─────────────────────────────────────────────────


class TestExtractBashOutput:
    def test_extracts_command_output(self):
        pane = "some context\n! echo hello\n⎿ hello\n"
        result = extract_bash_output(pane, "echo hello")
        assert result is not None
        assert "! echo hello" in result
        assert "hello" in result

    def test_command_not_found_returns_none(self):
        pane = "some context\njust normal output\n"
        assert extract_bash_output(pane, "echo hello") is None

    def test_chrome_stripped(self):
        pane = (
            "some context\n"
            "! ls\n"
            "⎿ file.txt\n"
            + "─" * 30
            + "\n"
            + "❯\n"
            + "─" * 30
            + "\n"
            + "  [Opus 4.6] Context: 34%\n"
        )
        result = extract_bash_output(pane, "ls")
        assert result is not None
        assert "file.txt" in result
        assert "Opus" not in result

    def test_prefix_match_long_command(self):
        pane = "! long_comma…\n⎿ output\n"
        result = extract_bash_output(pane, "long_command_that_gets_truncated")
        assert result is not None
        assert "output" in result

    def test_trailing_blank_lines_stripped(self):
        pane = "! echo hi\n⎿ hi\n\n\n"
        result = extract_bash_output(pane, "echo hi")
        assert result is not None
        assert not result.endswith("\n")


# ── format_status_display ───────────────────────────────────────────────


class TestFormatStatusDisplay:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Reading src/foo.py", "…reading"),
            ("Thinking about the problem", "…thinking"),
            ("Reasoning through options", "…thinking"),
            ("Editing main.py line 42", "…editing"),
            ("Writing to file", "…writing"),
            ("Running bash command", "…running"),
            ("Searching for pattern", "…searching"),
            ("grep -r foo .", "…searching"),
            ("glob **/*.py", "…searching"),
            ("Building the project", "…building"),
            ("compiling module", "…building"),
            ("Installing dependencies", "…installing"),
            ("Fetching remote refs", "…fetching"),
            ("git push origin main", "…pushing"),
            ("git pull --rebase", "…pulling"),
            ("git clone https://repo", "…cloning"),
            ("git commit -m msg", "…committing"),
            ("Deploying to prod", "…deploying"),
            ("Debugging crash", "…debugging"),
            ("Formatting code", "…formatting"),
            ("Linting files", "…linting"),
            ("Downloading artifact", "…downloading"),
            ("Uploading results", "…uploading"),
            ("Testing connection", "…testing"),
            ("Deleting old files", "…deleting"),
            ("Creating new module", "…creating"),
            ("Checking types", "…checking"),
            ("Updating dependencies", "…updating"),
            ("Analyzing output", "…analyzing"),
            ("Parsing JSON", "…parsing"),
            ("Verifying results", "…verifying"),
            ("esc to interrupt · working", "…working"),
            ("Something completely novel", "…working"),
            ("", "…working"),
        ],
    )
    def test_known_patterns(self, raw: str, expected: str) -> None:
        assert format_status_display(raw) == expected

    def test_case_insensitive(self) -> None:
        assert format_status_display("READING file") == "…reading"

    def test_first_word_priority(self) -> None:
        assert format_status_display("Writing tests for module") == "…writing"

    def test_fallback_to_full_string(self) -> None:
        assert format_status_display("foo bar testing baz") == "…testing"


# ── find_chrome_boundary ──────────────────────────────────────────────


class TestFindChromeBoundary:
    def test_empty_lines(self):
        assert find_chrome_boundary([]) is None

    def test_no_separator(self):
        assert find_chrome_boundary(["line 1", "line 2"]) is None

    def test_single_separator(self):
        lines = ["output", "more output", "─" * 30, "❯"]
        assert find_chrome_boundary(lines) == 2

    def test_two_separators(self):
        lines = [
            "output",
            "─" * 30,
            "❯ ",
            "─" * 30,
            "  [Opus 4.6] Context: 34%",
        ]
        assert find_chrome_boundary(lines) == 1

    def test_separator_far_from_bottom(self):
        lines = ["output"] * 50 + ["─" * 30, "❯", "─" * 30, "  status"]
        assert find_chrome_boundary(lines) == 50

    def test_content_separator_not_chrome(self):
        lines = [
            "─" * 30,
            "x" * 100,
            "─" * 30,
            "❯",
        ]
        # First separator has long content below it, so only second is chrome
        assert find_chrome_boundary(lines) == 2


# ── Adaptive terminal size tests ─────────────────────────────────────


class TestVariableTerminalSizes:
    def _build_pane(self, content_lines: int) -> str:
        content = [f"line {i}" for i in range(content_lines)]
        status = "✻ Working on task"
        sep = "─" * 30
        chrome = [sep, "❯ ", sep, "  ⎇ main  ✱ Opus 4.6"]
        return "\n".join(content + [status] + chrome)

    @pytest.mark.parametrize("rows", [24, 50, 100], ids=["24row", "50row", "100row"])
    def test_status_detected_any_size(self, rows: int):
        pane = self._build_pane(content_lines=rows - 5)
        assert parse_status_line(pane) == "Working on task"

    @pytest.mark.parametrize("rows", [24, 50, 100], ids=["24row", "50row", "100row"])
    def test_chrome_stripped_any_size(self, rows: int):
        content = [f"line {i}" for i in range(rows - 5)]
        status = "✻ Working on task"
        sep = "─" * 30
        chrome = [sep, "❯ ", sep, "  ⎇ main  ✱ Opus 4.6"]
        lines = content + [status] + chrome
        result = strip_pane_chrome(lines)
        assert result == content + [status]

    def test_pane_rows_optimization(self):
        pane = self._build_pane(content_lines=80)
        assert parse_status_line(pane, pane_rows=100) == "Working on task"

    def test_extra_padding_below_separator(self):
        lines = [
            "output",
            "─" * 30,
            "❯ ",
            "─" * 30,
            "  status bar",
            "",
            "",
        ]
        assert strip_pane_chrome(lines) == ["output"]
