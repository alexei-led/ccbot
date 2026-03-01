"""Shared utility functions used across multiple CCBot modules.

Provides:
  - ccbot_dir(): resolve config directory from CCBOT_DIR env var.
  - tmux_session_name(): resolve tmux session name from env.
  - atomic_write_json(): crash-safe JSON file writes via temp+rename.
  - read_cwd_from_jsonl(): extract the cwd field from the first JSONL entry.
  - read_session_metadata_from_jsonl(): single-pass extraction of (cwd, summary).
  - task_done_callback(): log unhandled exceptions from background asyncio tasks.
"""

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

CCBOT_DIR_ENV = "CCBOT_DIR"

# Maximum number of JSONL lines to scan when extracting session metadata.
_SCAN_LINES = 20

_SUMMARY_MAX_CHARS = 80


def ccbot_dir() -> Path:
    """Resolve config directory from CCBOT_DIR env var or default ~/.ccbot."""
    raw = os.environ.get(CCBOT_DIR_ENV, "")
    return Path(raw) if raw else Path.home() / ".ccbot"


def tmux_session_name() -> str:
    """Get tmux session name from TMUX_SESSION_NAME env var or default 'ccbot'."""
    return os.environ.get("TMUX_SESSION_NAME", "ccbot")


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON data to a file atomically.

    Writes to a temporary file in the same directory, then renames it
    to the target path. This prevents data corruption if the process
    is interrupted mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=indent)

    # Write to temp file in same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def read_cwd_from_jsonl(file_path: str | Path) -> str:
    """Read the cwd field from the first JSONL entry that has one.

    Scans up to _SCAN_LINES lines. Shared by session.py and session_monitor.py.
    """
    cwd, _ = read_session_metadata_from_jsonl(file_path)
    return cwd


def _extract_user_text(msg: dict[str, object]) -> str:
    """Extract display text from a user message's content field."""
    content = msg.get("content", "")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text:
                    return text[:_SUMMARY_MAX_CHARS]
    elif isinstance(content, str) and content:
        return content[:_SUMMARY_MAX_CHARS]
    return ""


def _extract_metadata_from_entry(data: dict, cwd: str, summary: str) -> tuple[str, str]:
    """Extract cwd and summary fields from a single parsed JSONL entry."""
    if not cwd:
        found_cwd = data.get("cwd")
        if found_cwd and isinstance(found_cwd, str):
            cwd = found_cwd
    if not summary and data.get("type") == "user":
        msg = data.get("message", {})
        if isinstance(msg, dict):
            summary = _extract_user_text(msg)
    return cwd, summary


def read_session_metadata_from_jsonl(file_path: str | Path) -> tuple[str, str]:
    """Extract cwd and summary from a JSONL transcript in a single file read.

    Scans up to _SCAN_LINES lines. Returns (cwd, summary) where either
    may be empty if not found.
    """
    cwd = ""
    summary = ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= _SCAN_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                cwd, summary = _extract_metadata_from_entry(data, cwd, summary)
                if cwd and summary:
                    break
    except OSError:
        pass
    return cwd, summary


def task_done_callback(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from background asyncio tasks.

    Attach to any fire-and-forget task via ``task.add_done_callback(task_done_callback)``.
    Suppresses CancelledError (normal shutdown).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task %s failed", task.get_name(), exc_info=exc)
