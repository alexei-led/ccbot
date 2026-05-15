"""Git-worktree helpers for the new-topic flow.

When a new topic targets an eligible git repository, the directory flow
offers an opt-in step: keep the current branch (today's behaviour) or
spin up a fresh worktree on a new branch. This module is the pure git
plumbing behind that step — eligibility probing, branch-name
suggestion with collision avoidance, path/slug derivation, branch-name
validation, and worktree creation.

All git access goes through ``subprocess.run`` against the host ``git``
(already a runtime requirement). Nothing here touches Telegram, tmux,
or window state; the picker UI and wiring live in
``directory_browser`` / ``directory_callbacks``.

Key components: ``WorktreeEligibility`` (frozen result),
``check_worktree_eligibility``, ``suggest_branch_name``,
``slug_for_path``, ``worktree_path_for``, ``validate_branch_name``,
``create_worktree`` (raises ``WorktreeError`` on failure).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()

_GIT_TIMEOUT = 5
_WORKTREE_ADD_TIMEOUT = 30
_BRANCH_PREFIX = "ccg/"
_MAX_BRANCH_LEN = 200


class WorktreeError(RuntimeError):
    """Raised when ``git worktree add`` fails."""


@dataclass(frozen=True, slots=True)
class WorktreeEligibility:
    """Outcome of probing a directory for worktree eligibility.

    ``reason`` is populated only when ``eligible`` is False and exists
    for debug logging — it is never surfaced in the UI (the step is
    silently skipped when ineligible).
    """

    eligible: bool
    repo_path: Path | None
    current_branch: str | None
    dirty: bool
    reason: str | None = None


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )


def _ineligible(reason: str) -> WorktreeEligibility:
    return WorktreeEligibility(
        eligible=False,
        repo_path=None,
        current_branch=None,
        dirty=False,
        reason=reason,
    )


def _resolve_git_dir(path: Path) -> Path | None:
    res = _git(path, "rev-parse", "--git-dir")
    if res.returncode != 0:
        return None
    git_dir = Path(res.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (path / git_dir).resolve()
    return git_dir


def _has_merge_or_rebase(git_dir: Path) -> bool:
    return (
        (git_dir / "MERGE_HEAD").exists()
        or (git_dir / "rebase-apply").exists()
        or (git_dir / "rebase-merge").exists()
    )


def check_worktree_eligibility(path: Path) -> WorktreeEligibility:
    """Probe *path* for git-worktree eligibility.

    Eligible only when *path* is inside a non-bare work tree, on a
    named branch (not detached HEAD), with no merge or rebase in
    progress. A dirty work tree is still eligible (the picker warns
    but allows it). Any git/OS error is treated as ineligible.
    """
    try:
        inside = _git(path, "rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return _ineligible("not a git work tree")

        if _git(path, "rev-parse", "--is-bare-repository").stdout.strip() != "false":
            return _ineligible("bare repository")

        branch_res = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_res.stdout.strip()
        if branch_res.returncode != 0 or not branch or branch == "HEAD":
            return _ineligible("detached HEAD")

        git_dir = _resolve_git_dir(path)
        if git_dir is None:
            return _ineligible("cannot resolve git dir")
        if _has_merge_or_rebase(git_dir):
            return _ineligible("merge or rebase in progress")

        toplevel = _git(path, "rev-parse", "--show-toplevel")
        repo_path = Path(toplevel.stdout.strip()) if toplevel.returncode == 0 else path
        dirty = bool(_git(path, "status", "--porcelain").stdout.strip())
        return WorktreeEligibility(
            eligible=True,
            repo_path=repo_path,
            current_branch=branch,
            dirty=dirty,
            reason=None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug(
            "worktree eligibility check failed", path=str(path), error=str(exc)
        )
        return _ineligible(f"git error: {exc}")


def _used_branch_names(repo_path: Path) -> set[str]:
    used: set[str] = set()
    branches = _git(repo_path, "branch", "--list", "--format=%(refname:short)")
    if branches.returncode == 0:
        used.update(
            line.strip() for line in branches.stdout.splitlines() if line.strip()
        )
    worktrees = _git(repo_path, "worktree", "list", "--porcelain")
    if worktrees.returncode == 0:
        prefix = "branch refs/heads/"
        for line in worktrees.stdout.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                used.add(line[len(prefix) :])
    return used


def _kebab(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def suggest_branch_name(topic_title: str | None, repo_path: Path) -> str:
    """Suggest a non-colliding ``ccg/`` branch name.

    Prefers ``ccg/<kebab(topic-title)>``; on collision appends the
    smallest ``-<n>`` (n≥2) that is free. With no usable title, falls
    back to ``ccg/agent-<n>`` (smallest n≥1 that is free). Collisions
    are checked against both local branches and existing worktree
    branches.
    """
    used = _used_branch_names(repo_path)
    kebab = _kebab(topic_title) if topic_title else ""
    if kebab:
        candidate = f"{_BRANCH_PREFIX}{kebab}"
        if candidate not in used:
            return candidate
        n = 2
        while f"{candidate}-{n}" in used:
            n += 1
        return f"{candidate}-{n}"
    n = 1
    while f"{_BRANCH_PREFIX}agent-{n}" in used:
        n += 1
    return f"{_BRANCH_PREFIX}agent-{n}"


def slug_for_path(branch: str) -> str:
    """Worktree directory name for *branch* (``/`` → ``-``)."""
    return branch.replace("/", "-")


def worktree_path_for(repo_path: Path, slug: str) -> Path:
    """Worktree location: ``<repo>.worktrees/<slug>`` next to the repo."""
    return repo_path.parent / f"{repo_path.name}.worktrees" / slug


def validate_branch_name(name: str) -> bool:
    """Return True if *name* is a valid git branch name.

    Rejects empty, over-long, and leading-dash names up front (the
    last would be misread as a git option), then defers to
    ``git check-ref-format --branch``.
    """
    if not name or name.startswith("-") or len(name) > _MAX_BRANCH_LEN:
        return False
    try:
        res = subprocess.run(
            ["git", "check-ref-format", "--branch", name],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return res.returncode == 0


def create_worktree(repo_path: Path, branch: str, worktree_path: Path) -> None:
    """Create a worktree at *worktree_path* on a new *branch* off HEAD.

    Raises ``WorktreeError`` with git's stderr on any failure (branch
    already exists, target path occupied, git/OS error).
    """
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "worktree",
                "add",
                str(worktree_path),
                "-b",
                branch,
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=_WORKTREE_ADD_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"git worktree add failed: {exc}") from exc
    if res.returncode != 0:
        detail = res.stderr.strip() or res.stdout.strip() or "unknown error"
        raise WorktreeError(f"git worktree add failed: {detail}")
