"""Shared test helpers for Mini App tests."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode


def make_init_data(
    *,
    bot_token: str,
    user_id: int,
    auth_date: int | None = None,
    extras: dict[str, str] | None = None,
) -> str:
    """Build a signed Telegram WebApp ``initData`` string for the user."""
    params: dict[str, str] = {
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "user": f'{{"id":{int(user_id)},"first_name":"Test"}}',
        "query_id": "AAH",
    }
    if extras:
        params.update(extras)
    pairs = sorted(params.items())
    data_check = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})
