"""Provider protocol and shared event types for multi-agent CLI backends.

Pure definitions only — no imports from existing ccbot modules to avoid
circular dependencies. Every agent provider (Claude, Codex, Gemini) must
satisfy the ``AgentProvider`` protocol.

Event types:
  - SessionStartEvent: emitted when a new session is detected
  - AgentMessage: a parsed message from the agent's transcript
  - StatusUpdate: a parsed terminal status line

Capability descriptor:
  - ProviderCapabilities: declares what features the provider supports
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

# ── Event types ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SessionStartEvent:
    """Emitted when a provider session starts or is detected via hook."""

    session_id: str
    cwd: str
    transcript_path: str
    window_key: str  # e.g. "ccbot:@0"


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """A single parsed message from the agent's transcript."""

    session_id: str
    text: str
    role: Literal["user", "assistant"]
    content_type: Literal[
        "text", "thinking", "tool_use", "tool_result", "local_command"
    ]
    is_complete: bool = True
    tool_use_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class StatusUpdate:
    """Parsed terminal status line from the agent's pane."""

    session_id: str
    raw_text: str  # original text after spinner
    display_label: str  # short label like "…reading"
    is_interactive: bool = False
    ui_type: str | None = None  # "AskUserQuestion", "ExitPlanMode", etc.


# ── Capabilities ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Declares what features a provider supports.

    Immutable after construction — providers return a fixed instance.
    """

    name: str  # e.g. "claude", "codex", "gemini"
    launch_command: str  # e.g. "claude", "codex"
    supports_hook: bool = False
    supports_resume: bool = False
    supports_continue: bool = False
    supports_structured_transcript: bool = False
    transcript_format: Literal["jsonl", "plain"] = "jsonl"
    terminal_ui_patterns: tuple[str, ...] = ()
    builtin_commands: tuple[str, ...] = ()


# ── Provider protocol ────────────────────────────────────────────────────


@runtime_checkable
class AgentProvider(Protocol):
    """Protocol that every agent CLI provider must satisfy."""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def make_launch_args(
        self,
        resume_id: str | None = None,
        use_continue: bool = False,
    ) -> str:
        """Build CLI args string for launching the agent.

        Returns a string like ``--resume abc123`` or ``--continue``.
        Empty string for a fresh session.
        """
        ...

    def parse_hook_payload(self, payload: dict[str, Any]) -> SessionStartEvent | None:
        """Parse a hook's stdin JSON into a SessionStartEvent.

        Returns None if the payload is invalid or not from this provider.
        """
        ...

    def parse_transcript_line(self, line: str) -> dict[str, Any] | None:
        """Parse a single raw transcript line into a structured dict.

        Returns None for empty, invalid, or skipped lines.
        """
        ...

    def parse_transcript_entries(
        self,
        entries: list[dict[str, Any]],
        pending_tools: dict[str, Any],
    ) -> tuple[list[AgentMessage], dict[str, Any]]:
        """Parse a batch of transcript entries into AgentMessages.

        Returns (messages, updated_pending_tools).
        """
        ...

    def parse_terminal_status(self, pane_text: str) -> StatusUpdate | None:
        """Parse captured pane text into a StatusUpdate.

        Returns None if no status line or interactive UI is detected.
        """
        ...

    def discover_commands(self, base_dir: str) -> list[str]:
        """Discover available commands/skills from the provider's config.

        Returns command names (e.g. ["clear", "compact", "spec:work"]).
        """
        ...
