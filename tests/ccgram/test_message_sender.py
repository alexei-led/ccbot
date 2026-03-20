"""Tests for message_sender rate limiting and send-with-fallback."""

import asyncio
from unittest.mock import AsyncMock, patch

from telegram import Message
from telegram.error import RetryAfter, TelegramError

from ccgram.handlers.message_sender import (
    MESSAGE_SEND_INTERVAL,
    _last_send_time,
    _send_with_fallback,
    rate_limit_send,
    strip_plain,
)

import pytest


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    _last_send_time.clear()
    yield
    _last_send_time.clear()


class TestRateLimitSend:
    async def test_first_call_no_wait(self) -> None:
        with patch(
            "ccgram.handlers.message_sender.asyncio.sleep",
            new_callable=AsyncMock,
            spec=asyncio.sleep,
        ) as mock_sleep:
            await rate_limit_send(123)
            mock_sleep.assert_not_called()

    async def test_second_call_within_interval_waits(self) -> None:
        await rate_limit_send(123)

        with patch(
            "ccgram.handlers.message_sender.asyncio.sleep",
            new_callable=AsyncMock,
            spec=asyncio.sleep,
        ) as mock_sleep:
            await rate_limit_send(123)
            mock_sleep.assert_called_once()
            wait_time = mock_sleep.call_args[0][0]
            assert 0 < wait_time <= MESSAGE_SEND_INTERVAL

    async def test_different_chat_ids_independent(self) -> None:
        await rate_limit_send(1)

        with patch(
            "ccgram.handlers.message_sender.asyncio.sleep",
            new_callable=AsyncMock,
            spec=asyncio.sleep,
        ) as mock_sleep:
            await rate_limit_send(2)
            mock_sleep.assert_not_called()

    async def test_updates_last_send_time(self) -> None:
        assert 123 not in _last_send_time
        await rate_limit_send(123)
        assert 123 in _last_send_time
        first_time = _last_send_time[123]

        await asyncio.sleep(0.01)
        await rate_limit_send(123)
        assert _last_send_time[123] > first_time


class TestSendWithFallback:
    async def test_entity_success(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.return_value = sent

        result = await _send_with_fallback(bot, 123, "hello")
        assert result is sent
        bot.send_message.assert_called_once()
        # Entity-based: should have entities param, no parse_mode
        call_kwargs = bot.send_message.call_args.kwargs
        assert "entities" in call_kwargs
        assert "parse_mode" not in call_kwargs

    async def test_fallback_to_plain(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.side_effect = [TelegramError("entity error"), sent]

        result = await _send_with_fallback(bot, 123, "hello")
        assert result is sent
        assert bot.send_message.call_count == 2
        # Fallback: no entities, no parse_mode
        fallback_kwargs = bot.send_message.call_args_list[1].kwargs
        assert "parse_mode" not in fallback_kwargs
        assert "entities" not in fallback_kwargs

    async def test_both_fail_returns_none(self) -> None:
        bot = AsyncMock()
        bot.send_message.side_effect = [
            TelegramError("entity fail"),
            TelegramError("plain fail"),
        ]

        result = await _send_with_fallback(bot, 123, "hello")
        assert result is None

    async def test_retry_after_sleeps_and_retries(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.side_effect = [RetryAfter(1), sent]

        result = await _send_with_fallback(bot, 123, "hello")
        assert result is sent
        assert bot.send_message.call_count == 2

    async def test_retry_after_then_permanent_fail_returns_none(self) -> None:
        bot = AsyncMock()
        bot.send_message.side_effect = [
            RetryAfter(1),
            TelegramError("permanent fail"),
        ]
        result = await _send_with_fallback(bot, 123, "hello")
        assert result is None
        assert bot.send_message.call_count == 2

    async def test_plain_text_retry_after_then_success(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.side_effect = [
            TelegramError("entity fail"),
            RetryAfter(1),
            sent,
        ]
        result = await _send_with_fallback(bot, 123, "hello")
        assert result is sent
        assert bot.send_message.call_count == 3

    async def test_plain_text_retry_after_then_permanent_fail(self) -> None:
        bot = AsyncMock()
        bot.send_message.side_effect = [
            TelegramError("entity fail"),
            RetryAfter(1),
            TelegramError("plain also dead"),
        ]
        result = await _send_with_fallback(bot, 123, "hello")
        assert result is None
        assert bot.send_message.call_count == 3

    async def test_bold_formatting_sends_entities(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.return_value = sent

        await _send_with_fallback(bot, 123, "**bold text**")

        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "bold text"
        entities = call_kwargs["entities"]
        assert len(entities) >= 1
        assert any(e.type == "bold" for e in entities)


class TestStripPlain:
    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            pytest.param(">line1\n>line2", "line1\nline2", id="blockquote-prefix"),
            pytest.param(">content||", "content", id="expandable-quote-close"),
            pytest.param(
                ">first||\n>second||",
                "first\nsecond",
                id="expandable-quote-multi",
            ),
            pytest.param("plain text here", "plain text here", id="plain-passthrough"),
            pytest.param("", "", id="empty-string"),
        ],
    )
    def test_strip_plain(self, input_text: str, expected: str) -> None:
        assert strip_plain(input_text) == expected
