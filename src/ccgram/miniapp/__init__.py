"""Mini App backend — optional aiohttp web surface for Telegram WebApps.

The Mini App is gated on ``CCGRAM_MINIAPP_BASE_URL``. When unset, neither the
HTTP server nor the inline launch button are exposed. When set, the server
serves a single-page app from ``static/`` and opens token-scoped routes per
window.

Sub-modules:
- ``auth``: HMAC-signed window tokens + Telegram WebApp ``initData`` validation
- ``server``: aiohttp app factory + lifecycle helpers (``start_server``, ``stop_server``)
"""

from .auth import (
    InvalidTokenError,
    TokenPayload,
    authorize_api_request,
    init_data_user_id,
    sign_token,
    validate_init_data,
    verify_token,
)
from .server import build_app, start_server, stop_server

__all__ = [
    "InvalidTokenError",
    "TokenPayload",
    "authorize_api_request",
    "build_app",
    "init_data_user_id",
    "sign_token",
    "start_server",
    "stop_server",
    "validate_init_data",
    "verify_token",
]
