"""Live terminal surface — websocket that streams pane content delta-by-delta.

Endpoint: ``GET /ws/terminal/{token}`` upgrades to a websocket. The token is
verified via :func:`ccgram.miniapp.auth.verify_token`; the resolved
``window_id`` is the only pane the websocket may stream from.

Each tick the handler captures the active pane with ANSI colours via
``TmuxManager.capture_pane(window_id, with_ansi=True)``. The result is hashed
and only forwarded when it differs from the last frame, keeping bandwidth
proportional to actual change instead of poll cadence.

The endpoint is read-only in v3.0; client-side typing is deferred to v3.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from ..auth import InvalidTokenError, verify_token

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Default poll cadence between pane captures (seconds).
DEFAULT_POLL_INTERVAL = 0.2

# Hard cap on a single frame (bytes); larger captures are truncated.
MAX_FRAME_BYTES = 64 * 1024

# Application keys for dependencies injected by ``register_terminal_routes``.
_BOT_TOKEN_KEY = web.AppKey("bot_token", str)
_CAPTURE_KEY: web.AppKey[Callable[[str], Awaitable[str | None]]] = web.AppKey(
    "terminal_capture"
)
_POLL_INTERVAL_KEY = web.AppKey("terminal_poll_interval", float)


async def _default_capture(window_id: str) -> str | None:
    """Capture pane via the global ``TmuxManager`` singleton."""
    from ...tmux_manager import tmux_manager

    return await tmux_manager.capture_pane(window_id, with_ansi=True)


def _hash_frame(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _truncate(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_FRAME_BYTES:
        return text
    return encoded[:MAX_FRAME_BYTES].decode("utf-8", errors="ignore")


async def _send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> bool:
    """Send a JSON message; return False when the socket is no longer open."""
    if ws.closed:
        return False
    try:
        await ws.send_json(payload)
    except ConnectionResetError, RuntimeError:
        return False
    return True


async def _terminal_handler(request: web.Request) -> web.StreamResponse:
    token = request.match_info["token"]
    bot_token = request.app[_BOT_TOKEN_KEY]
    capture = request.app[_CAPTURE_KEY]
    interval = request.app[_POLL_INTERVAL_KEY]

    try:
        payload = verify_token(token, bot_token=bot_token)
    except InvalidTokenError as exc:
        logger.info("rejected terminal websocket token: %s", exc)
        return web.Response(status=403, text="invalid or expired token")

    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    await _send_json(
        ws,
        {
            "type": "hello",
            "window_id": payload.window_id,
            "interval": interval,
        },
    )

    streamer = asyncio.create_task(
        _stream_loop(ws, payload.window_id, capture, interval)
    )
    try:
        # Drain inbound frames so a client close terminates the stream promptly.
        async for msg in ws:
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        streamer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await streamer
        if not ws.closed:
            await ws.close()
    return ws


async def _stream_loop(
    ws: web.WebSocketResponse,
    window_id: str,
    capture: Callable[[str], Awaitable[str | None]],
    interval: float,
) -> None:
    """Background task: capture pane, emit deltas, sleep, repeat."""
    last_hash: str | None = None
    while not ws.closed:
        try:
            text = await capture(window_id)
        except Exception:  # noqa: BLE001 — capture failure must not kill stream
            logger.exception("terminal capture failed for %s", window_id)
            await _send_json(ws, {"type": "error", "message": "capture failed"})
            await asyncio.sleep(interval)
            continue

        if text is None:
            text = ""
        truncated = _truncate(text)
        digest = _hash_frame(truncated)
        if digest != last_hash:
            sent = await _send_json(
                ws,
                {"type": "frame", "text": truncated, "hash": digest},
            )
            if not sent:
                return
            last_hash = digest

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


def register_terminal_routes(
    app: web.Application,
    *,
    bot_token: str,
    capture: Callable[[str], Awaitable[str | None]] | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    """Attach the websocket route to ``app`` and stash dependencies.

    ``capture`` is injected for tests; production leaves it ``None`` to use
    the global ``TmuxManager`` singleton. ``poll_interval`` is clamped to a
    minimum of 50 ms to prevent runaway loops if a caller misconfigures it.
    """
    interval = max(0.05, float(poll_interval))
    app[_BOT_TOKEN_KEY] = bot_token
    app[_CAPTURE_KEY] = capture or _default_capture
    app[_POLL_INTERVAL_KEY] = interval
    app.router.add_get("/ws/terminal/{token}", _terminal_handler)


__all__ = [
    "DEFAULT_POLL_INTERVAL",
    "MAX_FRAME_BYTES",
    "register_terminal_routes",
]
