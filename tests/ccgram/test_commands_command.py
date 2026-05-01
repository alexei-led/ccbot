"""Tests for /commands handler in handlers/commands/__init__.py."""

from typing import TYPE_CHECKING, cast
from types import SimpleNamespace

if TYPE_CHECKING:
    from ccgram.providers import AgentProvider
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.commands import commands_command
from ccgram.cc_commands import CCCommand


_CO = "ccgram.handlers.commands"


def _make_update(
    *,
    user_id: int = 100,
    thread_id: int = 42,
) -> MagicMock:
    update = MagicMock()
    update.effective_user = MagicMock(id=user_id)
    msg = AsyncMock()
    msg.message_thread_id = thread_id
    msg.chat.type = "supergroup"
    msg.chat.id = -100999
    msg.chat.is_forum = True
    msg.is_topic_message = True
    update.message = msg
    return update


@pytest.fixture(autouse=True)
def _allow_user():
    with patch(f"{_CO}.config.is_user_allowed", return_value=True):
        yield


class TestCommandsCommand:
    async def test_unauthorized_user_returns_early(self) -> None:
        with (
            patch(f"{_CO}.config.is_user_allowed", return_value=False),
            patch(f"{_CO}.thread_router") as mock_tr,
        ):
            await commands_command(_make_update(), MagicMock())

        mock_tr.resolve_window_for_thread.assert_not_called()

    async def test_no_message_returns_early(self) -> None:
        update = _make_update()
        update.message = None
        with patch(f"{_CO}.thread_router") as mock_tr:
            await commands_command(update, MagicMock())
        mock_tr.resolve_window_for_thread.assert_not_called()

    async def test_unbound_topic_reports_error(self) -> None:
        update = _make_update()
        with (
            patch(f"{_CO}.thread_router") as mock_tr,
            patch(f"{_CO}.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_tr.resolve_window_for_thread.return_value = None
            await commands_command(update, MagicMock())

        mock_reply.assert_called_once()
        assert "No session bound" in mock_reply.call_args.args[1]

    async def test_no_discoverable_commands_reports_provider(self) -> None:
        update = _make_update()
        provider = cast(
            "AgentProvider", SimpleNamespace(capabilities=SimpleNamespace(name="codex"))
        )
        with (
            patch(f"{_CO}.thread_router") as mock_tr,
            patch(f"{_CO}.get_provider_for_window", return_value=provider),
            patch(f"{_CO}.sync_scoped_provider_menu", new_callable=AsyncMock),
            patch(f"{_CO}.discover_provider_commands", return_value=[]),
            patch(f"{_CO}.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_tr.resolve_window_for_thread.return_value = "@1"
            await commands_command(update, MagicMock())

        mock_reply.assert_called_once()
        text = mock_reply.call_args.args[1]
        assert "Provider: `codex`" in text
        assert "No discoverable commands" in text

    async def test_lists_provider_commands_with_original_mapping(self) -> None:
        update = _make_update()
        provider = cast(
            "AgentProvider", SimpleNamespace(capabilities=SimpleNamespace(name="codex"))
        )
        discovered = [
            CCCommand(
                name="spec:work",
                telegram_name="spec_work",
                description="↗ work",
                source="command",
            ),
            CCCommand(
                name="/status",
                telegram_name="status",
                description="↗ status",
                source="builtin",
            ),
            CCCommand(
                name="ignored",
                telegram_name="",
                description="↗ ignored",
                source="command",
            ),
        ]
        with (
            patch(f"{_CO}.thread_router") as mock_tr,
            patch(f"{_CO}.get_provider_for_window", return_value=provider),
            patch(
                f"{_CO}.sync_scoped_provider_menu", new_callable=AsyncMock
            ) as mock_sync,
            patch(f"{_CO}.discover_provider_commands", return_value=discovered),
            patch(f"{_CO}.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_tr.resolve_window_for_thread.return_value = "@1"
            await commands_command(update, MagicMock())

        mock_sync.assert_called_once_with(update.message, 100, provider)
        mock_reply.assert_called_once()
        text = mock_reply.call_args.args[1]
        assert "Provider: `codex`" in text
        assert "`/spec_work`" in text and "`/spec:work`" in text
        assert "`/status`" in text
        assert "ignored" not in text
