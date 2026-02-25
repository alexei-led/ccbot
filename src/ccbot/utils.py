"""Shared utility functions used across multiple CCBot modules.

Provides:
  - ccbot_dir(): resolve config directory from CCBOT_DIR env var.
  - tmux_session_name(): resolve tmux session name from env.
  - atomic_write_json(): crash-safe JSON file writes via temp+rename.
  - read_cwd_from_jsonl(): extract the cwd field from the first JSONL entry.
  - task_done_callback(): log unhandled exceptions from background asyncio tasks.
"""

import asyncio
import json
import structlog
import os
import tempfile
from pathlib import Path
from typing import Any
import contextlib

logger = structlog.get_logger()

CCBOT_DIR_ENV = "CCBOT_DIR"


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

    Shared by session.py and session_monitor.py.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    cwd = data.get("cwd")
                    if cwd:
                        return cwd
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return ""


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
