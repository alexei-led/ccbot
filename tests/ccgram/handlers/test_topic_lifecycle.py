import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Bot
from telegram.error import BadRequest

from ccgram.handlers.topic_lifecycle import (
    check_autoclose_timers,
    check_unbound_window_ttl,
    probe_topic_existence,
    prune_stale_state,
)
from ccgram.handlers.polling_strategies import (
    lifecycle_strategy,
    terminal_poll_state,
)


@pytest.fixture(autouse=True)
def _clean_strategy_state():
    terminal_poll_state._states.clear()
    lifecycle_strategy._states.clear()
    lifecycle_strategy._dead_notified.clear()
    yield
    terminal_poll_state._states.clear()
    lifecycle_strategy._states.clear()
    lifecycle_strategy._dead_notified.clear()


class TestCheckAutocloseTimers:
    async def test_no_topics_is_noop(self):
        bot = AsyncMock(spec=Bot)
        await check_autoclose_timers(bot)
        bot.delete_forum_topic.assert_not_called()

    async def test_expired_done_topic_gets_closed(self):
        bot = AsyncMock(spec=Bot)
        bot.delete_forum_topic = AsyncMock()
        user_id, thread_id = 1, 100
        lifecycle_strategy.start_autoclose_timer(
            user_id, thread_id, "done", time.monotonic() - 99999
        )
        with (
            patch("ccgram.handlers.topic_lifecycle.config") as mock_config,
            patch("ccgram.handlers.topic_lifecycle.thread_router") as mock_router,
            patch(
                "ccgram.handlers.topic_lifecycle.clear_topic_state",
                new_callable=AsyncMock,
            ),
        ):
            mock_config.autoclose_done_minutes = 1
            mock_router.resolve_chat_id.return_value = 42
            mock_router.get_window_for_thread.return_value = "@0"
            await check_autoclose_timers(bot)
        bot.delete_forum_topic.assert_called_once()

    async def test_not_yet_expired_topic_stays(self):
        bot = AsyncMock(spec=Bot)
        user_id, thread_id = 1, 100
        lifecycle_strategy.start_autoclose_timer(
            user_id, thread_id, "done", time.monotonic()
        )
        with patch("ccgram.handlers.topic_lifecycle.config") as mock_config:
            mock_config.autoclose_done_minutes = 60
            await check_autoclose_timers(bot)
        bot.delete_forum_topic.assert_not_called()


class TestCheckUnboundWindowTtl:
    async def test_no_timeout_is_noop(self):
        with patch("ccgram.handlers.topic_lifecycle.config") as mock_config:
            mock_config.autoclose_done_minutes = 0
            await check_unbound_window_ttl([])

    async def test_bound_window_timer_cleared(self):
        ws = terminal_poll_state.get_state("@0")
        ws.unbound_timer = time.monotonic() - 100
        mock_window = MagicMock(window_id="@0", window_name="test")
        with (
            patch("ccgram.handlers.topic_lifecycle.config") as mock_config,
            patch("ccgram.handlers.topic_lifecycle.thread_router") as mock_router,
        ):
            mock_config.autoclose_done_minutes = 1
            mock_router.iter_thread_bindings.return_value = [(1, 100, "@0")]
            await check_unbound_window_ttl([mock_window])
        assert ws.unbound_timer is None


class TestPruneStaleState:
    async def test_syncs_display_names(self):
        mock_window = MagicMock(window_id="@0", window_name="test")
        with patch("ccgram.handlers.topic_lifecycle.session_manager") as mock_sm:
            await prune_stale_state([mock_window])
            mock_sm.sync_display_names.assert_called_once_with([("@0", "test")])
            mock_sm.prune_stale_state.assert_called_once_with({"@0"})


class TestProbeTopicExistence:
    async def test_deleted_topic_unbinds(self):
        bot = AsyncMock(spec=Bot)
        bot.unpin_all_forum_topic_messages = AsyncMock(
            side_effect=BadRequest("Topic_id_invalid")
        )
        with (
            patch("ccgram.handlers.topic_lifecycle.thread_router") as mock_router,
            patch("ccgram.handlers.topic_lifecycle.tmux_manager") as mock_tmux,
            patch(
                "ccgram.handlers.topic_lifecycle.clear_topic_state",
                new_callable=AsyncMock,
            ),
        ):
            mock_router.iter_thread_bindings.return_value = [(1, 100, "@0")]
            mock_router.resolve_chat_id.return_value = 42
            mock_tmux.find_window_by_id = AsyncMock(
                return_value=MagicMock(window_id="@0")
            )
            mock_tmux.kill_window = AsyncMock()
            await probe_topic_existence(bot)
            mock_router.unbind_thread.assert_called_once_with(1, 100)

    async def test_suspended_probe_skipped(self):
        bot = AsyncMock(spec=Bot)
        ws = terminal_poll_state.get_state("@0")
        ws.probe_failures = 999
        with patch("ccgram.handlers.topic_lifecycle.thread_router") as mock_router:
            mock_router.iter_thread_bindings.return_value = [(1, 100, "@0")]
            await probe_topic_existence(bot)
        bot.unpin_all_forum_topic_messages.assert_not_called()
