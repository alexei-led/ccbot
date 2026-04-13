"""Shared shell-provider context — LLM context gathering and secret redaction.

Extracted from ``shell_commands`` so that ``shell_capture`` can use
``gather_llm_context`` and ``redact_for_llm`` without importing back into
``shell_commands``. This removes the highest-volume mutual import between
the two shell modules.

The functions here have no per-window state — they're pure helpers that
look up shell metadata and apply regex-based redaction.
"""

from __future__ import annotations

import functools
import re
import shutil

from ..session import session_manager

# Modern CLI tools we hint to the LLM as preferred replacements when present.
_MODERN_TOOLS: dict[str, str] = {
    "fd": "find replacement (use fd syntax: fd PATTERN, fd --type file, NOT find syntax)",
    "rg": "grep replacement (use rg PATTERN, NOT grep syntax)",
    "bat": "cat replacement",
    "eza": "ls replacement (use eza, NOT ls)",
    "sd": "sed replacement (use sd 'from' 'to', NOT sed syntax)",
    "dust": "du replacement (use dust, NOT du)",
    "procs": "ps replacement",
}


@functools.cache
def _detect_shell_tools() -> str:
    """Detect available modern CLI tools on PATH (cached)."""
    available = []
    for tool, desc in _MODERN_TOOLS.items():
        if shutil.which(tool):
            available.append(f"{tool} ({desc})")
    return ", ".join(available)


# Patterns redacted from terminal output before sending to the LLM
_SENSITIVE_RE = re.compile(
    r"(?i)"
    r"(?:export\s+\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)\w*\s*=\s*\S+)"
    r"|(?:(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)\w*\s*[=:]\s*['\"]?\S{8,})"
    r"|(?:(?:sk|pk|ghp|gho|ghu|ghs|ghr|glpat|xoxb|xoxp|xoxs|AKIA)-[A-Za-z0-9_/+=]{10,})"
    r"|(?:Bearer\s+[A-Za-z0-9_.+/=-]{20,})",
)


def redact_for_llm(text: str) -> str:
    """Strip sensitive patterns from terminal text before sending to an LLM."""
    return _SENSITIVE_RE.sub("[REDACTED]", text)


async def gather_llm_context(window_id: str) -> dict[str, str]:
    """Gather cwd, shell type, and available tools for LLM calls."""
    from ..providers.shell import detect_pane_shell

    shell = await detect_pane_shell(window_id)
    tools = _detect_shell_tools()
    view = session_manager.view_window(window_id)
    cwd = view.cwd if view else ""
    return {"cwd": cwd, "shell": shell, "shell_tools": tools}
