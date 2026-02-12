"""Tests for forward_command_handler CC command resolution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccbot.bot import forward_command_handler


def _make_update(
    *,
    user_id: int = 100,
    thread_id: int = 42,
    text: str = "/clear",
) -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock(id=user_id)
    msg = AsyncMock()
    msg.text = text
    msg.message_thread_id = thread_id
    msg.chat.type = "supergroup"
    msg.chat.id = -100999
    msg.chat.is_forum = True
    msg.is_topic_message = True
    update.message = msg
    update.callback_query = None
    return update


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {}
    return ctx


@pytest.fixture(autouse=True)
def _allow_user():
    with patch("ccbot.bot.is_user_allowed", return_value=True):
        yield


class TestForwardCommandResolution:
    """Verify that sanitized Telegram command names are resolved to original CC names."""

    @pytest.fixture(autouse=True)
    def _setup_mocks(self):
        self.mock_sm = MagicMock()
        self.mock_sm.resolve_window_for_thread.return_value = "@1"
        self.mock_sm.get_display_name.return_value = "project"
        self.mock_sm.send_to_window = AsyncMock(return_value=(True, ""))

        self.mock_tm = MagicMock()
        self.mock_tm.find_window_by_id = AsyncMock(
            return_value=MagicMock(window_id="@1")
        )

        with (
            patch("ccbot.bot.session_manager", self.mock_sm),
            patch("ccbot.bot.tmux_manager", self.mock_tm),
        ):
            yield

    async def test_builtin_forwarded_as_is(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/clear")

    async def test_builtin_with_args(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="compact"):
            update = _make_update(text="/compact focus on auth")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with(
            "@1", "/compact focus on auth"
        )

    async def test_skill_name_resolved(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="committing-code"):
            update = _make_update(text="/committing_code")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/committing-code")

    async def test_custom_command_resolved(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="spec:work"):
            update = _make_update(text="/spec_work")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/spec:work")

    async def test_custom_command_with_args(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="spec:new"):
            update = _make_update(text="/spec_new task auth")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/spec:new task auth")

    async def test_unknown_command_forwarded_as_is(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value=None):
            update = _make_update(text="/unknown_thing")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/unknown_thing")

    async def test_botname_mention_stripped(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear@mybot")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/clear")

    async def test_botname_mention_stripped_with_args(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="compact"):
            update = _make_update(text="/compact@mybot some args")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_called_once_with("@1", "/compact some args")

    async def test_confirmation_message_shows_resolved_name(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="committing-code"):
            update = _make_update(text="/committing_code")
            await forward_command_handler(update, _make_context())

        reply_text = update.message.reply_text.call_args[0][0]
        # safe_reply escapes MarkdownV2 chars (- -> \-), so check unescaped
        assert "committing" in reply_text and "code" in reply_text

    async def test_clear_clears_session(self) -> None:
        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        self.mock_sm.clear_window_session.assert_called_once_with("@1")

    async def test_no_session_bound(self) -> None:
        self.mock_sm.resolve_window_for_thread.return_value = None

        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_not_called()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "No session" in reply_text

    async def test_window_gone(self) -> None:
        self.mock_tm.find_window_by_id = AsyncMock(return_value=None)

        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_not_called()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "no longer exists" in reply_text

    async def test_send_failure(self) -> None:
        self.mock_sm.send_to_window = AsyncMock(return_value=(False, "Connection lost"))

        with patch("ccbot.bot.get_cc_name", return_value="clear"):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Connection lost" in reply_text

    async def test_unauthorized_user(self) -> None:
        with (
            patch("ccbot.bot.is_user_allowed", return_value=False),
            patch("ccbot.bot.get_cc_name") as mock_cc,
        ):
            update = _make_update(text="/clear")
            await forward_command_handler(update, _make_context())

        mock_cc.assert_not_called()
        self.mock_sm.send_to_window.assert_not_called()

    async def test_no_message(self) -> None:
        update = _make_update(text="/clear")
        update.message = None

        await forward_command_handler(update, _make_context())

        self.mock_sm.send_to_window.assert_not_called()
