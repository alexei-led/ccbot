"""Pi coding agent provider — ``@mariozechner/pi-coding-agent`` behind AgentProvider.

Pi is a Node.js-based CLI with JSONL session transcripts (v3 format) and no
hook subsystem; session discovery therefore follows the Codex/Gemini pattern:
scan ``~/.pi/agent/sessions/`` for the newest transcript whose header ``cwd``
matches the window working directory.

Session path:  ``~/.pi/agent/sessions/--<encoded-cwd>--/<timestamp>_<uuid>.jsonl``

CWD encoding strips leading slashes, replaces ``/``, ``\\``, and ``:`` with
``-``, then wraps with ``--`` delimiters.  The canonical session id lives in
the header line ``{"type":"session","id":"<uuid>","cwd":"...","version":3}``
— the filename prefix is just a timestamp.

Resume strategy: always use ``--session <path>``.  ``--resume`` opens pi's
interactive picker, which ccgram can't drive over ``send_keys``.  Pi accepts
both a transcript path and a (partial) UUID for ``--session``, so we route
everything through it after ``shlex.quote`` for safety.
"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any

from ccgram.providers._jsonl import JsonlProvider, parse_jsonl_line
from ccgram.providers.base import (
    AgentMessage,
    DiscoveredCommand,
    ProviderCapabilities,
    SessionStartEvent,
)
from ccgram.providers.pi_format import (
    Pending,
    normalize_pending,
    parse_assistant,
    parse_bash_execution,
    parse_tool_result,
    parse_user,
    read_session_header,
)

_PI_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"

# Cap transcript age when the pane is dead — guards against picking up an
# unrelated historical transcript for the same cwd.
_STALE_TRANSCRIPT_MAX_AGE_SECS = 120.0

# How many recent session files to inspect when searching for a cwd match.
_DISCOVERY_SCAN_LIMIT = 20

_PI_BUILTINS: dict[str, str] = {
    "/clear": "Clear conversation history",
    "/compact": "Summarize older messages to save tokens",
    "/export": "Export session as HTML",
    "/fork": "Branch the current session into a new file",
    "/model": "Switch active model",
    "/models": "List available models",
    "/new": "Start a new session",
    "/resume": "Browse past sessions",
    "/share": "Share session via gist",
    "/thinking": "Change reasoning level",
    "/tools": "List available tools",
    "/tree": "Navigate the session history tree",
}


def encode_cwd_dirname(cwd: str) -> str:
    """Encode a working directory into pi's session subdirectory name.

    Matches pi's own encoding: strip leading slash, then replace ``/``, ``\\``
    and ``:`` with ``-``, then wrap with ``--``.  Root (``/``) renders as
    ``----`` to stay round-trippable.
    """
    stripped = cwd.lstrip("/\\")
    # Also drop trailing separators so "/tmp/foo/" and "/tmp/foo" collide correctly.
    stripped = stripped.rstrip("/\\")
    encoded = stripped.replace("/", "-").replace("\\", "-").replace(":", "-")
    return f"--{encoded}--"


def _candidate_transcripts(cwd: str) -> list[tuple[float, Path]]:
    """Return ``(mtime, path)`` tuples for this cwd's sessions, newest first."""
    session_dir = _PI_SESSIONS_DIR / encode_cwd_dirname(cwd)
    if not session_dir.is_dir():
        return []
    results: list[tuple[float, Path]] = []
    try:
        for entry in session_dir.iterdir():
            if entry.suffix == ".jsonl" and entry.is_file():
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                results.append((mtime, entry))
    except OSError:
        return []
    results.sort(key=lambda pair: pair[0], reverse=True)
    return results


def _parse_message_entry(
    role: str,
    msg: dict[str, Any],
    pending: Pending,
) -> tuple[list[AgentMessage], Pending]:
    """Dispatch one envelope's inner ``message`` to the role-specific parser."""
    if role == "user":
        return parse_user(msg), pending
    if role == "assistant":
        return parse_assistant(msg, pending)
    if role == "toolResult":
        return parse_tool_result(msg, pending)
    if role == "bashExecution":
        return parse_bash_execution(msg), pending
    # branchSummary, compactionSummary, custom → no relay output for v1
    return [], pending


class PiProvider(JsonlProvider):
    """AgentProvider implementation for the pi coding agent CLI."""

    _CAPS = ProviderCapabilities(
        name="pi",
        launch_command="pi",
        supports_hook=False,
        supports_hook_events=False,
        supports_resume=True,
        supports_continue=True,
        supports_structured_transcript=True,
        supports_incremental_read=True,
        transcript_format="jsonl",
        builtin_commands=tuple(_PI_BUILTINS.keys()),
        supports_user_command_discovery=False,
        supports_status_snapshot=False,
        supports_mailbox_delivery=True,
    )

    _BUILTINS = _PI_BUILTINS

    # ── Launch ───────────────────────────────────────────────────────────

    def make_launch_args(
        self,
        resume_id: str | None = None,
        use_continue: bool = False,
    ) -> str:
        """Build CLI args.  Prefers ``--session`` (non-interactive)."""
        if resume_id:
            return f"--session {shlex.quote(resume_id)}"
        if use_continue:
            return "--continue"
        return ""

    # ── Transcript parsing ───────────────────────────────────────────────

    def parse_transcript_line(self, line: str) -> dict[str, Any] | None:
        """Unwrap pi's ``message`` envelope into a flat dict keyed by role.

        For session/model_change/etc. entries the raw dict passes through so
        ``apply_task_entries`` and friends can still inspect them.
        """
        raw = parse_jsonl_line(line)
        if raw is None:
            return None
        if raw.get("type") != "message":
            return raw
        inner = raw.get("message")
        if not isinstance(inner, dict):
            return None
        role = inner.get("role")
        if not isinstance(role, str) or not role:
            return None
        flat: dict[str, Any] = {k: v for k, v in raw.items() if k != "type"}
        flat["type"] = role
        flat["message"] = inner
        return flat

    def parse_transcript_entries(
        self,
        entries: list[dict[str, Any]],
        pending_tools: dict[str, Any],
        cwd: str | None = None,  # noqa: ARG002 — kept for protocol compat
    ) -> tuple[list[AgentMessage], dict[str, Any]]:
        messages: list[AgentMessage] = []
        pending = normalize_pending(pending_tools)

        for entry in entries:
            role = entry.get("type", "")
            if role not in ("user", "assistant", "toolResult", "bashExecution"):
                continue
            inner = entry.get("message")
            if not isinstance(inner, dict):
                continue
            batch, pending = _parse_message_entry(role, inner, pending)
            messages.extend(batch)

        return messages, dict(pending)

    # `is_user_transcript_entry` / `parse_history_entry` inherited from
    # JsonlProvider — pi's envelope is flattened by parse_transcript_line
    # above, so the base implementations apply unchanged.

    # ── Discovery ────────────────────────────────────────────────────────

    def discover_transcript(
        self,
        cwd: str,
        window_key: str,
        *,
        max_age: float | None = None,
    ) -> SessionStartEvent | None:
        """Return the newest pi transcript whose header cwd matches."""
        if not cwd:
            return None

        age_limit = (
            _STALE_TRANSCRIPT_MAX_AGE_SECS if max_age is None else float(max_age)
        )
        now = time.time()
        try:
            resolved_target = str(Path(cwd).resolve())
        except OSError:
            return None

        for mtime, path in _candidate_transcripts(cwd)[:_DISCOVERY_SCAN_LIMIT]:
            if age_limit > 0 and now - mtime > age_limit:
                break
            header = read_session_header(str(path))
            if not header:
                continue
            try:
                header_cwd = str(Path(header["cwd"]).resolve())
            except OSError:
                continue
            if header_cwd != resolved_target:
                continue
            return SessionStartEvent(
                session_id=header["id"],
                cwd=header["cwd"],
                transcript_path=str(path),
                window_key=window_key,
            )
        return None

    # ── Commands ─────────────────────────────────────────────────────────

    def discover_commands(self, base_dir: str) -> list[DiscoveredCommand]:  # noqa: ARG002
        return [
            DiscoveredCommand(name=name, description=desc, source="builtin")
            for name, desc in _PI_BUILTINS.items()
        ]
