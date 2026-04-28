from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, RetryAfter, TelegramError

from ccgram import telegram_draft
from ccgram.telegram_draft import (
    DRAFT_LEGACY,
    DRAFT_STREAMING,
    DraftStream,
    is_draft_unavailable,
    is_peer_draft_unsupported,
    mark_draft_unavailable,
    mark_peer_draft_unsupported,
    reset_draft_state,
)


@pytest.fixture(autouse=True)
def _reset_draft_state():
    reset_draft_state()
    yield
    reset_draft_state()


def _make_bot(*, draft_result=None, send_id=42):
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value=draft_result or {"message_id": 11})
    sent_msg = MagicMock(message_id=send_id)
    bot.send_message = AsyncMock(return_value=sent_msg)
    bot.edit_message_text = AsyncMock(return_value=None)
    bot.delete_message = AsyncMock(return_value=None)
    return bot


class TestDraftStreamHappyPath:
    async def test_streaming_start_uses_draft_api(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100, message_thread_id=5)

        mid = await stream.start("hello")

        assert mid == 7
        assert stream.mode == DRAFT_STREAMING
        bot.do_api_request.assert_awaited_once()
        method, kwargs = (
            bot.do_api_request.call_args.args[0],
            bot.do_api_request.call_args.kwargs,
        )
        assert method == "sendMessageDraft"
        assert kwargs["api_kwargs"]["chat_id"] == 100
        assert kwargs["api_kwargs"]["text"] == "hello"
        assert kwargs["api_kwargs"]["message_thread_id"] == 5
        bot.send_message.assert_not_awaited()

    async def test_append_then_finalize_streaming(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        await stream.start("a")
        await stream.append("b")
        await stream.append("c")
        await stream.finalize()

        # 1 sendMessageDraft + 2 editMessageDraft + 1 finalizeMessageDraft
        assert bot.do_api_request.await_count == 4
        called_methods = [c.args[0] for c in bot.do_api_request.call_args_list]
        assert called_methods == [
            "sendMessageDraft",
            "editMessageDraft",
            "editMessageDraft",
            "finalizeMessageDraft",
        ]
        # Buffer accumulates
        last_call = bot.do_api_request.call_args_list[-1]
        assert last_call.kwargs["api_kwargs"]["text"] == "abc"
        assert stream.closed is True

    async def test_finalize_with_replacement_text(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        await stream.start("draft")
        await stream.finalize("final")

        last_call = bot.do_api_request.call_args_list[-1]
        assert last_call.args[0] == "finalizeMessageDraft"
        assert last_call.kwargs["api_kwargs"]["text"] == "final"


class TestDraftStreamFallback:
    async def test_400_method_not_found_flips_global_flag(self) -> None:
        bot = _make_bot()
        bot.do_api_request.side_effect = BadRequest("method not found")

        stream = DraftStream(bot, chat_id=100)
        mid = await stream.start("hi")

        assert mid == 42
        assert stream.mode == DRAFT_LEGACY
        assert is_draft_unavailable() is True
        bot.send_message.assert_awaited_once()

    async def test_subsequent_streams_skip_probe_after_flag_set(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()

        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")

        assert stream.mode == DRAFT_LEGACY
        bot.do_api_request.assert_not_awaited()
        bot.send_message.assert_awaited_once()

    async def test_other_badrequest_degrades_without_flag(self) -> None:
        bot = _make_bot()
        bot.do_api_request.side_effect = BadRequest("internal server error")

        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")

        assert stream.mode == DRAFT_LEGACY
        # Generic BadRequest does not set process-wide unavailable
        assert is_draft_unavailable() is False

    async def test_legacy_mode_uses_edit_message_text(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()

        stream = DraftStream(bot, chat_id=100)
        await stream.start("a")
        await stream.append("b")
        await stream.finalize()

        bot.do_api_request.assert_not_awaited()
        # 2 edit calls (append + finalize), 1 send_message at start
        assert bot.send_message.await_count == 1
        assert bot.edit_message_text.await_count == 2
        last_call = bot.edit_message_text.call_args_list[-1]
        assert last_call.kwargs["text"] == "ab"

    async def test_self_degrade_after_repeated_failures(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        # Start succeeds; subsequent calls raise transient errors twice.
        bot.do_api_request.side_effect = [
            {"message_id": 7},
            TelegramError("transient1"),
            TelegramError("transient2"),
        ]

        stream = DraftStream(bot, chat_id=100)
        await stream.start("a")
        assert stream.mode == DRAFT_STREAMING

        await stream.append("b")
        # First failure does not degrade
        assert stream.mode == DRAFT_STREAMING

        await stream.append("c")
        # Second failure degrades to legacy and re-pushes via edit_message_text
        assert stream.mode == DRAFT_LEGACY
        bot.edit_message_text.assert_awaited()


class TestDraftStreamWarningSuppressed:
    async def test_send_warning_filtered(self) -> None:
        import warnings

        from telegram.warnings import PTBUserWarning

        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await stream.start("hi")

        nag = [
            w
            for w in caught
            if issubclass(w.category, PTBUserWarning)
            and "sendMessageDraft" in str(w.message)
        ]
        assert nag == []


class TestDraftStreamTransientLegacyFailure:
    async def test_streaming_badrequest_then_legacy_timeout_returns_none(self) -> None:
        from telegram.error import TimedOut

        bot = _make_bot()
        bot.do_api_request.side_effect = BadRequest("Textdraft_peer_invalid")
        bot.send_message.side_effect = TimedOut("Timed out")

        stream = DraftStream(bot, chat_id=100, message_thread_id=5)
        mid = await stream.start("hi")

        assert mid is None
        assert stream.message_id is None

    async def test_legacy_only_path_timeout_returns_none(self) -> None:
        from telegram.error import TimedOut

        mark_draft_unavailable("test")
        bot = _make_bot()
        bot.send_message.side_effect = TimedOut("Timed out")

        stream = DraftStream(bot, chat_id=100)
        mid = await stream.start("hi")

        assert mid is None

    async def test_legacy_only_path_telegram_error_returns_none(self) -> None:
        from telegram.error import TelegramError as TgError

        mark_draft_unavailable("test")
        bot = _make_bot()
        # Non-transient TelegramError (e.g. BadRequest, RetryAfter, generic)
        # must not propagate — the stream is best-effort and silent.
        bot.send_message.side_effect = TgError("flood")

        stream = DraftStream(bot, chat_id=100)
        mid = await stream.start("hi")

        assert mid is None

    async def test_empty_initial_text_returns_none_without_api_call(self) -> None:
        bot = _make_bot()

        stream = DraftStream(bot, chat_id=100)
        mid = await stream.start("")

        assert mid is None
        bot.do_api_request.assert_not_awaited()
        bot.send_message.assert_not_awaited()


class TestDraftStreamPeerCache:
    async def test_peer_invalid_caches_per_peer(self) -> None:
        bot = _make_bot()
        bot.do_api_request.side_effect = BadRequest("Textdraft_peer_invalid")

        stream = DraftStream(bot, chat_id=100, message_thread_id=5)
        await stream.start("hi")

        assert stream.mode == DRAFT_LEGACY
        assert is_draft_unavailable() is False  # only this peer
        assert is_peer_draft_unsupported(100, 5) is True

    async def test_subsequent_stream_to_same_peer_skips_probe(self) -> None:
        mark_peer_draft_unsupported(100, 5)
        bot = _make_bot()

        stream = DraftStream(bot, chat_id=100, message_thread_id=5)
        await stream.start("hi")

        assert stream.mode == DRAFT_LEGACY
        bot.do_api_request.assert_not_awaited()
        bot.send_message.assert_awaited_once()

    async def test_different_peer_still_probes(self) -> None:
        mark_peer_draft_unsupported(100, 5)
        bot = _make_bot(draft_result={"message_id": 7})

        stream = DraftStream(bot, chat_id=200, message_thread_id=5)
        await stream.start("hi")

        assert stream.mode == DRAFT_STREAMING
        bot.do_api_request.assert_awaited_once()

    async def test_peer_invalid_marker_variants(self) -> None:
        for marker in ("draft_peer_invalid", "PEER_INVALID", "Bad: Chat not found"):
            reset_draft_state()
            bot = _make_bot()
            bot.do_api_request.side_effect = BadRequest(marker)

            stream = DraftStream(bot, chat_id=100)
            await stream.start("hi")

            assert is_peer_draft_unsupported(100, None) is True, marker


class TestDraftStreamRetryAfter:
    async def test_retry_after_on_start_falls_back(self, monkeypatch) -> None:
        async def _no_sleep(_):
            return None

        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        bot = _make_bot()
        bot.do_api_request.side_effect = RetryAfter(0)

        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")

        assert stream.mode == DRAFT_LEGACY
        bot.send_message.assert_awaited_once()


class TestDraftStreamAbort:
    async def test_abort_deletes_message(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        await stream.start("hi")
        await stream.abort()

        assert stream.closed is True
        bot.delete_message.assert_awaited_once_with(chat_id=100, message_id=7)

    async def test_abort_swallows_telegram_error(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        bot.delete_message.side_effect = TelegramError("gone")

        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")
        await stream.abort()

        assert stream.closed is True

    async def test_abort_before_start_is_safe(self) -> None:
        bot = _make_bot()
        stream = DraftStream(bot, chat_id=100)
        await stream.abort()
        assert stream.closed is True
        bot.delete_message.assert_not_awaited()


class TestDraftStreamGuards:
    async def test_double_start_raises(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")
        with pytest.raises(RuntimeError, match="start called twice"):
            await stream.start("again")

    async def test_append_before_start_raises(self) -> None:
        bot = _make_bot()
        stream = DraftStream(bot, chat_id=100)
        with pytest.raises(RuntimeError, match="not started"):
            await stream.append("x")

    async def test_append_after_finalize_raises(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)
        await stream.start("hi")
        await stream.finalize()
        with pytest.raises(RuntimeError, match="already closed"):
            await stream.append("x")


class TestDraftStreamTextSafety:
    async def test_text_truncated_to_4096(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        await stream.start("a" * 5000)

        sent_text = bot.do_api_request.call_args.kwargs["api_kwargs"]["text"]
        assert len(sent_text) == 4096
        # Buffer is full; truncation only at send/edit boundary
        assert stream.text == "a" * 4096

    async def test_legacy_not_modified_is_silent(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()
        bot.edit_message_text.side_effect = BadRequest(
            "Bad Request: message is not modified"
        )

        stream = DraftStream(bot, chat_id=100)
        await stream.start("a")
        # Should not raise
        await stream.append("a")
        assert stream.mode == DRAFT_LEGACY


class TestModuleStateHelpers:
    def test_mark_unavailable_idempotent(self) -> None:
        mark_draft_unavailable("first")
        mark_draft_unavailable("second")
        assert telegram_draft.draft_unavailable_reason() == "first"

    def test_reset_clears_state(self) -> None:
        mark_draft_unavailable("x")
        assert is_draft_unavailable() is True
        reset_draft_state()
        assert is_draft_unavailable() is False
        assert telegram_draft.draft_unavailable_reason() == ""


class TestDraftStreamReplace:
    async def test_replace_streaming_pushes_full_text(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)

        await stream.start("first")
        await stream.replace("second")

        called_methods = [c.args[0] for c in bot.do_api_request.call_args_list]
        assert called_methods == ["sendMessageDraft", "editMessageDraft"]
        last = bot.do_api_request.call_args_list[-1]
        assert last.kwargs["api_kwargs"]["text"] == "second"
        assert stream.text == "second"

    async def test_replace_legacy_pushes_via_edit_message_text(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()

        stream = DraftStream(bot, chat_id=100)
        await stream.start("first")
        await stream.replace("second")

        bot.send_message.assert_awaited_once()
        bot.edit_message_text.assert_awaited_once()
        last = bot.edit_message_text.call_args_list[-1]
        assert last.kwargs["text"] == "second"
        assert stream.text == "second"

    async def test_replace_after_finalize_raises(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100)
        await stream.start("first")
        await stream.finalize()

        with pytest.raises(RuntimeError, match="already closed"):
            await stream.replace("second")


class TestDraftStreamReplyMarkup:
    @staticmethod
    def _markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Esc", callback_data="esc")]]
        )

    async def test_streaming_includes_serialized_markup(self) -> None:
        bot = _make_bot(draft_result={"message_id": 7})
        stream = DraftStream(bot, chat_id=100, reply_markup=self._markup())
        await stream.start("hi")

        kw = bot.do_api_request.call_args.kwargs["api_kwargs"]
        assert "reply_markup" in kw
        assert isinstance(kw["reply_markup"], dict)
        assert kw["reply_markup"]["inline_keyboard"][0][0]["text"] == "Esc"

    async def test_legacy_passes_inline_keyboard_through(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()
        markup = self._markup()
        stream = DraftStream(bot, chat_id=100, reply_markup=markup)

        await stream.start("hi")
        assert bot.send_message.call_args.kwargs["reply_markup"] is markup

        await stream.replace("more")
        assert bot.edit_message_text.call_args.kwargs["reply_markup"] is markup

    async def test_replace_can_clear_markup(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()
        stream = DraftStream(bot, chat_id=100, reply_markup=self._markup())

        await stream.start("hi")
        await stream.replace("bye", reply_markup=None)

        # Telegram leaves the existing keyboard untouched when reply_markup
        # is omitted, so an explicit clear must serialize to an empty
        # InlineKeyboardMarkup for the keyboard to actually disappear.
        last_edit = bot.edit_message_text.call_args_list[-1]
        markup = last_edit.kwargs["reply_markup"]
        assert isinstance(markup, InlineKeyboardMarkup)
        assert markup.inline_keyboard == ()

    async def test_finalize_can_update_markup(self) -> None:
        mark_draft_unavailable("test")
        bot = _make_bot()
        stream = DraftStream(bot, chat_id=100)

        await stream.start("hi")
        await stream.finalize("done", reply_markup=self._markup())

        last_edit = bot.edit_message_text.call_args_list[-1]
        assert isinstance(last_edit.kwargs["reply_markup"], InlineKeyboardMarkup)
