"""Gemini CLI provider — Google's terminal agent behind AgentProvider protocol.

Gemini CLI uses directory-scoped sessions with automatic persistence. Resume
uses ``--resume <id>`` flag syntax. No SessionStart hook — session detection
requires external wrapping.

Terminal UI: Gemini CLI uses ``@inquirer/select`` for interactive prompts.
Permission prompts start with "Action Required" and list numbered options
with a ``●`` (U+25CF) marker on the selected choice.
"""

import re

from ccbot.providers._jsonl import JsonlProvider
from ccbot.providers.base import ProviderCapabilities, StatusUpdate
from ccbot.terminal_parser import UIPattern, extract_interactive_content

# Gemini CLI known slash commands.
_GEMINI_BUILTINS: dict[str, str] = {
    "/clear": "Clear screen and chat context",
    "/model": "Switch model mid-session",
    "/compress": "Summarize chat context to save tokens",
    "/copy": "Copy last response to clipboard",
    "/help": "Display available commands",
    "/commands": "Manage custom commands",
    "/mcp": "List MCP servers and tools",
    "/stats": "Show session statistics",
    "/resume": "Browse and select previous sessions",
    "/bug": "File issue or bug report",
    "/directories": "Manage accessible directories",
}

# ── Gemini CLI UI patterns ──────────────────────────────────────────────
#
# Gemini uses @inquirer/select for permission prompts.  The structure is:
#
#   Action Required
#   ? Shell <command> [current working directory <path>] (<description>…
#   <command>
#   Allow execution of: '<tools>'?
#   ● 1. Allow once
#     2. Allow for this session
#     3. Allow for all future sessions
#     4. No, suggest changes (esc
#
# For file writes: "? WriteFile <path>" instead of "? Shell <command>".
# The ● (U+25CF) marks the selected option; (esc is always on the last line.
#
# We match on structural markers rather than exact wording for resilience
# against prompt text changes.

GEMINI_UI_PATTERNS: list[UIPattern] = [
    UIPattern(
        name="PermissionPrompt",
        top=(
            # "Action Required" header (bold in terminal, plain in capture)
            re.compile(r"^\s*Action Required"),
        ),
        bottom=(
            # Last option always ends with "(esc" (possibly truncated by pane width)
            re.compile(r"\(esc"),
            # Fallback: a numbered "No" option (the cancel choice)
            re.compile(r"^\s*\d+\.\s+No\b"),
        ),
    ),
]


class GeminiProvider(JsonlProvider):
    """AgentProvider implementation for Google Gemini CLI."""

    _CAPS = ProviderCapabilities(
        name="gemini",
        launch_command="gemini",
        supports_hook=False,
        supports_resume=True,
        supports_continue=False,
        supports_structured_transcript=True,
        transcript_format="jsonl",
        terminal_ui_patterns=("PermissionPrompt",),
        uses_pane_title=True,
        builtin_commands=tuple(_GEMINI_BUILTINS.keys()),
    )

    _BUILTINS = _GEMINI_BUILTINS

    def parse_terminal_status(
        self, pane_text: str, *, pane_title: str = ""
    ) -> StatusUpdate | None:
        """Parse Gemini CLI pane for status via title and interactive UI.

        Gemini CLI sets pane title via OSC escape sequences:
          - ``Working: ✦`` (U+2726) — agent is processing
          - ``Action Required: ✋`` (U+270B) — needs user input
          - ``Ready: ◇`` (U+25C7) — idle / waiting for input

        Title-based detection is checked first (most reliable), then
        pane content is scanned for interactive UI patterns.
        """
        # 1. Working title → non-interactive status
        if "\u2726" in pane_title:  # ✦
            return StatusUpdate(raw_text="working", display_label="\u2026working")

        # 2. Action Required title → check content for specific UI
        action_required = "\u270b" in pane_title  # ✋

        # 3. Pane content for interactive UI details
        interactive = extract_interactive_content(pane_text, GEMINI_UI_PATTERNS)
        if interactive:
            return StatusUpdate(
                raw_text=interactive.content,
                display_label=interactive.name,
                is_interactive=True,
                ui_type=interactive.name,
            )

        # 4. Title says action required but content didn't match patterns
        if action_required:
            return StatusUpdate(
                raw_text="Action Required",
                display_label="PermissionPrompt",
                is_interactive=True,
                ui_type="PermissionPrompt",
            )

        # 5. Ready title or unknown — no status (let activity heuristic handle)
        return None
