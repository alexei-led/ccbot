"""Text subpackage — text-message orchestrator and step functions.

Bundles ``text_handler`` (UI guards → unbound topic → dead window
recovery → message forwarding chain). Each step returns ``True`` if it
handled the request (stop) or ``False`` to continue.

Public surface re-exported here is what ``bot.py`` imports; module
internals stay private.
"""

from .text_handler import handle_text_message

__all__ = [
    "handle_text_message",
]

# Note: ``text_handler`` (the top-level MessageHandler callback) is imported
# directly from ``handlers.text.text_handler`` rather than re-exported here
# to avoid shadowing the same-named submodule attribute on the package.
