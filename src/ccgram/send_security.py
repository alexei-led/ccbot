"""Security validation for the /send command — path traversal and access control.

Ensures only files within the session's cwd can be sent to Telegram.
Blocks access to reserved directories (.ccgram-uploads/) and optionally
rejects hidden files (dot-prefixed names).

Key function: validate_send_path(path, cwd) -> bool
"""

from pathlib import Path

_UPLOAD_DIR = ".ccgram-uploads"


def validate_send_path(
    path: str | Path,
    cwd: str | Path,
    *,
    allow_hidden: bool = True,
) -> bool:
    """Return True if *path* is safe to send; False otherwise.

    Checks performed (in order):
    1. Resolve symlinks — the real path must lie strictly within *cwd*.
    2. Reject any path component that equals `.ccgram-uploads` (reserved for
       inbound uploads; sending those back would expose user-uploaded content
       in ways the sender may not intend).
    3. If *allow_hidden* is False, reject any path component that starts with
       `.` (hidden file/directory on POSIX systems).

    Args:
        path: The candidate file or directory path.
        cwd: The session working directory that acts as the security boundary.
        allow_hidden: When False, paths whose name starts with ``.`` are
            rejected.  Defaults to True (hidden files allowed).

    Returns:
        True if the path passes all checks, False otherwise.
    """
    try:
        real_path = Path(path).resolve()
        real_cwd = Path(cwd).resolve()
    except OSError, ValueError:
        return False

    # 1. Path traversal check — resolved path must be within cwd
    try:
        real_path.relative_to(real_cwd)
    except ValueError:
        return False

    # 2. Reject .ccgram-uploads/ entries
    if _UPLOAD_DIR in real_path.parts:
        return False

    # 3. Optional hidden-file rejection (check every component relative to cwd)
    if not allow_hidden:
        try:
            rel = real_path.relative_to(real_cwd)
        except ValueError:
            return False
        for part in rel.parts:
            if part.startswith("."):
                return False

    return True
