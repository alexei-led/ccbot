"""Tests for status_snapshot — /status and /stats fallback for non-native providers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ccgram.handlers.commands.status_snapshot import (
    _maybe_send_status_snapshot,
    _status_snapshot_probe_offset,
)


_SS = "ccgram.handlers.commands.status_snapshot"


class TestStatusSnapshotProbeOffset:
    def test_returns_none_for_non_status_command(self) -> None:
        with patch(f"{_SS}.window_query") as mock_wq:
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=None, provider_name="codex"
            )
            assert _status_snapshot_probe_offset("@1", "/clear") is None

    def test_returns_none_when_provider_does_not_support_snapshot(self) -> None:
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window") as mock_get,
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=None, provider_name="claude"
            )
            mock_get.return_value = SimpleNamespace(
                capabilities=SimpleNamespace(supports_status_snapshot=False)
            )
            assert _status_snapshot_probe_offset("@1", "/status") is None

    def test_returns_offset_for_codex_status(self) -> None:
        mock_path = MagicMock(spec=Path)
        mock_path.stat.return_value.st_size = 4096
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window") as mock_get,
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=mock_path, provider_name="codex"
            )
            mock_get.return_value = SimpleNamespace(
                capabilities=SimpleNamespace(supports_status_snapshot=True)
            )
            assert _status_snapshot_probe_offset("@1", "/status") == 4096


class TestMaybeSendStatusSnapshot:
    async def test_skips_for_non_status_command(self) -> None:
        message = AsyncMock()
        with patch(f"{_SS}.window_query") as mock_wq:
            await _maybe_send_status_snapshot(message, "@1", "p", "/clear")
            mock_wq.view_window.assert_not_called()

    async def test_skips_when_provider_does_not_support_snapshot(self) -> None:
        message = AsyncMock()
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window") as mock_get,
            patch(f"{_SS}.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=None, provider_name="claude"
            )
            mock_get.return_value = SimpleNamespace(
                capabilities=SimpleNamespace(supports_status_snapshot=False)
            )
            await _maybe_send_status_snapshot(message, "@1", "p", "/status")
            mock_reply.assert_not_called()

    async def test_unavailable_when_no_transcript_path(self) -> None:
        message = AsyncMock()
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window") as mock_get,
            patch(f"{_SS}.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=None,
                provider_name="codex",
                session_id="s",
                cwd="/c",
            )
            mock_get.return_value = SimpleNamespace(
                capabilities=SimpleNamespace(supports_status_snapshot=True)
            )
            await _maybe_send_status_snapshot(message, "@1", "p", "/status")
            mock_reply.assert_called_once()
            assert "no transcript path" in mock_reply.call_args.args[1]

    async def test_emits_snapshot(self) -> None:
        message = AsyncMock()
        mock_path = MagicMock(spec=Path)
        mock_path.__str__ = MagicMock(return_value="/tmp/codex.jsonl")
        provider = SimpleNamespace(
            capabilities=SimpleNamespace(supports_status_snapshot=True),
            build_status_snapshot=MagicMock(return_value="snapshot body"),
            has_output_since=MagicMock(return_value=False),
        )
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window", return_value=provider),
            patch(f"{_SS}.safe_reply", new_callable=AsyncMock) as mock_reply,
            patch(f"{_SS}.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=mock_path,
                provider_name="codex",
                session_id="s",
                cwd="/c",
            )
            await _maybe_send_status_snapshot(
                message, "@1", "p", "/status", since_offset=0
            )
            mock_reply.assert_called_once_with(message, "snapshot body")

    async def test_skips_snapshot_when_native_output_exists(self) -> None:
        message = AsyncMock()
        mock_path = MagicMock(spec=Path)
        mock_path.__str__ = MagicMock(return_value="/tmp/codex.jsonl")
        provider = SimpleNamespace(
            capabilities=SimpleNamespace(supports_status_snapshot=True),
            build_status_snapshot=MagicMock(return_value="ignored"),
            has_output_since=MagicMock(return_value=True),
        )
        with (
            patch(f"{_SS}.window_query") as mock_wq,
            patch(f"{_SS}.get_provider_for_window", return_value=provider),
            patch(f"{_SS}.safe_reply", new_callable=AsyncMock) as mock_reply,
            patch(f"{_SS}.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_wq.view_window.return_value = SimpleNamespace(
                transcript_path=mock_path,
                provider_name="codex",
                session_id="s",
                cwd="/c",
            )
            await _maybe_send_status_snapshot(
                message, "@1", "p", "/status", since_offset=0
            )
            mock_reply.assert_not_called()
            provider.build_status_snapshot.assert_not_called()
