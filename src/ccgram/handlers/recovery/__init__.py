"""Recovery subpackage — dead window recovery, resume, restore, history.

Bundles the modules that surface "browse past sessions" and recover from
dead windows: ``recovery_callbacks`` (callback dispatcher + shared
validators), ``recovery_banner`` (dead-window banner UX flow),
``resume_picker`` (resume-picker UX flow + transcript scan),
``restore_command`` (/restore re-renders the banner on demand),
``resume_command`` (/resume scans past Claude sessions and resumes one),
``transcript_discovery`` (hookless transcript discovery for
Codex/Gemini/Pi and provider auto-detection), ``history`` (paginated
message history send/edit), and ``history_callbacks`` (page-navigation
callback handler).

Public surface re-exported here is the entry point for ``bot.py`` and the
rest of ``handlers/``; internals stay in the per-module files.
"""

from .history import send_history
from .history_callbacks import handle_history_callback
from .recovery_banner import RecoveryBanner, build_recovery_keyboard, render_banner
from .recovery_callbacks import handle_recovery_callback
from .restore_command import restore_command
from .resume_command import (
    ResumeEntry,
    format_session_entry,
    handle_resume_command_callback,
    resume_command,
    scan_all_sessions,
)
from .resume_picker import scan_sessions_for_cwd
from .transcript_discovery import discover_and_register_transcript

__all__ = [
    "RecoveryBanner",
    "ResumeEntry",
    "build_recovery_keyboard",
    "discover_and_register_transcript",
    "format_session_entry",
    "handle_history_callback",
    "handle_recovery_callback",
    "handle_resume_command_callback",
    "render_banner",
    "restore_command",
    "resume_command",
    "scan_all_sessions",
    "scan_sessions_for_cwd",
    "send_history",
]
