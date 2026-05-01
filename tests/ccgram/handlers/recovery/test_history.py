"""Tests for history helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.recovery.history import _format_timestamp, send_history
from ccgram.telegram_client import FakeTelegramClient


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        ("ts", "expected"),
        [
            ("2024-01-15T14:32:00.000Z", "14:32"),
            ("2024-01-15T14:32:00Z", "14:32"),
            ("2024-01-15T14:32:00+05:30", "14:32"),
            ("2024-01-15T14:32:59", "14:32"),
            ("2024-01-15 14:32:00", "14:32"),
            ("not-a-timestamp", ""),
            ("", ""),
            (None, ""),
        ],
        ids=[
            "standard-iso-with-Z",
            "no-millis-with-Z",
            "timezone-offset",
            "no-timezone",
            "space-separator",
            "invalid-string",
            "empty-string",
            "none",
        ],
    )
    def test_format_timestamp(self, ts: str | None, expected: str) -> None:
        assert _format_timestamp(ts) == expected


class TestSendHistoryDirectSend:
    """Direct-send mode (catch-up) routes through ``TelegramClient``."""

    async def test_direct_send_uses_client_protocol(self) -> None:
        client = FakeTelegramClient()
        target = MagicMock()
        with (
            patch(
                "ccgram.handlers.recovery.history.session_query.get_recent_messages",
                new_callable=AsyncMock,
                return_value=([], 0),
            ),
            patch("ccgram.handlers.recovery.history.thread_router") as mock_router,
        ):
            mock_router.get_display_name.return_value = "win-name"
            mock_router.resolve_chat_id.return_value = -100
            await send_history(
                target,
                "@7",
                edit=False,
                user_id=42,
                client=client,
                message_thread_id=99,
            )
        assert client.call_count("send_message") == 1
        sent = client.last_call("send_message")
        assert sent is not None
        assert sent.kwargs["chat_id"] == -100
        assert sent.kwargs["message_thread_id"] == 99

    async def test_no_client_falls_back_to_safe_reply(self) -> None:
        target = MagicMock()
        target.reply_text = AsyncMock()
        with patch(
            "ccgram.handlers.recovery.history.session_query.get_recent_messages",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            await send_history(target, "@7", edit=False)
        target.reply_text.assert_awaited()
