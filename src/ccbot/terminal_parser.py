"""Terminal output parser — detects Claude Code UI elements in pane text.

Parses captured tmux pane content to detect:
  - Interactive UIs (AskUserQuestion, ExitPlanMode, Permission Prompt,
    RestoreCheckpoint) via regex-based UIPattern matching with top/bottom
    delimiters.
  - Status line (spinner characters + working text) by scanning from bottom up.

All Claude Code text patterns live here. To support a new UI type or
a changed Claude Code version, edit UI_PATTERNS / STATUS_SPINNERS.

Key functions: is_interactive_ui(), extract_interactive_content(),
parse_status_line(), strip_pane_chrome(), extract_bash_output().
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class InteractiveUIContent:
    """Content extracted from an interactive UI."""

    content: str  # The extracted display content
    name: str = ""  # Pattern name that matched (e.g. "AskUserQuestion")


@dataclass(frozen=True)
class UIPattern:
    """A text-marker pair that delimits an interactive UI region.

    Extraction scans lines top-down: the first line matching any `top` pattern
    marks the start, the first subsequent line matching any `bottom` pattern
    marks the end.  Both boundary lines are included in the extracted content.

    ``top`` and ``bottom`` are tuples of compiled regexes — any single match
    is sufficient.  This accommodates wording changes across Claude Code
    versions (e.g. a reworded confirmation prompt).
    """

    name: str  # Descriptive label (not used programmatically)
    top: tuple[re.Pattern[str], ...]
    bottom: tuple[re.Pattern[str], ...]
    min_gap: int = 2  # minimum lines between top and bottom (inclusive)


# ── UI pattern definitions (order matters — first match wins) ────────────

UI_PATTERNS: list[UIPattern] = [
    UIPattern(
        name="ExitPlanMode",
        top=(
            re.compile(r"^\s*Would you like to proceed\?"),
            # v2.1.29+: longer prefix that may wrap across lines
            re.compile(r"^\s*Claude has written up a plan"),
        ),
        bottom=(
            re.compile(r"^\s*ctrl-g to edit in "),
            re.compile(r"^\s*Esc to (cancel|exit)"),
        ),
    ),
    UIPattern(
        name="AskUserQuestion",
        top=(re.compile(r"^\s*←\s+[☐✔☒]"),),  # Multi-tab: no bottom needed
        bottom=(),
        min_gap=1,
    ),
    UIPattern(
        name="AskUserQuestion",
        top=(re.compile(r"^\s*[☐✔☒]"),),  # Single-tab: bottom required
        bottom=(re.compile(r"^\s*Enter to select"),),
        min_gap=1,
    ),
    UIPattern(
        name="PermissionPrompt",
        top=(re.compile(r"^\s*Do you want to proceed\?"),),
        bottom=(re.compile(r"^\s*Esc to cancel"),),
    ),
    UIPattern(
        name="RestoreCheckpoint",
        top=(re.compile(r"^\s*Restore the code"),),
        bottom=(re.compile(r"^\s*Enter to continue"),),
    ),
    UIPattern(
        name="Settings",
        top=(re.compile(r"^\s*Settings:"),),
        bottom=(
            re.compile(r"Esc to cancel"),
            re.compile(r"^\s*Type to filter"),
        ),
    ),
    UIPattern(
        name="SelectModel",
        top=(re.compile(r"^\s*Select model"),),
        bottom=(re.compile(r"Enter to confirm"),),
    ),
]


# ── Post-processing ──────────────────────────────────────────────────────

_RE_LONG_DASH = re.compile(r"^─{5,}$")

# Minimum number of "─" characters to recognize a line as a separator
_MIN_SEPARATOR_WIDTH = 20

# Maximum length of a chrome line (prompt, status bar) between separators.
# Lines longer than this are considered actual output content.
_MAX_CHROME_LINE_LENGTH = 80


def _shorten_separators(text: str) -> str:
    """Replace lines of 5+ ─ characters with exactly ─────."""
    return "\n".join(
        "─────" if _RE_LONG_DASH.match(line) else line for line in text.split("\n")
    )


# ── Core extraction ──────────────────────────────────────────────────────


def _try_extract(lines: list[str], pattern: UIPattern) -> InteractiveUIContent | None:
    """Try to extract content matching a single UI pattern.

    When ``pattern.bottom`` is empty, the region extends from the top marker
    to the last non-empty line (used for multi-tab AskUserQuestion where the
    bottom delimiter varies by tab).
    """
    top_idx: int | None = None
    bottom_idx: int | None = None

    for i, line in enumerate(lines):
        if top_idx is None:
            if any(p.search(line) for p in pattern.top):
                top_idx = i
        elif pattern.bottom and any(p.search(line) for p in pattern.bottom):
            bottom_idx = i
            break

    if top_idx is None:
        return None

    # No bottom patterns → use last non-empty line as boundary
    if not pattern.bottom:
        for i in range(len(lines) - 1, top_idx, -1):
            if lines[i].strip():
                bottom_idx = i
                break

    if bottom_idx is None or bottom_idx - top_idx < pattern.min_gap:
        return None

    content = "\n".join(lines[top_idx : bottom_idx + 1]).rstrip()
    return InteractiveUIContent(content=_shorten_separators(content), name=pattern.name)


# ── Public API ───────────────────────────────────────────────────────────


def extract_interactive_content(
    pane_text: str,
    patterns: list[UIPattern] | None = None,
) -> InteractiveUIContent | None:
    """Extract content from an interactive UI in terminal output.

    Tries each UI pattern in declaration order; first match wins.
    Returns None if no recognizable interactive UI is found.

    ``patterns`` defaults to ``UI_PATTERNS`` (Claude Code).  Providers with
    different terminal UIs pass their own pattern list.
    """
    if not pane_text:
        return None

    lines = pane_text.strip().split("\n")
    for pattern in patterns or UI_PATTERNS:
        result = _try_extract(lines, pattern)
        if result:
            return result
    return None


def is_interactive_ui(pane_text: str) -> bool:
    """Check if terminal currently shows an interactive UI."""
    return extract_interactive_content(pane_text) is not None


# ── Status line parsing ─────────────────────────────────────────────────

# Spinner characters Claude Code uses in its status line (fast-path lookup)
STATUS_SPINNERS = frozenset(["·", "✻", "✽", "✶", "✳", "✢"])

# Box-drawing range U+2500–U+257F and other known non-spinner symbols
_BRAILLE_START = 0x2800
_BRAILLE_END = 0x28FF
_NON_SPINNER_RANGES = ((0x2500, 0x257F),)  # box-drawing characters
_NON_SPINNER_CHARS = frozenset("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬>|·")
# Note: · (U+00B7 MIDDLE DOT) is in STATUS_SPINNERS so the fast-path catches it
# before _NON_SPINNER_CHARS is checked.

# Unicode categories that spinner characters typically belong to
_SPINNER_CATEGORIES = frozenset({"So", "Sm", "Po"})


def is_likely_spinner(char: str) -> bool:
    """Check if a character is likely a spinner symbol.

    Uses a two-tier approach:
    1. Fast-path: check the known STATUS_SPINNERS frozenset
    2. Fallback: use Unicode category matching (So, Sm, Po, Braille)
       while excluding box-drawing and other non-spinner characters
    """
    if not char:
        return False
    if char in STATUS_SPINNERS:
        return True
    if char in _NON_SPINNER_CHARS:
        return False
    cp = ord(char)
    for start, end in _NON_SPINNER_RANGES:
        if start <= cp <= end:
            return False
    # Braille Patterns block U+2800–U+28FF
    if _BRAILLE_START <= cp <= _BRAILLE_END:
        return True
    category = unicodedata.category(char)
    return category in _SPINNER_CATEGORIES


def parse_status_line(pane_text: str, *, pane_rows: int | None = None) -> str | None:
    """Extract the Claude Code status line from terminal output.

    The status line sits above a chrome separator (a line of ``─`` characters).
    Uses ``find_chrome_boundary()`` to locate the chrome block, then checks
    the lines immediately above it for a spinner character.

    When ``pane_rows`` is provided, the separator scan is limited to the
    bottom 40% of the screen as an optimization.

    Returns the text after the spinner, or None if no status line found.
    """
    if not pane_text:
        return None

    lines = pane_text.strip().split("\n")

    # Determine scan range: either bottom 40% of screen or all lines
    if pane_rows is not None:
        scan_limit = max(int(pane_rows * 0.4), 16)
        scan_start = max(len(lines) - scan_limit, 0)
    else:
        scan_start = 0

    # Scan separators from bottom up within the scan range.
    # Claude Code 4.6 renders two separators around the prompt line;
    # the spinner sits above the upper one, possibly with a blank line between.
    for i in range(len(lines) - 1, scan_start - 1, -1):
        if not _is_separator(lines[i]):
            continue
        # Check up to 2 lines above the separator (skip blanks).
        for offset in (1, 2):
            j = i - offset
            if j < scan_start:
                break
            candidate = lines[j].strip()
            if not candidate:
                continue  # skip blank line
            if is_likely_spinner(candidate[0]):
                return candidate[1:].strip()
            break  # non-blank, non-spinner → stop looking above this separator

    return None


# ── Status display formatting ──────────────────────────────────────────

# Keyword → short label mapping for status display in Telegram.
# First match wins; checked against the first word, then full string as fallback.
_STATUS_KEYWORDS: list[tuple[str, str]] = [
    ("think", "…thinking"),
    ("reason", "…thinking"),
    ("test", "…testing"),
    ("read", "…reading"),
    ("edit", "…editing"),
    ("writ", "…writing"),
    ("search", "…searching"),
    ("grep", "…searching"),
    ("glob", "…searching"),
    ("install", "…installing"),
    ("runn", "…running"),
    ("bash", "…running"),
    ("execut", "…running"),
    ("compil", "…building"),
    ("build", "…building"),
    ("lint", "…linting"),
    ("format", "…formatting"),
    ("deploy", "…deploying"),
    ("fetch", "…fetching"),
    ("download", "…downloading"),
    ("upload", "…uploading"),
    ("commit", "…committing"),
    ("push", "…pushing"),
    ("pull", "…pulling"),
    ("clone", "…cloning"),
    ("debug", "…debugging"),
    ("delet", "…deleting"),
    ("creat", "…creating"),
    ("check", "…checking"),
    ("updat", "…updating"),
    ("analyz", "…analyzing"),
    ("analys", "…analyzing"),
    ("pars", "…parsing"),
    ("verif", "…verifying"),
]


def format_status_display(raw_status: str) -> str:
    """Convert raw Claude Code status text to a short display label.

    Matches the first word first (so "Writing tests" → "…writing", not "…testing"),
    then falls back to scanning the full string. Returns "…working" if nothing matches.
    """
    lower = raw_status.lower()
    first_word = lower.split(maxsplit=1)[0] if lower else ""
    for keyword, label in _STATUS_KEYWORDS:
        if keyword in first_word:
            return label
    for keyword, label in _STATUS_KEYWORDS:
        if keyword in lower:
            return label
    return "…working"


# ── Pane chrome stripping & bash output extraction ─────────────────────


def _is_separator(line: str) -> bool:
    """Check if a line is a chrome separator (all ─ chars, wide enough)."""
    stripped = line.strip()
    return len(stripped) >= _MIN_SEPARATOR_WIDTH and all(c == "─" for c in stripped)


def find_chrome_boundary(lines: list[str]) -> int | None:
    """Find the topmost separator row of Claude Code's bottom chrome.

    Scans from the bottom upward, looking for the first separator that has
    only chrome content below it (more separators, prompt chars, status bar).
    Returns the line index of that separator, or None if no chrome found.
    """
    if not lines:
        return None

    # Find all separator indices, scanning from bottom up
    separator_indices: list[int] = []
    for i in range(len(lines) - 1, -1, -1):
        if _is_separator(lines[i]):
            separator_indices.append(i)

    if not separator_indices:
        return None

    # The topmost separator is the chrome boundary.
    # Walk the separators (already sorted bottom-up) and find the one
    # where everything between consecutive separators is chrome (prompt, status).
    # The topmost separator in a contiguous chrome block is our boundary.
    boundary = separator_indices[0]  # start with the bottommost

    for idx in separator_indices[1:]:
        # Check if the lines between this separator and the current boundary
        # are all chrome-like (empty, prompt, status bar, or short non-content).
        gap_is_chrome = True
        for j in range(idx + 1, boundary):
            line = lines[j].strip()
            if not line:
                continue
            # Chrome lines: prompt (❯), status bar info, short UI elements
            # Non-chrome: actual output content (longer meaningful text)
            # Heuristic: lines in chrome are typically short UI elements
            if len(line) > _MAX_CHROME_LINE_LENGTH:
                gap_is_chrome = False
                break
        if gap_is_chrome:
            boundary = idx
        else:
            break

    return boundary


def strip_pane_chrome(lines: list[str]) -> list[str]:
    """Strip Claude Code's bottom chrome (prompt area + status bar).

    The bottom of the pane looks like::

        ────────────────────────  (separator)
        ❯                        (prompt)
        ────────────────────────  (separator)
          [Opus 4.6] Context: 34%
          ⏵⏵ bypass permissions…

    Finds the topmost separator in the bottom chrome block and strips
    everything from there down.
    """
    boundary = find_chrome_boundary(lines)
    if boundary is not None:
        return lines[:boundary]
    return lines


def extract_bash_output(pane_text: str, command: str) -> str | None:
    """Extract ``!`` command output from a captured tmux pane.

    Searches from the bottom for the ``! <command>`` echo line, then
    returns that line and everything below it (including the ``⎿`` output).
    Returns *None* if the command echo wasn't found.
    """
    lines = strip_pane_chrome(pane_text.splitlines())

    # Find the last "! <command>" echo line (search from bottom).
    # Match on the first 10 chars of the command in case the line is truncated.
    cmd_idx: int | None = None
    match_prefix = command[:10]
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith(f"! {match_prefix}") or stripped.startswith(
            f"!{match_prefix}"
        ):
            cmd_idx = i
            break

    if cmd_idx is None:
        return None

    # Include the command echo line and everything after it
    raw_output = lines[cmd_idx:]

    # Strip trailing empty lines
    while raw_output and not raw_output[-1].strip():
        raw_output.pop()

    if not raw_output:
        return None

    return "\n".join(raw_output).strip()
