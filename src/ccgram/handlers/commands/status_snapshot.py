"""Status-snapshot fallback for /status and /stats slash commands.

Some providers (notably Codex) do not always reply natively to /status
or /stats, so ccgram synthesises a one-shot status snapshot from the
transcript when the provider doesn't write its own output. The probe
captures the transcript size before the send, waits briefly, and only
falls back if no provider-native output appeared in the delta.

Public surface is the two helpers used by ``forward.py``:
  - _status_snapshot_probe_offset(): pre-send transcript byte offset
  - _maybe_send_status_snapshot(): post-send transcript reader + reply
"""

from __future__ import annotations


import asyncio

from telegram import Message

from ...providers import get_provider_for_window
from ... import window_query
from ..messaging_pipeline.message_sender import safe_reply

_CODEX_STATUS_FALLBACK_DELAY_SECONDS = 1.2


def _status_snapshot_probe_offset(window_id: str, cc_slash: str) -> int | None:
    """Return transcript file offset before sending a /status(/stats) command."""
    command = cc_slash.split(None, 1)[0].lower()
    if command not in ("/status", "/stats"):
        return None

    view = window_query.view_window(window_id)
    provider = get_provider_for_window(
        window_id, provider_name=view.provider_name if view else None
    )
    if not provider.capabilities.supports_status_snapshot:
        return None

    if not view or not view.transcript_path:
        return None

    try:
        return view.transcript_path.stat().st_size
    except OSError:
        return None


async def _maybe_send_status_snapshot(
    message: Message,
    window_id: str,
    display: str,
    cc_slash: str,
    *,
    since_offset: int | None = None,
) -> None:
    """Send transcript-based status snapshot fallback for /status and /stats."""
    command = cc_slash.split(None, 1)[0].lower()
    if command not in ("/status", "/stats"):
        return

    view = window_query.view_window(window_id)
    provider = get_provider_for_window(
        window_id, provider_name=view.provider_name if view else None
    )
    if not provider.capabilities.supports_status_snapshot:
        return

    if not view or not view.transcript_path:
        await safe_reply(
            message,
            f"[{display}] Status snapshot unavailable (no transcript path).",
        )
        return
    transcript_path = str(view.transcript_path)

    if since_offset is not None:
        await asyncio.sleep(_CODEX_STATUS_FALLBACK_DELAY_SECONDS)
        has_native_output = await asyncio.to_thread(
            provider.has_output_since,
            transcript_path,
            since_offset,
        )
        if has_native_output:
            return

    snapshot = await asyncio.to_thread(
        provider.build_status_snapshot,
        transcript_path,
        display_name=display,
        session_id=view.session_id,
        cwd=view.cwd,
    )
    if snapshot:
        await safe_reply(message, snapshot)
        return

    await safe_reply(
        message,
        f"[{display}] Status snapshot unavailable (transcript unreadable).",
    )
