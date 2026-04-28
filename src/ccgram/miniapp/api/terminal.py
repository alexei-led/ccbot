"""Live terminal surface — websocket that streams pane content delta-by-delta.

Endpoints:

- ``GET /ws/terminal/{token}`` upgrades to a websocket. Optional query string
  ``?pane=%5`` streams the named pane (validated against the window). Without
  it, the active pane is captured. Tokens are verified via
  :func:`ccgram.miniapp.auth.verify_token`; the resolved ``window_id`` is the
  only window the websocket may stream from.
- ``GET /api/panes/{token}`` returns a JSON list of panes for the window —
  used by the multi-pane grid surface to lay out terminal previews.

Each tick the handler captures the target pane with ANSI colours via
``TmuxManager.capture_pane`` (active) or ``capture_pane_by_id`` (specific).
The result is hashed and only forwarded when it differs from the last frame,
keeping bandwidth proportional to actual change instead of poll cadence.

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
# Per-pane capture: (window_id, pane_id) -> captured text. Used by the
# multi-pane grid for non-active panes; ``None`` falls back to the active
# pane capture above.
_PANE_CAPTURE_KEY: web.AppKey[Callable[[str, str], Awaitable[str | None]]] = web.AppKey(
    "terminal_pane_capture"
)
# Pane lister: window_id -> list of pane dicts (pane_id, active, name, state).
_PANE_LIST_KEY: web.AppKey[Callable[[str], Awaitable[list[dict[str, Any]]]]] = (
    web.AppKey("terminal_pane_list")
)
_POLL_INTERVAL_KEY = web.AppKey("terminal_poll_interval", float)


async def _default_capture(window_id: str) -> str | None:
    """Capture the active pane via the global ``TmuxManager`` singleton."""
    from ...tmux_manager import tmux_manager

    return await tmux_manager.capture_pane(window_id, with_ansi=True)


async def _default_pane_capture(window_id: str, pane_id: str) -> str | None:
    """Capture a specific pane by ID, scoped to ``window_id``."""
    from ...tmux_manager import tmux_manager

    return await tmux_manager.capture_pane_by_id(
        pane_id, with_ansi=True, window_id=window_id
    )


async def _default_pane_list(window_id: str) -> list[dict[str, Any]]:
    """Enumerate panes for a window, merging tmux state + ``WindowState.panes``."""
    from ...tmux_manager import tmux_manager
    from ...window_state_store import window_store

    panes = await tmux_manager.list_panes(window_id)
    state = window_store.window_states.get(window_id)
    persisted = state.panes if state else {}
    out: list[dict[str, Any]] = []
    for pane in panes:
        info = persisted.get(pane.pane_id)
        out.append(
            {
                "pane_id": pane.pane_id,
                "index": pane.index,
                "active": pane.active,
                "command": pane.command,
                "width": pane.width,
                "height": pane.height,
                "name": info.name if info else None,
                "state": info.state if info else ("active" if pane.active else "idle"),
                "subscribed": bool(info.subscribed) if info else False,
            }
        )
    return out


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
    pane_capture = request.app[_PANE_CAPTURE_KEY]
    interval = request.app[_POLL_INTERVAL_KEY]

    try:
        payload = verify_token(token, bot_token=bot_token)
    except InvalidTokenError as exc:
        logger.info("rejected terminal websocket token: %s", exc)
        return web.Response(status=403, text="invalid or expired token")

    pane_id = (request.query.get("pane") or "").strip() or None

    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    await _send_json(
        ws,
        {
            "type": "hello",
            "window_id": payload.window_id,
            "interval": interval,
            "pane_id": pane_id,
        },
    )

    streamer = asyncio.create_task(
        _stream_loop(ws, payload.window_id, capture, pane_capture, pane_id, interval)
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


async def _panes_handler(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    bot_token = request.app[_BOT_TOKEN_KEY]
    pane_list = request.app[_PANE_LIST_KEY]

    try:
        payload = verify_token(token, bot_token=bot_token)
    except InvalidTokenError as exc:
        logger.info("rejected panes list token: %s", exc)
        return web.Response(status=403, text="invalid or expired token")

    try:
        panes = await pane_list(payload.window_id)
    except Exception:  # noqa: BLE001 — surface as 500, never crash the server
        logger.exception("pane list failed for %s", payload.window_id)
        return web.json_response({"error": "list failed"}, status=500)

    return web.json_response({"window_id": payload.window_id, "panes": list(panes)})


async def _stream_loop(
    ws: web.WebSocketResponse,
    window_id: str,
    capture: Callable[[str], Awaitable[str | None]],
    pane_capture: Callable[[str, str], Awaitable[str | None]],
    pane_id: str | None,
    interval: float,
) -> None:
    """Background task: capture pane, emit deltas, sleep, repeat."""
    last_hash: str | None = None
    while not ws.closed:
        try:
            if pane_id is None:
                text = await capture(window_id)
            else:
                text = await pane_capture(window_id, pane_id)
        except Exception:  # noqa: BLE001 — capture failure must not kill stream
            logger.exception(
                "terminal capture failed for %s pane=%s", window_id, pane_id
            )
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
    pane_capture: Callable[[str, str], Awaitable[str | None]] | None = None,
    pane_list: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    """Attach the terminal routes to ``app`` and stash dependencies.

    ``capture`` is injected for tests; production leaves it ``None`` to use
    the global ``TmuxManager`` singleton. ``pane_capture`` and ``pane_list``
    are likewise stub-injectable to bypass tmux during tests.
    ``poll_interval`` is clamped to a minimum of 50 ms to prevent runaway
    loops if a caller misconfigures it.
    """
    interval = max(0.05, float(poll_interval))
    app[_BOT_TOKEN_KEY] = bot_token
    app[_CAPTURE_KEY] = capture or _default_capture
    app[_PANE_CAPTURE_KEY] = pane_capture or _default_pane_capture
    app[_PANE_LIST_KEY] = pane_list or _default_pane_list
    app[_POLL_INTERVAL_KEY] = interval
    app.router.add_get("/ws/terminal/{token}", _terminal_handler)
    app.router.add_get("/api/panes/{token}", _panes_handler)


__all__ = [
    "DEFAULT_POLL_INTERVAL",
    "MAX_FRAME_BYTES",
    "register_terminal_routes",
]
