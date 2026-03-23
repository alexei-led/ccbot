"""Tests for bot-level error handler — stale callback queries must not crash."""

from unittest.mock import MagicMock, patch

from telegram.error import BadRequest, Conflict, TelegramError

from ccgram.bot import _error_handler


def _make_context(error: BaseException) -> MagicMock:
    ctx = MagicMock()
    ctx.error = error
    return ctx


class TestErrorHandlerStaleCallback:
    async def test_bad_request_query_too_old_is_debug_not_error(self) -> None:
        ctx = _make_context(BadRequest("Query is too old and response timeout expired"))

        with patch("ccgram.bot.logger") as mock_logger:
            await _error_handler(None, ctx)

        mock_logger.debug.assert_called_once()
        assert "expired" in mock_logger.debug.call_args[0][0]
        mock_logger.error.assert_not_called()

    async def test_bad_request_query_id_invalid_is_debug(self) -> None:
        ctx = _make_context(BadRequest("query id is invalid and too old"))

        with patch("ccgram.bot.logger") as mock_logger:
            await _error_handler(None, ctx)

        mock_logger.debug.assert_called_once()
        mock_logger.error.assert_not_called()

    async def test_other_bad_request_still_logged_as_error(self) -> None:
        ctx = _make_context(BadRequest("Chat not found"))

        with patch("ccgram.bot.logger") as mock_logger:
            await _error_handler(None, ctx)

        mock_logger.error.assert_called_once()
        mock_logger.debug.assert_not_called()

    async def test_other_telegram_error_logged_as_error(self) -> None:
        ctx = _make_context(TelegramError("Network timeout"))

        with patch("ccgram.bot.logger") as mock_logger:
            await _error_handler(None, ctx)

        mock_logger.error.assert_called_once()

    async def test_conflict_triggers_shutdown(self) -> None:
        ctx = _make_context(Conflict("409 Conflict"))

        with (
            patch("ccgram.bot.logger"),
            patch("ccgram.bot.os.kill") as mock_kill,
        ):
            await _error_handler(None, ctx)

        mock_kill.assert_called_once()
