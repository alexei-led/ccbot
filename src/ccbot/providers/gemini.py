"""Gemini CLI provider — Google's terminal agent behind AgentProvider protocol.

Gemini CLI uses directory-scoped sessions with automatic persistence. Resume
uses ``--resume <index|latest>`` flag syntax (index number or "latest", not
a session UUID). No SessionStart hook — session detection requires external
wrapping.

Terminal UI: Gemini CLI uses ``@inquirer/select`` for interactive prompts.
Permission prompts start with "Action Required" and list numbered options
with a ``●`` (U+25CF) marker on the selected choice.

Transcript format: single JSON file per session (NOT JSONL) with structure:
  ``{sessionId, projectHash, startTime, lastUpdated, messages: [...]}``
Messages use ``type`` field with values ``"user"`` / ``"gemini"`` (not
``"assistant"``), and ``content`` is a plain string (not content blocks).
"""

import json
import re
from typing import Any, cast

from ccbot.providers._jsonl import JsonlProvider
from ccbot.providers.base import (
    AgentMessage,
    ContentType,
    MessageRole,
    ProviderCapabilities,
    SessionStartEvent,
    StatusUpdate,
)
from ccbot.terminal_parser import UIPattern, extract_interactive_content

# Gemini CLI known slash commands
_GEMINI_BUILTINS: dict[str, str] = {
    "/chat": "Save, resume, list, or delete named sessions",
    "/clear": "Clear screen and chat context",
    "/compress": "Summarize chat context to save tokens",
    "/copy": "Copy last response to clipboard",
    "/diff": "View file changes",
    "/directories": "Manage accessible directories",
    "/help": "Display available commands",
    "/mcp": "List MCP servers and tools",
    "/memory": "Show or manage GEMINI.md context",
    "/model": "Switch model mid-session",
    "/restore": "List or restore project state checkpoints",
    "/skills": "Enable, list, or reload agent skills",
    "/stats": "Show session statistics",
    "/tools": "List accessible tools",
    "/vim": "Toggle Vim input mode",
}

# Gemini role → our MessageRole mapping
_GEMINI_ROLE_MAP: dict[str, MessageRole] = {
    "user": "user",
    "gemini": "assistant",
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
        supports_continue=True,
        supports_structured_transcript=True,
        transcript_format="jsonl",
        terminal_ui_patterns=("PermissionPrompt",),
        uses_pane_title=True,
        builtin_commands=tuple(_GEMINI_BUILTINS.keys()),
    )

    _BUILTINS = _GEMINI_BUILTINS

    def make_launch_args(
        self,
        resume_id: str | None = None,
        use_continue: bool = False,
    ) -> str:
        """Build Gemini CLI args for launching or resuming a session.

        Resume uses ``--resume <index|latest>`` — accepts a numeric index
        or ``"latest"``, NOT a UUID.
        Continue uses ``--resume latest`` to pick up the most recent session.
        """
        if resume_id:
            return f"--resume {resume_id}"
        if use_continue:
            return "--resume latest"
        return ""

    # ── Gemini-specific transcript parsing ────────────────────────────

    def parse_transcript_line(self, line: str) -> dict[str, Any] | None:
        """Parse a line from a Gemini transcript.

        Gemini sessions are single JSON files, not JSONL. When read line-by-line
        by the monitor (which streams lines), individual lines won't be valid JSON.
        This method handles both cases gracefully.
        """
        if not line or not line.strip():
            return None
        try:
            result = json.loads(line)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None

    def parse_transcript_entries(
        self,
        entries: list[dict[str, Any]],
        pending_tools: dict[str, Any],
    ) -> tuple[list[AgentMessage], dict[str, Any]]:
        """Parse Gemini transcript entries into AgentMessages.

        Gemini messages use ``type`` field ("user"/"gemini") instead of ``role``,
        and ``content`` is a plain string (not content blocks).  ``toolCalls``
        is a separate array field.
        """
        messages: list[AgentMessage] = []
        pending = dict(pending_tools)

        for entry in entries:
            # Support both top-level messages and entries from the messages array
            msg_type = entry.get("type", "")
            role = _GEMINI_ROLE_MAP.get(msg_type)
            if not role:
                continue

            content = entry.get("content", "")
            text = content if isinstance(content, str) else ""
            content_type: ContentType = "text"

            # Track tool calls from gemini messages
            tool_calls = entry.get("toolCalls", [])
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict) and tc.get("id"):
                        pending[tc["id"]] = tc.get("name", "unknown")
                        content_type = "tool_use"

            if text:
                messages.append(
                    AgentMessage(
                        text=text,
                        role=cast(MessageRole, role),
                        content_type=content_type,
                        timestamp=entry.get("timestamp"),
                    )
                )

        return messages, pending

    def is_user_transcript_entry(self, entry: dict[str, Any]) -> bool:
        """Check if this Gemini entry is a human turn."""
        return entry.get("type") == "user"

    def parse_history_entry(self, entry: dict[str, Any]) -> AgentMessage | None:
        """Parse a single Gemini transcript entry for history display."""
        msg_type = entry.get("type", "")
        role = _GEMINI_ROLE_MAP.get(msg_type)
        if not role:
            return None
        content = entry.get("content", "")
        text = content if isinstance(content, str) else ""
        if not text:
            return None
        return AgentMessage(
            text=text,
            role=cast(MessageRole, role),
            content_type="text",
            timestamp=entry.get("timestamp"),
        )

    def parse_hook_payload(
        self,
        payload: dict[str, Any],  # noqa: ARG002 — protocol signature
    ) -> SessionStartEvent | None:
        return None

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
