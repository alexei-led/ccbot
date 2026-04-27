import hashlib
import hmac
from urllib.parse import urlencode

import pytest

from ccgram.miniapp.auth import (
    DEFAULT_TOKEN_TTL,
    InvalidTokenError,
    TokenPayload,
    sign_token,
    validate_init_data,
    verify_token,
)

BOT = "1234:abcdef"
WID = "ccgram:@7"
UID = 42
NOW = 1_700_000_000.0


def test_sign_then_verify_roundtrip():
    tok = sign_token(bot_token=BOT, window_id=WID, user_id=UID, now=NOW)
    payload = verify_token(tok, bot_token=BOT, now=NOW + 10)
    assert isinstance(payload, TokenPayload)
    assert payload.window_id == WID
    assert payload.user_id == UID
    assert payload.exp == int(NOW) + DEFAULT_TOKEN_TTL


def test_verify_rejects_expired_token():
    tok = sign_token(bot_token=BOT, window_id=WID, user_id=UID, ttl=60, now=NOW)
    with pytest.raises(InvalidTokenError, match="expired"):
        verify_token(tok, bot_token=BOT, now=NOW + 120)


def test_verify_rejects_wrong_bot_token():
    tok = sign_token(bot_token=BOT, window_id=WID, user_id=UID, now=NOW)
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_token(tok, bot_token="9999:other", now=NOW + 10)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not.a.token.at.all",
        "no_dot_here",
        "...",
        "!!!.!!!",
    ],
)
def test_verify_rejects_malformed(bad):
    with pytest.raises(InvalidTokenError):
        verify_token(bad, bot_token=BOT, now=NOW)


def test_verify_rejects_tampered_payload():
    tok = sign_token(bot_token=BOT, window_id=WID, user_id=UID, now=NOW)
    body, sig = tok.split(".")
    # Flip a byte in body — sig won't match.
    tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
    with pytest.raises(InvalidTokenError, match="signature"):
        verify_token(tampered, bot_token=BOT, now=NOW + 10)


def test_signing_key_rejects_empty_bot_token():
    with pytest.raises(InvalidTokenError, match="bot_token"):
        sign_token(bot_token="", window_id=WID, user_id=UID, now=NOW)


def _make_init_data(bot_token: str, params: dict[str, str]) -> str:
    """Build a signed initData string per the WebApp legacy HMAC spec."""
    pairs = sorted(params.items())
    data_check = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


def test_validate_init_data_happy_path():
    params = {
        "auth_date": str(int(NOW)),
        "user": '{"id":42,"first_name":"Alice"}',
        "query_id": "AAH",
    }
    init = _make_init_data(BOT, params)
    out = validate_init_data(init, bot_token=BOT, now=NOW + 10)
    assert out["query_id"] == "AAH"
    assert out["hash"]


def test_validate_init_data_rejects_bad_signature():
    params = {"auth_date": str(int(NOW)), "user": '{"id":1}'}
    init = _make_init_data(BOT, params)
    with pytest.raises(InvalidTokenError, match="signature"):
        validate_init_data(init, bot_token="other:token", now=NOW + 10)


def test_validate_init_data_rejects_missing_hash():
    init = urlencode({"auth_date": str(int(NOW)), "user": '{"id":1}'})
    with pytest.raises(InvalidTokenError, match="missing hash"):
        validate_init_data(init, bot_token=BOT, now=NOW + 10)


def test_validate_init_data_rejects_stale_auth_date():
    params = {"auth_date": str(int(NOW)), "user": '{"id":1}'}
    init = _make_init_data(BOT, params)
    with pytest.raises(InvalidTokenError, match="stale"):
        validate_init_data(init, bot_token=BOT, max_age=60, now=NOW + 3600)


def test_validate_init_data_rejects_non_numeric_auth_date():
    params = {"auth_date": "not-a-number", "user": '{"id":1}'}
    init = _make_init_data(BOT, params)
    with pytest.raises(InvalidTokenError, match="auth_date"):
        validate_init_data(init, bot_token=BOT, now=NOW + 10)


def test_validate_init_data_rejects_empty():
    with pytest.raises(InvalidTokenError, match="empty"):
        validate_init_data("", bot_token=BOT)
