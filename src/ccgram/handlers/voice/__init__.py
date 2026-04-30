"""Voice subpackage — voice message handling and confirm/discard callbacks.

Bundles ``voice_handler`` (download OGG audio, transcribe via the
configured Whisper provider, present confirm/discard inline keyboard)
and ``voice_callbacks`` (``vc:send``/``vc:drop`` callback dispatch:
forward transcribed text to the bound agent window, route via LLM for
shell topics, or discard).

Public surface re-exported here is what ``bot.py`` and
``callback_registry`` import; module internals stay private.
"""

from .voice_callbacks import handle_voice_callback
from .voice_handler import handle_voice_message

__all__ = [
    "handle_voice_callback",
    "handle_voice_message",
]
