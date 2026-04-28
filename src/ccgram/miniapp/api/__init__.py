"""Mini App API surfaces — websocket and HTTP endpoints scoped per window.

Submodules attach routes onto the aiohttp ``Application`` built in
:mod:`ccgram.miniapp.server` so the web layer stays declarative.
"""

from .terminal import register_terminal_routes
from .transcript import register_transcript_routes

__all__ = ["register_terminal_routes", "register_transcript_routes"]
