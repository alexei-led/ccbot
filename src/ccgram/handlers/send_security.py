"""Security validation for the /send command — multi-layer access control.

Ensures only safe, non-sensitive files within the session's CWD can be sent to
Telegram. The pipeline applies checks in order: path containment, hidden files,
secret patterns, gitleaks rules, gitignore, state-file protection, size limit,
and file-type validation.

Key function: validate_sendable(path, cwd) -> str | None
"""

from __future__ import annotations

import fnmatch
import re
import stat
import subprocess
import tomllib
from pathlib import Path

import structlog

logger = structlog.get_logger()

_SECRET_PATTERNS: list[str] = [
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*credential*",
    "*secret*",
    "*.token",
    ".env",
    ".env.*",
]

_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        ".cache",
        ".npm",
        ".yarn",
        "target",
        ".gradle",
    }
)

_TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB


def is_path_contained(path: Path, root: Path) -> bool:
    """Return True if *path* resolves to a location within *root*."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError, ValueError:
        return False


def is_hidden(path: Path, root: Path) -> bool:
    """Return True if any path component relative to *root* starts with '.'."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except OSError, ValueError:
        return False
    return any(part.startswith(".") for part in rel.parts)


def matches_secret_pattern(path: Path) -> str | None:
    """Return the matching secret pattern if path.name matches, else None."""
    name = path.name.lower()
    for pattern in _SECRET_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return pattern
    return None


def _gitignored_by_pathspec(path: Path, cwd: Path) -> bool:
    """Pathspec fallback for is_gitignored — walk .gitignore files up to cwd."""
    try:
        import pathspec  # noqa: PLC0415 — lazy import for optional fallback

        lines: list[str] = []
        current = path.parent
        cwd_resolved = cwd.resolve()
        while True:
            gitignore = current / ".gitignore"
            if gitignore.is_file():
                lines.extend(
                    gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
                )
            if current.resolve() == cwd_resolved:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        if not lines:
            return False

        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        # Match against the full path relative to cwd, not to the individual
        # .gitignore file's directory.  This is intentionally coarser than
        # git's own per-directory scoping: it is a last-resort fallback used
        # only when git is unavailable, so false-negatives are acceptable.
        try:
            rel = path.relative_to(cwd)
        except ValueError:
            return False
        return spec.match_file(str(rel))
    except Exception as exc:  # noqa: BLE001 — last-resort fallback
        logger.debug("pathspec_fallback_error", error=str(exc), path=str(path))
        return False


def is_gitignored(path: Path, cwd: Path) -> bool:
    """Return True if *path* is ignored according to git or a local .gitignore.

    Primary: `git check-ignore -q <path>` subprocess. Exit 0 → ignored,
    exit 1 → not ignored, any other exit → fall through to pathspec fallback.
    On subprocess error (not a git repo, git not found, timeout), also falls
    back to pathspec. Returns False if both strategies fail.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        # Any other returncode (e.g. fatal git error) — fall through to pathspec
    except FileNotFoundError, subprocess.TimeoutExpired, OSError:
        pass

    return _gitignored_by_pathspec(path, cwd)


def check_gitleaks_rules(path: Path, cwd: Path) -> str | None:
    """Return a rule id/description if *path* matches any gitleaks path rule, else None.

    Loads `.gitleaks.toml` from *cwd* if present, iterates `[[rules]]`, and
    applies each rule's `path` regex against the path relative to *cwd*.
    Returns the rule's `id` field (or `"gitleaks rule"` if absent) on first
    match. Returns None if no match or if the file is absent/unparseable.
    """
    toml_path = cwd / ".gitleaks.toml"
    if not toml_path.is_file():
        return None

    try:
        with toml_path.open("rb") as fh:
            config = tomllib.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.debug("gitleaks_toml_parse_error", error=str(exc), cwd=str(cwd))
        return None

    try:
        relative_path = str(path.relative_to(cwd))
    except ValueError:
        # path is not contained in cwd — should have been caught by
        # is_path_contained() earlier. Skip gitleaks rules rather than
        # matching against the absolute path (breaks ^-anchored rules).
        return None

    for rule in config.get("rules", []):
        rule_path = rule.get("path")
        if not rule_path:
            continue
        try:
            if re.search(rule_path, relative_path):
                return rule.get("id", "gitleaks rule")
        except re.error:
            continue

    return None


def _check_size_and_type(path: Path) -> str | None:
    """Return an error string if the file fails size or type checks, else None."""
    try:
        st = path.stat()
    except OSError:
        return "File not accessible"
    if not stat.S_ISREG(st.st_mode):
        return "Not a regular file"
    if st.st_size > _TELEGRAM_FILE_LIMIT:
        size_mb = st.st_size / (1024 * 1024)
        return f"File too large: {size_mb:.0f} MB (limit: 50 MB)"
    return None


def validate_sendable(path: Path, cwd: Path) -> str | None:
    """Run the full security pipeline for *path* relative to *cwd*.

    Returns a human-readable error string on the first failed check, or None
    if the file is safe to send.

    Pipeline order (cheap stat-based checks first, subprocess last):
    1. Path containment (traversal)
    2. Hidden file/dir check
    3. Secret pattern match
    4. File size limit + regular-file check
    5. State-file protection (assert_sendable from utils)
    6. Gitleaks rule match
    7. Gitignore check (subprocess — most expensive, last)
    """
    if not is_path_contained(path, cwd):
        return "File is outside project directory"

    if is_hidden(path, cwd):
        return "Hidden files cannot be sent"

    pattern = matches_secret_pattern(path)
    if pattern is not None:
        return f"File appears to contain credentials — denied ({pattern})"

    size_error = _check_size_and_type(path)
    if size_error is not None:
        return size_error

    from ..utils import assert_sendable  # noqa: PLC0415

    try:
        assert_sendable(path)
    except ValueError as exc:
        return str(exc)

    rule_id = check_gitleaks_rules(path, cwd)
    if rule_id is not None:
        return f"File denied by gitleaks rule: {rule_id}"

    if is_gitignored(path, cwd):
        return "File is gitignored"

    return None


def is_excluded_dir(name: str) -> bool:
    """Return True if *name* is a directory that should never be listed or searched."""
    return name in _EXCLUDED_DIRS or name.startswith(".")
