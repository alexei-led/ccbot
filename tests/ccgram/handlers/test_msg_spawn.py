import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.msg_spawn import (
    CB_SPAWN_APPROVE,
    CB_SPAWN_DENY,
    handle_spawn_approval,
    handle_spawn_denial,
)
from ccgram.spawn_request import (
    _pending_requests,
    check_max_windows,
    check_spawn_rate,
    clear_spawn_state,
    create_spawn_request,
    record_spawn,
    reset_spawn_state,
)


@pytest.fixture(autouse=True)
def _clean_state(tmp_path: Path):
    with patch("ccgram.spawn_request.spawns_dir", return_value=tmp_path / "spawns"):
        reset_spawn_state()
        yield
        reset_spawn_state()


class TestSpawnRequestCreation:
    def test_create_basic_request(self, tmp_path: Path):
        cwd = str(tmp_path)
        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=cwd,
            prompt="review auth module",
        )
        assert req.requester_window == "ccgram:@0"
        assert req.provider == "claude"
        assert req.cwd == cwd
        assert req.prompt == "review auth module"
        assert req.context_file is None
        assert req.auto is False
        assert req.id in _pending_requests

    def test_create_request_with_context_file(self, tmp_path: Path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("some context")
        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="review",
            context_file=str(ctx_file),
        )
        assert req.context_file == str(ctx_file)

    def test_create_request_auto_mode(self, tmp_path: Path):
        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
            auto=True,
        )
        assert req.auto is True

    def test_request_has_unique_id(self, tmp_path: Path):
        cwd = str(tmp_path)
        r1 = create_spawn_request(
            requester_window="ccgram:@0", provider="claude", cwd=cwd, prompt="a"
        )
        r2 = create_spawn_request(
            requester_window="ccgram:@0", provider="claude", cwd=cwd, prompt="b"
        )
        assert r1.id != r2.id

    def test_validate_cwd_must_exist(self, tmp_path: Path):
        bad_path = str(tmp_path / "nonexistent")
        with pytest.raises(ValueError, match="does not exist"):
            create_spawn_request(
                requester_window="ccgram:@0",
                provider="claude",
                cwd=bad_path,
                prompt="test",
            )


class TestMaxWindowsCheck:
    def test_under_limit(self):
        window_states = {f"@{i}": MagicMock() for i in range(5)}
        assert check_max_windows(window_states, max_windows=10)

    def test_at_limit(self):
        window_states = {f"@{i}": MagicMock() for i in range(10)}
        assert not check_max_windows(window_states, max_windows=10)

    def test_over_limit(self):
        window_states = {f"@{i}": MagicMock() for i in range(15)}
        assert not check_max_windows(window_states, max_windows=10)

    def test_zero_windows(self):
        assert check_max_windows({}, max_windows=10)


class TestSpawnRateLimiting:
    def test_first_spawn_allowed(self):
        assert check_spawn_rate("ccgram:@0", max_rate=3)

    def test_under_rate_limit(self):
        record_spawn("ccgram:@0")
        record_spawn("ccgram:@0")
        assert check_spawn_rate("ccgram:@0", max_rate=3)

    def test_at_rate_limit(self):
        for _ in range(3):
            record_spawn("ccgram:@0")
        assert not check_spawn_rate("ccgram:@0", max_rate=3)

    def test_different_windows_independent(self):
        for _ in range(3):
            record_spawn("ccgram:@0")
        assert check_spawn_rate("ccgram:@5", max_rate=3)

    def test_old_spawns_expire(self):
        from ccgram.spawn_request import _save_spawn_log

        now = time.time()
        _save_spawn_log({"ccgram:@0": [now - 4000, now - 3700, now - 3500]})
        assert check_spawn_rate("ccgram:@0", max_rate=3)


class TestApprovalFlow:
    @pytest.fixture()
    def mock_bot(self):
        bot = AsyncMock()
        bot.create_forum_topic = AsyncMock()
        return bot

    @pytest.fixture()
    def spawn_request(self, tmp_path: Path):
        cwd = str(tmp_path)
        return create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=cwd,
            prompt="review auth",
        )

    async def test_approve_creates_window(self, mock_bot, spawn_request, tmp_path):
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ) as mock_topic,
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            result = await handle_spawn_approval(spawn_request.id, mock_bot)

        assert result is not None
        assert result.window_id == "@7"
        mock_tmux.create_window.assert_called_once()
        mock_topic.assert_called_once()

    async def test_approve_unknown_request_returns_none(self, mock_bot):
        result = await handle_spawn_approval("nonexistent-id", mock_bot)
        assert result is None

    async def test_approve_sets_provider(self, mock_bot, spawn_request, tmp_path):
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            await handle_spawn_approval(spawn_request.id, mock_bot)

        mock_sm.set_window_provider.assert_called_once_with(
            "@7", "claude", cwd=str(tmp_path)
        )

    async def test_approve_window_creation_failure(self, mock_bot, spawn_request):
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(False, "tmux error", "", ""))

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            result = await handle_spawn_approval(spawn_request.id, mock_bot)

        assert result is None
        assert spawn_request.id not in _pending_requests

    async def test_deny_removes_request(self, spawn_request):
        req_id = spawn_request.id
        assert req_id in _pending_requests
        handle_spawn_denial(req_id)
        assert req_id not in _pending_requests

    async def test_deny_unknown_request_is_noop(self):
        handle_spawn_denial("nonexistent-id")


class TestAutoMode:
    async def test_auto_bypasses_approval(self, tmp_path):
        mock_bot = AsyncMock()
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test auto",
            auto=True,
        )

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            result = await handle_spawn_approval(req.id, mock_bot)

        assert result is not None


class TestSpawnTimeout:
    def test_request_expires_after_timeout(self, tmp_path: Path):
        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
        )
        req.created_at = time.monotonic() - 400
        assert req.is_expired(timeout=300)

    def test_request_not_expired_within_timeout(self, tmp_path: Path):
        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
        )
        assert not req.is_expired(timeout=300)


class TestContextBootstrap:
    async def test_context_file_sent_as_prompt(self, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("bootstrap context here")

        mock_bot = AsyncMock()
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="use this context",
            context_file=str(ctx_file),
        )

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            result = await handle_spawn_approval(req.id, mock_bot)

        assert result is not None
        mock_tmux.send_keys.assert_called()
        sent_text = mock_tmux.send_keys.call_args[0][1]
        assert "context.md" in sent_text
        assert "use this context" in sent_text


class TestCallbackConstants:
    def test_approve_prefix(self):
        assert CB_SPAWN_APPROVE == "sp:ok:"

    def test_deny_prefix(self):
        assert CB_SPAWN_DENY == "sp:no:"


class TestClearSpawnState:
    def test_clear_removes_requests_for_window(self, tmp_path: Path):
        cwd = str(tmp_path)
        create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=cwd,
            prompt="a",
        )
        create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=cwd,
            prompt="b",
        )
        create_spawn_request(
            requester_window="ccgram:@5",
            provider="claude",
            cwd=cwd,
            prompt="c",
        )
        clear_spawn_state("ccgram:@0")
        remaining = [
            r for r in _pending_requests.values() if r.requester_window == "ccgram:@0"
        ]
        assert len(remaining) == 0
        assert any(
            r.requester_window == "ccgram:@5" for r in _pending_requests.values()
        )


class TestSkillInstallOnSpawn:
    async def test_claude_spawn_installs_skill(self, tmp_path):
        mock_bot = AsyncMock()
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
        )

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="claude",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            await handle_spawn_approval(req.id, mock_bot)

        skill_path = tmp_path / ".claude" / "skills" / "ccgram-messaging" / "SKILL.md"
        assert skill_path.exists()

    async def test_non_claude_spawn_skips_skill(self, tmp_path):
        mock_bot = AsyncMock()
        mock_tmux = AsyncMock()
        mock_tmux.create_window = AsyncMock(return_value=(True, "ok", "project", "@7"))

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="codex",
            cwd=str(tmp_path),
            prompt="test",
        )

        with (
            patch("ccgram.handlers.msg_spawn.tmux_manager", mock_tmux),
            patch("ccgram.handlers.msg_spawn.session_manager") as mock_sm,
            patch("ccgram.handlers.msg_spawn.window_query") as mock_wq,
            patch(
                "ccgram.handlers.msg_spawn.resolve_launch_command",
                return_value="codex",
            ),
            patch(
                "ccgram.handlers.msg_spawn._create_topic_for_spawn",
                new_callable=AsyncMock,
            ),
        ):
            mock_sm.window_states = {}
            mock_wq.window_count.return_value = 0
            mock_sm.get_window_state.return_value = MagicMock(cwd="", provider_name="")
            await handle_spawn_approval(req.id, mock_bot)

        skill_path = tmp_path / ".claude" / "skills" / "ccgram-messaging" / "SKILL.md"
        assert not skill_path.exists()


class TestAccessorAPI:
    def test_get_pending_returns_request(self, tmp_path: Path):
        from ccgram.spawn_request import get_pending

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
        )
        result = get_pending(req.id)
        assert result is req

    def test_get_pending_missing_returns_none(self):
        from ccgram.spawn_request import get_pending

        assert get_pending("nonexistent") is None

    def test_pop_pending_removes(self, tmp_path: Path):
        from ccgram.spawn_request import pop_pending

        req = create_spawn_request(
            requester_window="ccgram:@0",
            provider="claude",
            cwd=str(tmp_path),
            prompt="test",
        )
        result = pop_pending(req.id)
        assert result is req
        assert req.id not in _pending_requests

    def test_pop_pending_missing_returns_none(self):
        from ccgram.spawn_request import pop_pending

        assert pop_pending("nonexistent") is None

    def test_iter_pending_yields_all(self, tmp_path: Path):
        from ccgram.spawn_request import iter_pending

        cwd = str(tmp_path)
        r1 = create_spawn_request(
            requester_window="ccgram:@0", provider="claude", cwd=cwd, prompt="a"
        )
        r2 = create_spawn_request(
            requester_window="ccgram:@0", provider="claude", cwd=cwd, prompt="b"
        )
        items = dict(iter_pending())
        assert items[r1.id] is r1
        assert items[r2.id] is r2

    def test_register_pending_stores(self):
        from ccgram.spawn_request import SpawnRequest, get_pending, register_pending

        req = SpawnRequest(
            id="test-123",
            requester_window="ccgram:@0",
            provider="claude",
            cwd="/tmp",
            prompt="test",
        )
        register_pending(req)
        assert get_pending("test-123") is req
