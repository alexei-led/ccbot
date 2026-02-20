"""Gemini CLI provider — Google's terminal agent behind AgentProvider protocol.

MVP implementation: Gemini CLI uses directory-scoped sessions with automatic
persistence. Resume uses ``--resume <id>`` flag syntax. No SessionStart hook —
session detection requires external wrapping. Terminal UI is a stable GUI-like
renderer with sticky headers; patterns TBD pending empirical characterization.
"""

import json
import logging
import re
from typing import Any, cast

from ccbot.providers.base import (
    AgentMessage,
    ContentType,
    DiscoveredCommand,
    MessageRole,
    ProviderCapabilities,
    SessionStartEvent,
    StatusUpdate,
)

logger = logging.getLogger(__name__)

# Alphanumeric + hyphens/underscores — rejects shell metacharacters.
_RESUME_ID_RE = re.compile(r"^[\w-]+$")

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


class GeminiProvider:
    """AgentProvider implementation for Google Gemini CLI."""

    _CAPS = ProviderCapabilities(
        name="gemini",
        launch_command="gemini",
        supports_hook=False,
        supports_resume=True,
        supports_continue=False,
        supports_structured_transcript=True,
        transcript_format="jsonl",
        terminal_ui_patterns=(),
        builtin_commands=tuple(_GEMINI_BUILTINS.keys()),
    )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._CAPS

    def make_launch_args(
        self,
        resume_id: str | None = None,
        use_continue: bool = False,  # noqa: ARG002
    ) -> str:
        """Build Gemini CLI args for launching or resuming a session.

        Resume uses ``--resume <id>`` flag syntax.
        Continue is not supported.
        """
        if resume_id:
            if not _RESUME_ID_RE.match(resume_id):
                raise ValueError(f"Invalid resume_id: {resume_id!r}")
            return f"--resume {resume_id}"
        return ""

    def parse_hook_payload(
        self,
        payload: dict[str, Any],  # noqa: ARG002
    ) -> SessionStartEvent | None:
        """Gemini has no SessionStart hook — always returns None."""
        return None

    def parse_transcript_line(self, line: str) -> dict[str, Any] | None:
        """Parse a single JSONL transcript line."""
        if not line or not line.strip():
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def parse_transcript_entries(
        self,
        entries: list[dict[str, Any]],
        pending_tools: dict[str, Any],
    ) -> tuple[list[AgentMessage], dict[str, Any]]:
        """Parse Gemini transcript entries into AgentMessages with tool tracking."""
        messages: list[AgentMessage] = []
        pending = dict(pending_tools)

        for entry in entries:
            msg_type = entry.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue
            content = entry.get("message", {}).get("content", "")
            text, content_type, pending = self._extract_content(content, pending)
            if text:
                messages.append(
                    AgentMessage(
                        session_id="",
                        text=text,
                        role=cast(MessageRole, msg_type),
                        content_type=content_type,
                    )
                )
        return messages, pending

    @staticmethod
    def _extract_content(
        content: Any, pending: dict[str, Any]
    ) -> tuple[str, ContentType, dict[str, Any]]:
        """Extract text and track tool_use/tool_result from content blocks."""
        if isinstance(content, str):
            return content, "text", pending
        if not isinstance(content, list):
            return "", "text", pending

        text = ""
        content_type: ContentType = "text"
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text += block.get("text", "")
            elif btype == "tool_use" and block.get("id"):
                pending[block["id"]] = block.get("name", "unknown")
                content_type = "tool_use"
            elif btype == "tool_result":
                pending.pop(block.get("tool_use_id", ""), None)
                content_type = "tool_result"
        return text, content_type, pending

    def parse_terminal_status(self, pane_text: str) -> StatusUpdate | None:
        """Parse Gemini terminal pane for status information.

        MVP: returns a basic status update for non-empty pane text.
        Gemini TUI patterns are not yet characterized — no interactive UI
        detection until patterns are empirically discovered.
        """
        if not pane_text or not pane_text.strip():
            return None
        last_line = pane_text.strip().splitlines()[-1].strip()
        if not last_line:
            return None
        return StatusUpdate(
            session_id="",
            raw_text=last_line,
            display_label=last_line,
        )

    def extract_bash_output(self, pane_text: str, command: str) -> str | None:
        """Extract bash command output from pane text.

        Gemini uses ``!`` prefix for shell commands.
        Exact format is assumed pending empirical verification.
        """
        if not pane_text or not command:
            return None
        cmd_prefix = command[:10]
        for line in pane_text.splitlines():
            if line.strip().startswith(f"! {cmd_prefix}"):
                return line.strip()
        return None

    def is_user_transcript_entry(self, entry: dict[str, Any]) -> bool:
        return entry.get("type") == "user"

    def parse_history_entry(self, entry: dict[str, Any]) -> AgentMessage | None:
        """Parse a single transcript entry for history display."""
        msg_type = entry.get("type", "")
        if msg_type not in ("user", "assistant"):
            return None
        content = entry.get("message", {}).get("content", "")
        if isinstance(content, list):
            text = "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        if not text:
            return None
        return AgentMessage(
            session_id="",
            text=text,
            role=cast(MessageRole, msg_type),
            content_type="text",
        )

    def discover_commands(
        self,
        base_dir: str,  # noqa: ARG002
    ) -> list[DiscoveredCommand]:
        """Return Gemini built-in slash commands (no custom command discovery)."""
        return [
            DiscoveredCommand(name=name, description=desc, source="builtin")
            for name, desc in _GEMINI_BUILTINS.items()
        ]
