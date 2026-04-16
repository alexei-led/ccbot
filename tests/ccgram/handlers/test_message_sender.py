import asyncio
from unittest.mock import AsyncMock, patch

from telegram import Message
from telegram.error import RetryAfter, TelegramError

from ccgram.handlers.message_sender import (
    MESSAGE_SEND_INTERVAL,
    _last_send_time,
    _send_with_fallback,
    edit_with_fallback,
    rate_limit_send,
)
from ccgram.expandable_quote import EXPANDABLE_QUOTE_END as EXP_END
from ccgram.expandable_quote import EXPANDABLE_QUOTE_START as EXP_START

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

    async def test_retry_after_then_permanent_fail_falls_through_to_plain(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.side_effect = [
            RetryAfter(1),
            TelegramError("permanent fail"),
            sent,
        ]
        result = await _send_with_fallback(bot, 123, "hello")
        assert result is sent
        assert bot.send_message.call_count == 3

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


class TestEditWithFallback:
    async def test_entity_success(self) -> None:
        bot = AsyncMock()
        result = await edit_with_fallback(bot, 123, 1, "hello")
        assert result is True
        call_kwargs = bot.edit_message_text.call_args.kwargs
        assert "entities" in call_kwargs

    async def test_entity_fail_plain_success(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = [TelegramError("entity fail"), None]
        result = await edit_with_fallback(bot, 123, 1, "hello")
        assert result is True
        assert bot.edit_message_text.call_count == 2
        fallback_kwargs = bot.edit_message_text.call_args_list[1].kwargs
        assert "entities" not in fallback_kwargs

    async def test_both_fail_returns_false(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = [
            TelegramError("entity fail"),
            TelegramError("plain fail"),
        ]
        result = await edit_with_fallback(bot, 123, 1, "hello")
        assert result is False

    async def test_retry_after_reraised(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = RetryAfter(5)
        with pytest.raises(RetryAfter):
            await edit_with_fallback(bot, 123, 1, "hello")

    async def test_retry_after_in_fallback_reraised(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = [
            TelegramError("entity fail"),
            RetryAfter(5),
        ]
        with pytest.raises(RetryAfter):
            await edit_with_fallback(bot, 123, 1, "hello")


class TestFallbackNoSentinelLeak:
    async def test_no_sentinel_bytes_in_fallback(self) -> None:
        bot = AsyncMock()
        sent = AsyncMock(spec=Message)
        bot.send_message.side_effect = [TelegramError("entity error"), sent]

        text_with_sentinels = f"before {EXP_START}quoted{EXP_END} after"
        await _send_with_fallback(bot, 123, text_with_sentinels)

        fallback_text = bot.send_message.call_args_list[1].kwargs.get(
            "text",
            (
                bot.send_message.call_args_list[1].args[0]
                if bot.send_message.call_args_list[1].args
                else ""
            ),
        )
        assert "\x02" not in fallback_text

    async def test_edit_fallback_no_sentinel_bytes(self) -> None:
        bot = AsyncMock()
        bot.edit_message_text.side_effect = [TelegramError("entity fail"), None]

        text_with_sentinels = f"before {EXP_START}quoted{EXP_END} after"
        await edit_with_fallback(bot, 123, 1, text_with_sentinels)

        fallback_kwargs = bot.edit_message_text.call_args_list[1].kwargs
        assert "\x02" not in fallback_kwargs["text"]
