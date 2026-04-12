"""File search, listing and upload utilities for the /send command.

Provides utilities for the /send Telegram command:
  - _is_image: detect image files by extension
  - _find_files: glob/exact/substring file search with security filtering
  - _list_directory: directory listing with security filtering and sorting
  - _format_file_label: human-readable inline keyboard button labels
"""

import structlog
from pathlib import Path

from ..config import config
from .send_security import is_excluded_dir, validate_sendable

logger = structlog.get_logger()

_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp"}
)
_ITEMS_PER_PAGE = 8
_KB = 1024
_MB = 1024 * 1024


def _is_image(path: Path) -> bool:
    """Return True if *path* has an image file extension."""
    return path.suffix.lower() in _IMAGE_EXTENSIONS


def _find_files(cwd: Path, pattern: str) -> list[Path]:
    """Search for files matching *pattern* under *cwd*.

    Dispatch rules:
    - Pattern contains ``*`` or ``?``: glob search via ``cwd.rglob(pattern)``.
    - Otherwise: try exact relative path first; if not found, substring search via
      ``cwd.rglob(f"*{pattern}*")``.

    All candidates are filtered:
    - Skip files inside excluded directories (any ancestor component matches
      ``is_excluded_dir``).
    - Skip files where ``validate_sendable`` returns a non-None error string.
    - Skip files deeper than ``config.send_search_depth`` levels below *cwd*.

    Results are capped at ``config.send_max_results`` and sorted by mtime descending.
    """
    is_glob = "*" in pattern or "?" in pattern

    candidates: list[Path] = []

    if is_glob:
        candidates = list(cwd.rglob(pattern))
    else:
        exact = cwd / pattern
        if exact.exists() and validate_sendable(exact, cwd) is None:
            return [exact]
        candidates = list(cwd.rglob(f"*{pattern}*"))

    depth_limit = config.send_search_depth
    max_results = config.send_max_results

    results: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        # Check depth relative to cwd
        try:
            rel = path.relative_to(cwd)
        except ValueError:
            continue
        if len(rel.parts) > depth_limit:
            continue
        # Skip files inside excluded directories
        if any(is_excluded_dir(part) for part in rel.parts[:-1]):
            continue
        # Skip denied files
        if validate_sendable(path, cwd) is not None:
            continue
        results.append(path)

    results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return results[:max_results]


def _list_directory(path: Path, cwd: Path) -> tuple[list[Path], list[Path]]:
    """List *path* contents, separated into (dirs, files).

    Filtering:
    - Directories: exclude names matching ``is_excluded_dir``.
    - Files: exclude those where ``validate_sendable`` returns non-None.

    Both lists are sorted alphabetically by name (case-insensitive).
    """
    dirs: list[Path] = []
    files: list[Path] = []

    for entry in path.iterdir():
        if entry.is_dir():
            if not is_excluded_dir(entry.name):
                dirs.append(entry)
        elif entry.is_file() and validate_sendable(entry, cwd) is None:
            files.append(entry)

    dirs.sort(key=lambda p: p.name.lower())
    files.sort(key=lambda p: p.name.lower())
    return dirs, files


def _format_file_label(path: Path, cwd: Path) -> str:
    """Return a button label string ``"{rel_path} ({size})"`` for *path*.

    Size is formatted as B, KB, or MB. The total label is capped at 30 characters:
    when it exceeds that, the path portion is truncated with ``…`` while the size
    suffix is always preserved.
    """
    try:
        rel = str(path.relative_to(cwd))
    except ValueError:
        rel = path.name

    size_bytes = path.stat().st_size
    if size_bytes < _KB:
        size_str = f"{size_bytes} B"
    elif size_bytes < _MB:
        size_str = f"{size_bytes / _KB:.1f} KB"
    else:
        size_str = f"{size_bytes / _MB:.1f} MB"

    suffix = f" ({size_str})"
    label = rel + suffix

    max_len = 30
    if len(label) > max_len:
        # Truncate path portion, keep size suffix
        max_path_len = max_len - len(suffix) - 1  # 1 for ellipsis
        rel = rel[:max_path_len] + "…"
        label = rel + suffix

    return label
