from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Bot

from ccgram.handlers.msg_delivery import reset_delivery_state
from ccgram.mailbox import Message


@pytest.fixture(autouse=True)
def _clean_state():
    reset_delivery_state()
    yield
    reset_delivery_state()


def _make_message(
    *,
    id: str = "123-abc",
    from_id: str = "ccgram:@0",
    to_id: str = "ccgram:@5",
    type: str = "request",
    body: str = "What is the API contract?",
    subject: str = "API contract query",
    context: dict[str, str] | None = None,
    created_at: str = "2026-03-29T10:45:00+00:00",
    status: str = "pending",
    ttl_minutes: int = 60,
    reply_to: str | None = None,
) -> Message:
    return Message(
        id=id,
        from_id=from_id,
        to_id=to_id,
        type=type,
        body=body,
        subject=subject,
        context=context or {"window_name": "payment-svc", "branch": "feat/refund"},
        created_at=created_at,
        status=status,
        ttl_minutes=ttl_minutes,
        reply_to=reply_to,
    )


def _mock_router():
    router = MagicMock()
    router.iter_thread_bindings.return_value = [
        (111, 1001, "@0"),
        (111, 1002, "@5"),
    ]
    router.resolve_chat_id.return_value = -100123
    router.get_display_name.side_effect = lambda wid: {
        "@0": "payment-svc",
        "@5": "api-gateway",
    }.get(wid, wid)
    return router


class TestNotifyMessageSent:
    @pytest.mark.asyncio
    async def test_sends_compact_line_to_sender_topic(self):
        from ccgram.handlers.msg_telegram import notify_message_sent

        bot = AsyncMock(spec=Bot)
        msg = _make_message()
        router = _mock_router()

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_message_sent(bot, "ccgram:@0", "ccgram:@5", msg)

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert args[0] is bot
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        assert "@5" in text or "api-gateway" in text
        assert "request" in text.lower() or "API contract" in text
        assert kwargs.get("disable_notification") is True

    @pytest.mark.asyncio
    async def test_skips_when_no_sender_binding(self):
        from ccgram.handlers.msg_telegram import notify_message_sent

        bot = AsyncMock(spec=Bot)
        msg = _make_message()
        router = MagicMock()
        router.iter_thread_bindings.return_value = []

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await notify_message_sent(bot, "ccgram:@0", "ccgram:@5", msg)

        mock_send.assert_not_called()


class TestNotifyReplyReceived:
    @pytest.mark.asyncio
    async def test_sends_reply_notification_to_original_sender_topic(self):
        from ccgram.handlers.msg_telegram import notify_reply_received

        bot = AsyncMock(spec=Bot)
        original = _make_message(from_id="ccgram:@0", to_id="ccgram:@5")
        reply = _make_message(
            id="456-def",
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            type="reply",
            body="Here is the answer",
            reply_to="123-abc",
        )
        router = _mock_router()

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_reply_received(bot, original, reply)

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        assert "reply" in text.lower() or "Reply" in text


class TestNotifyPendingShell:
    @pytest.mark.asyncio
    async def test_sends_pending_message_to_shell_topic(self):
        from ccgram.handlers.msg_telegram import notify_pending_shell

        bot = AsyncMock(spec=Bot)
        msg = _make_message(to_id="ccgram:@8")
        router = _mock_router()
        router.iter_thread_bindings.return_value = [(111, 1008, "@8")]
        router.get_display_name.return_value = "infra-shell"

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_pending_shell(bot, "ccgram:@8", msg)

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        assert "payment-svc" in text or "@0" in text
        assert kwargs.get("disable_notification") is True

    @pytest.mark.asyncio
    async def test_skips_when_no_binding(self):
        from ccgram.handlers.msg_telegram import notify_pending_shell

        bot = AsyncMock(spec=Bot)
        msg = _make_message()
        router = MagicMock()
        router.iter_thread_bindings.return_value = []

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            await notify_pending_shell(bot, "ccgram:@5", msg)

        mock_send.assert_not_called()


class TestNotificationGrouping:
    @pytest.mark.asyncio
    async def test_multiple_messages_merged_in_delivered_notification(self):
        from ccgram.handlers.msg_telegram import notify_messages_delivered

        bot = AsyncMock(spec=Bot)
        msgs = [
            _make_message(id="1", subject="Query 1", from_id="ccgram:@0"),
            _make_message(id="2", subject="Query 2", from_id="ccgram:@3"),
        ]
        router = _mock_router()

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_messages_delivered(bot, "ccgram:@5", msgs)

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        assert "2" in text


class TestPeerMessageReaction:
    @pytest.mark.asyncio
    async def test_delivered_notification_gets_inbox_reaction(self):
        from ccgram.handlers import msg_telegram
        from ccgram.handlers.msg_telegram import notify_messages_delivered

        bot = AsyncMock(spec=Bot)
        msgs = [_make_message()]
        router = _mock_router()

        sent = MagicMock()
        sent.message_id = 555

        with (
            patch.object(msg_telegram, "thread_router", router),
            patch.object(
                msg_telegram, "rate_limit_send_message", new_callable=AsyncMock
            ) as mock_send,
            patch.object(msg_telegram, "react", new_callable=AsyncMock) as mock_react,
        ):
            mock_send.return_value = sent
            await notify_messages_delivered(bot, "ccgram:@5", msgs)

        mock_react.assert_awaited_once()
        args = mock_react.call_args.args
        assert args[0] is bot
        assert args[2] == 555
        # 📬 inbox semantics — fixed allowed-set fallback.
        from ccgram.handlers.reactions import REACT_INBOX

        assert args[3] == REACT_INBOX

    @pytest.mark.asyncio
    async def test_no_reaction_when_send_fails(self):
        from ccgram.handlers import msg_telegram
        from ccgram.handlers.msg_telegram import notify_messages_delivered

        bot = AsyncMock(spec=Bot)
        msgs = [_make_message()]
        router = _mock_router()

        with (
            patch.object(msg_telegram, "thread_router", router),
            patch.object(
                msg_telegram, "rate_limit_send_message", new_callable=AsyncMock
            ) as mock_send,
            patch.object(msg_telegram, "react", new_callable=AsyncMock) as mock_react,
        ):
            mock_send.return_value = None
            await notify_messages_delivered(bot, "ccgram:@5", msgs)

        mock_react.assert_not_awaited()


class TestSilentDelivery:
    @pytest.mark.asyncio
    async def test_all_notifications_are_silent(self):
        from ccgram.handlers.msg_telegram import (
            notify_message_sent,
            notify_pending_shell,
        )

        bot = AsyncMock(spec=Bot)
        msg = _make_message()
        router = _mock_router()

        funcs_and_args = [
            (notify_message_sent, (bot, "ccgram:@0", "ccgram:@5", msg)),
            (notify_pending_shell, (bot, "ccgram:@5", msg)),
        ]

        for func, call_args in funcs_and_args:
            with (
                patch("ccgram.handlers.msg_telegram.thread_router", router),
                patch(
                    "ccgram.handlers.msg_telegram.rate_limit_send_message",
                    new_callable=AsyncMock,
                ) as mock_send,
            ):
                mock_send.return_value = MagicMock()
                await func(*call_args)

                if mock_send.called:
                    _, kwargs = mock_send.call_args
                    assert kwargs.get("disable_notification") is True, (
                        f"{func.__name__} did not set disable_notification=True"
                    )


class TestNotifyLoopDetected:
    @pytest.mark.asyncio
    async def test_sends_alert_with_keyboard(self):
        from ccgram.handlers.msg_telegram import notify_loop_detected

        bot = AsyncMock(spec=Bot)
        router = _mock_router()

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_loop_detected(bot, "ccgram:@0", "ccgram:@5")

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        assert "loop" in text.lower()
        reply_markup = kwargs.get("reply_markup")
        assert reply_markup is not None
        buttons = reply_markup.inline_keyboard[0]
        button_texts = [b.text for b in buttons]
        assert any("Pause" in t for t in button_texts)
        assert any("Allow" in t for t in button_texts)

    @pytest.mark.asyncio
    async def test_keyboard_has_correct_callback_data(self):
        from ccgram.handlers.msg_telegram import (
            CB_MSG_LOOP_ALLOW,
            CB_MSG_LOOP_PAUSE,
            notify_loop_detected,
        )

        bot = AsyncMock(spec=Bot)
        router = _mock_router()

        with (
            patch("ccgram.handlers.msg_telegram.thread_router", router),
            patch(
                "ccgram.handlers.msg_telegram.rate_limit_send_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_send.return_value = MagicMock()
            await notify_loop_detected(bot, "ccgram:@0", "ccgram:@5")

        _, kwargs = mock_send.call_args
        buttons = kwargs["reply_markup"].inline_keyboard[0]
        cb_data = [b.callback_data for b in buttons]
        assert any(d.startswith(CB_MSG_LOOP_PAUSE) for d in cb_data)
        assert any(d.startswith(CB_MSG_LOOP_ALLOW) for d in cb_data)
