"""File search, listing and upload utilities for the /send command.

Provides utilities for the /send Telegram command:
  - _is_image: detect image files by extension
  - _find_files: glob/exact/substring file search with security filtering
  - _list_directory: directory listing with security filtering and sorting
  - _format_file_label: human-readable inline keyboard button labels
  - build_file_browser: build paginated inline keyboard for directory browsing
  - build_search_results: build inline keyboard for search result selection
"""

import structlog
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..config import config
from .callback_data import (
    CB_SEND_CANCEL,
    CB_SEND_DIR,
    CB_SEND_FILE,
    CB_SEND_PAGE,
    CB_SEND_UP,
)
from .send_security import is_excluded_dir, validate_sendable

logger = structlog.get_logger()

_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp"}
)
_ITEMS_PER_PAGE = 8
_BUTTONS_PER_ROW = 2
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


def _make_item_button(item: Path, idx: int, cwd: Path) -> InlineKeyboardButton:
    """Return a single InlineKeyboardButton for *item* at position *idx*."""
    if item.is_dir():
        return InlineKeyboardButton(
            f"📁 {item.name}", callback_data=f"{CB_SEND_DIR}{idx}"
        )
    label = _format_file_label(item, cwd)
    icon = "🖼️" if _is_image(item) else "📄"
    return InlineKeyboardButton(f"{icon} {label}", callback_data=f"{CB_SEND_FILE}{idx}")


def _pack_into_rows(
    buttons_flat: list[InlineKeyboardButton],
) -> list[list[InlineKeyboardButton]]:
    """Pack a flat list of buttons into rows of _BUTTONS_PER_ROW."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for btn in buttons_flat:
        row.append(btn)
        if len(row) == _BUTTONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def build_file_browser(
    current_path: Path,
    cwd: Path,
    page: int,
) -> tuple[str, InlineKeyboardMarkup, list[Path]]:
    """Build a paginated inline keyboard for browsing files under *cwd*.

    Returns (display_text, markup, items) where *items* is the full list of
    Path objects (dirs first, then files) used to resolve button indices.
    """
    dirs, files = _list_directory(current_path, cwd)
    items: list[Path] = dirs + files

    total_pages = max(1, (len(items) + _ITEMS_PER_PAGE - 1) // _ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _ITEMS_PER_PAGE
    page_items = items[start : start + _ITEMS_PER_PAGE]

    flat = [_make_item_button(item, items.index(item), cwd) for item in page_items]
    buttons = _pack_into_rows(flat)

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton("◀", callback_data=f"{CB_SEND_PAGE}{page - 1}")
            )
        nav.append(
            InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton("▶", callback_data=f"{CB_SEND_PAGE}{page + 1}")
            )
        buttons.append(nav)

    parent_row: list[InlineKeyboardButton] = []
    if current_path != cwd:
        parent_row.append(InlineKeyboardButton("📁 ..", callback_data=CB_SEND_UP))
    parent_row.append(InlineKeyboardButton("✖ Cancel", callback_data=CB_SEND_CANCEL))
    buttons.append(parent_row)

    try:
        display_path = (
            str(current_path.relative_to(cwd)) if current_path != cwd else "."
        )
    except ValueError:
        display_path = current_path.name

    return f"📂 {display_path}", InlineKeyboardMarkup(buttons), items


def build_search_results(
    matches: list[Path],
    cwd: Path,
) -> tuple[str, InlineKeyboardMarkup, list[Path]]:
    """Build an inline keyboard for selecting a file from search results.

    Shows up to ``_ITEMS_PER_PAGE * 3`` matches with no pagination or parent nav.
    Returns (display_text, markup, matches).
    """
    shown = matches[: _ITEMS_PER_PAGE * 3]

    flat = [_make_item_button(path, idx, cwd) for idx, path in enumerate(shown)]
    buttons = _pack_into_rows(flat)
    buttons.append([InlineKeyboardButton("✖ Cancel", callback_data=CB_SEND_CANCEL)])

    return f"🔍 {len(matches)} file(s) found", InlineKeyboardMarkup(buttons), shown
