"""Shell provider infrastructure — prompt detection, marker setup, shell inventory.

Separated from ``shell.py`` (which holds the slim ``ShellProvider`` class)
so the provider boundary stays clean: ``shell.py`` is just the
``AgentProvider`` implementation, and this module owns everything else
that handlers and the rest of ccgram need to drive a shell session
(prompt-marker matching, interactive-shell detection, prompt setup,
known shell inventory).

Future shell-like providers can compose against this infrastructure
without subclassing ``ShellProvider``.
"""

from __future__ import annotations

import asyncio
import functools
import os
import re
from dataclasses import dataclass

_DEFAULT_MARKER = "ccgram"


_VALID_PROMPT_MODES = frozenset({"wrap", "replace"})
_WARNED_INVALID_MODE = False


def _get_prompt_mode() -> str:
    """Return the configured prompt mode (``wrap`` or ``replace``)."""
    global _WARNED_INVALID_MODE  # noqa: PLW0603
    from ccgram.config import config

    mode = getattr(config, "prompt_mode", "wrap") or "wrap"
    if mode not in _VALID_PROMPT_MODES:
        if not _WARNED_INVALID_MODE:
            _WARNED_INVALID_MODE = True
            import structlog

            structlog.get_logger().warning(
                "Invalid CCGRAM_PROMPT_MODE=%r, defaulting to 'wrap'", mode
            )
        return "wrap"
    return mode


def _get_marker_prefix() -> str:
    """Return the configured prompt marker prefix (used in ``replace`` mode)."""
    from ccgram.config import config

    return getattr(config, "prompt_marker", _DEFAULT_MARKER) or _DEFAULT_MARKER


@functools.cache
def _compile_replace_re(prefix: str) -> re.Pattern[str]:
    """Compile prompt regex for ``replace`` mode (cached per unique prefix)."""
    return re.compile(rf"^{re.escape(prefix)}:(\d+)❯\s?(.*)")


_WRAP_RE = re.compile(r"⌘(\d+)⌘\s?(.*)$")


@dataclass(frozen=True)
class PromptMatch:
    """Typed result from prompt marker matching.

    Replaces raw ``re.Match`` group access with named fields so consumers
    never depend on regex internals.
    """

    sequence_number: int
    """Monotonic counter (exit code of the last command)."""

    trailing_text: str
    """Command text after the marker (empty string when the shell is idle)."""

    exit_code: int
    """Exit code of the last command (same value as *sequence_number*)."""

    raw_line: str
    """Original terminal line that matched."""


def _match_to_prompt_match(m: re.Match[str], line: str) -> PromptMatch:
    """Convert a regex match into a typed ``PromptMatch``."""
    num = int(m.group(1))
    return PromptMatch(
        sequence_number=num,
        trailing_text=m.group(2),
        exit_code=num,
        raw_line=line,
    )


def match_prompt(line: str) -> PromptMatch | None:
    """Match a prompt marker in *line*, respecting the current prompt mode.

    In ``replace`` mode the marker is at line start (``re.match``).
    In ``wrap`` mode the marker can appear anywhere (``re.search``).

    Returns a typed ``PromptMatch`` or ``None``.
    """
    if _get_prompt_mode() == "replace":
        m = _compile_replace_re(_get_marker_prefix()).match(line)
    else:
        m = _WRAP_RE.search(line)
    if m is None:
        return None
    return _match_to_prompt_match(m, line)


KNOWN_SHELLS = frozenset({"bash", "zsh", "fish", "sh", "dash", "tcsh", "csh", "ksh"})


async def has_prompt_marker(window_id: str) -> bool:
    """Check if the prompt marker is present in the pane."""
    from ccgram.tmux_manager import tmux_manager

    capture = await tmux_manager.capture_pane(window_id)
    if not capture:
        return False
    return any(match_prompt(line) for line in capture.rstrip().splitlines()[-5:])


def get_shell_name() -> str:
    """Return the basename of the bot process's $SHELL (e.g. 'fish', 'zsh').

    Sync fallback — for pane-accurate detection use ``detect_pane_shell()``.
    """
    return os.environ.get("SHELL", "").rsplit("/", 1)[-1]


async def detect_pane_shell(window_id: str) -> str:
    """Detect the shell running in a tmux pane via pane_current_command.

    Falls back to ``get_shell_name()`` when the pane is unavailable or
    its command is not a recognized shell.
    """
    from ccgram.tmux_manager import tmux_manager

    window = await tmux_manager.find_window_by_id(window_id)
    if window and window.pane_current_command:
        tokens = window.pane_current_command.split()
        if not tokens:
            return get_shell_name()
        basename = os.path.basename(tokens[0])
        cleaned = basename.lstrip("-")
        if cleaned in KNOWN_SHELLS:
            return cleaned
    return get_shell_name()


def _wrap_setup_commands(shell: str) -> str:
    """Return the shell command that appends a ⌘N⌘ marker to the prompt."""
    fish = (
        "builtin functions --query __ccgram_orig_prompt; or begin; "
        "builtin functions --copy fish_prompt __ccgram_orig_prompt 2>/dev/null; "
        "or function __ccgram_orig_prompt; end; "
        "function fish_prompt; "
        "set -l __s $status; "
        "__ccgram_orig_prompt; "
        "set_color brblack; printf '⌘%d⌘ ' $__s; set_color normal; "
        "end; clear; end"
    )
    bash = (
        "type __ccgram_sc >/dev/null 2>&1 || { "
        "__ccgram_sc(){ __ccgram_x=$?; return $__ccgram_x; }; "
        'PROMPT_COMMAND="__ccgram_sc${PROMPT_COMMAND:+;$PROMPT_COMMAND}"; '
        'PS1="${PS1}\\[\\033[2m\\]⌘\\${__ccgram_x}⌘\\[\\033[0m\\] "; '
        "clear; }"
    )
    zsh = (
        '[[ "$PROMPT" == *⌘%\\?⌘* ]] || { '
        "PROMPT+=$'%{\\e[2m%}⌘%?⌘%{\\e[0m%} '; "
        "clear; }"
    )
    tcsh = 'set prompt = "${prompt}⌘$status⌘ "'
    sh = 'case "$PS1" in *⌘*⌘*) ;; *) PS1="\\$ ⌘0⌘ "; clear;; esac'
    return {
        "fish": fish,
        "bash": bash,
        "zsh": zsh,
        "tcsh": tcsh,
        "csh": tcsh,
        "sh": sh,
        "dash": sh,
        "ksh": sh,
    }.get(shell, sh)


def _replace_setup_commands(shell: str, prefix: str) -> str:
    """Return the shell command that replaces the prompt with {prefix}:N❯."""
    cmds = {
        "fish": f'function fish_prompt; printf "{prefix}:$status❯ "; end',
        "bash": f"PS1='{prefix}:$?❯ '",
        "zsh": f"PROMPT='{prefix}:%?❯ '",
        "tcsh": f'set prompt = "{prefix}:$status❯ "',
        "csh": f'set prompt = "{prefix}:$status❯ "',
    }
    return cmds.get(shell, cmds["bash"])


async def _is_interactive_shell(window_id: str) -> bool:
    """Check if the pane has an interactive shell at a prompt (not running a script).

    Uses ``ps -t`` to inspect the foreground process. A shell running a script
    (e.g. ``bash ./scripts/restart.sh``) has child processes in the foreground
    group, while an idle interactive shell is its own foreground leader with
    bare args like ``-bash``, ``fish``, or ``/bin/zsh``.

    Returns True if the shell looks interactive, False if it's running a script
    or if detection fails (fail-safe: don't send C-c to unknown targets).
    """
    from ccgram.tmux_manager import tmux_manager

    w = await tmux_manager.find_window_by_id(window_id)
    if not w or not w.pane_tty:
        return False

    from .process_detection import get_foreground_args

    args, _ = await get_foreground_args(w.pane_tty)
    if not args:
        return False

    first_token = args.split()[0]
    basename = first_token.rsplit("/", 1)[-1].lstrip("-")
    if basename not in KNOWN_SHELLS:
        return False

    tokens = args.split()
    return len(tokens) == 1


async def setup_shell_prompt(window_id: str, *, clear: bool = True) -> None:
    """Configure the shell prompt with a detectable marker.

    In ``wrap`` mode the existing prompt is preserved and a small ``⌘N⌘``
    suffix is appended.  In ``replace`` mode the prompt is fully replaced
    with ``{prefix}:N❯``.

    No-op if the marker is already present in the pane (idempotent).
    Set ``clear=False`` when attaching to an existing session to
    preserve scrollback context.
    """
    from ccgram.config import config

    # Never send prompt setup to ccgram's own window — the C-c would kill the bot
    if config.own_window_id and window_id == config.own_window_id:
        return

    # Safety: verify the shell is actually idle at a prompt, not running a script.
    if not await _is_interactive_shell(window_id):
        return

    if await has_prompt_marker(window_id):
        return

    from ccgram.tmux_manager import tmux_manager

    await tmux_manager.send_keys(window_id, "C-c", enter=False, literal=False)
    await asyncio.sleep(0.1)

    shell = await detect_pane_shell(window_id)
    mode = _get_prompt_mode()
    if mode == "replace":
        cmd = _replace_setup_commands(shell, _get_marker_prefix())
    else:
        cmd = _wrap_setup_commands(shell)
    await tmux_manager.send_keys(window_id, cmd, raw=True)
    await asyncio.sleep(0.3)
    if clear:
        await tmux_manager.send_keys(window_id, "clear", raw=True)
