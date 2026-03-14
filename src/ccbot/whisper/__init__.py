"""Whisper transcription provider abstraction.

Provides a pluggable interface for audio transcription using OpenAI-compatible
APIs (OpenAI, Groq, etc.).
"""

import os

from .base import WhisperTranscriber
from .openai_compat import OpenAICompatTranscriber

_PROVIDERS = {
    "openai": {"base_url": None, "model": "whisper-1", "api_key_env": "OPENAI_API_KEY"},
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3",
        "api_key_env": "GROQ_API_KEY",
    },
}


def get_transcriber() -> WhisperTranscriber | None:
    """Create and return a Whisper transcriber based on config.

    Returns None if whisper_provider is not configured (empty string).
    """
    # Import singleton instance
    from ccbot.config import config

    provider = config.whisper_provider
    if not provider:
        return None

    # Get provider defaults
    provider_info = _PROVIDERS.get(provider)
    if not provider_info:
        msg = f"Unknown whisper provider: {provider}"
        raise ValueError(msg)

    # Determine API key: config value overrides env var
    api_key = config.whisper_api_key
    if not api_key:
        api_key_env = provider_info["api_key_env"]
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            msg = f"No API key found: set {api_key_env} or CCBOT_WHISPER_API_KEY"
            raise ValueError(msg)

    # Determine base_url: config value overrides default
    base_url = config.whisper_base_url or provider_info["base_url"]

    # Determine model: config value overrides default
    model = config.whisper_model or provider_info["model"]

    # Language can be None (let the API detect)
    language = config.whisper_language or None

    return OpenAICompatTranscriber(
        api_key=api_key,
        model=model,
        base_url=base_url,
        language=language,
    )
