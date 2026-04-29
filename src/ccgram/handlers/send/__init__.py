"""Send subpackage — file delivery from the agent's workspace to Telegram.

Bundles the modules that implement the ``/send`` command and its
callbacks: ``send_command`` (file search, paginated browser, upload
helpers, the toolbar entry point), ``send_callbacks`` (browser
navigation: select/dir/page/up/cancel with stale-window guard), and
``send_security`` (multi-layer access control — path containment,
hidden files, secret patterns, gitleaks rules, gitignore, size limit).

Public surface re-exported here is the entry point for ``bot.py``,
``handlers/toolbar_callbacks.py`` and the rest of ``handlers/``;
internals stay in the per-module files.
"""

from .send_command import (
    build_file_browser,
    build_search_results,
    open_file_browser,
    send_command,
    upload_file,
)
from .send_security import (
    check_gitleaks_rules,
    is_excluded_dir,
    is_gitignored,
    is_hidden,
    is_path_contained,
    matches_secret_pattern,
    validate_sendable,
)

__all__ = [
    "build_file_browser",
    "build_search_results",
    "check_gitleaks_rules",
    "is_excluded_dir",
    "is_gitignored",
    "is_hidden",
    "is_path_contained",
    "matches_secret_pattern",
    "open_file_browser",
    "send_command",
    "upload_file",
    "validate_sendable",
]
