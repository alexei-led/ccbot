"""Tests for session_map.py — focus on liveness-gated session_id overwrite.

Regression coverage for the window→session binding bug where nested
SessionStart events from Agent Teams teammates would clobber a still-live
parent session's binding. See `_existing_session_is_live` and the gate
inside `_sync_window_from_session_map`.
"""

import json
import logging
import os
import time

import pytest
import structlog

from ccgram.session_map import session_map_sync
from ccgram.thread_router import thread_router
from ccgram.window_state_store import WindowState, window_store


@pytest.fixture(autouse=True)
def _configure_structlog_for_caplog():
    """Route structlog through stdlib logging so pytest's caplog captures it."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    yield
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _wire_schedule_save():
    """Stub _schedule_save singletons so SessionMapSync can be tested in isolation.

    Production wiring is done by SessionManager.__init__; tests here exercise
    SessionMapSync directly, so no-op stubs on the relevant singletons are
    enough to keep the unwired-save guard quiet.
    """
    sms_orig = session_map_sync._schedule_save
    tr_orig = thread_router._schedule_save
    session_map_sync._schedule_save = lambda: None
    thread_router._schedule_save = lambda: None
    yield
    session_map_sync._schedule_save = sms_orig
    thread_router._schedule_save = tr_orig
    thread_router.reset()


def _write_session_map(path, entries: dict) -> None:
    path.write_text(json.dumps(entries))


def _set_mtime(path, age_seconds: float) -> None:
    """Set file mtime to (now - age_seconds)."""
    mtime = time.time() - age_seconds
    os.utime(path, (mtime, mtime))


class TestLivenessGatedOverwrite:
    """The key regression: a nested teammate must not clobber the parent."""

    async def test_skips_overwrite_when_existing_transcript_fresh(
        self,
        tmp_path,
        monkeypatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Parent's transcript modified within grace_sec → new sid is ignored."""
        # Parent transcript: present, modified seconds ago (fresh).
        parent_transcript = tmp_path / "parent.jsonl"
        parent_transcript.write_text('{"type": "assistant"}\n')
        _set_mtime(parent_transcript, age_seconds=2.0)

        # Pre-seed the window state as if the parent had registered first.
        window_store.window_states["@44"] = WindowState(
            session_id="parent-uuid",
            cwd="/tmp/parent-project",
            window_name="parent-window",
            transcript_path=str(parent_transcript),
            provider_name="claude",
        )

        # session_map.json now contains the teammate's entry under the same key.
        teammate_transcript = tmp_path / "teammate.jsonl"
        teammate_transcript.write_text('{"type": "assistant"}\n')
        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@44": {
                    "session_id": "teammate-uuid",
                    "cwd": "/tmp/teammate-project",
                    "window_name": "parent-window",
                    "transcript_path": str(teammate_transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        with caplog.at_level(logging.INFO, logger="ccgram.session_map"):
            await session_map_sync.load_session_map()

        # Binding is preserved: parent still owns the window.
        state = window_store.get_window_state("@44")
        assert state.session_id == "parent-uuid"
        assert state.cwd == "/tmp/parent-project"
        assert state.transcript_path == str(parent_transcript)

        # Skip log emitted, naming both sessions and the window_id.
        assert "Skip session_id overwrite" in caplog.text
        assert "@44" in caplog.text
        assert "parent-uuid" in caplog.text
        assert "teammate-uuid" in caplog.text

    async def test_overwrites_when_existing_transcript_stale(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Parent gone silent past grace_sec → new sid wins (lock auto-releases)."""
        parent_transcript = tmp_path / "parent.jsonl"
        parent_transcript.write_text('{"type": "assistant"}\n')
        # 120s old — well beyond default grace_sec=60.
        _set_mtime(parent_transcript, age_seconds=120.0)

        window_store.window_states["@44"] = WindowState(
            session_id="parent-uuid",
            cwd="/tmp/parent-project",
            window_name="parent-window",
            transcript_path=str(parent_transcript),
            provider_name="claude",
        )

        new_transcript = tmp_path / "new.jsonl"
        new_transcript.write_text('{"type": "assistant"}\n')
        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@44": {
                    "session_id": "new-uuid",
                    "cwd": "/tmp/new-project",
                    "window_name": "parent-window",
                    "transcript_path": str(new_transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        await session_map_sync.load_session_map()

        # Binding flipped: parent went silent, new session takes over.
        state = window_store.get_window_state("@44")
        assert state.session_id == "new-uuid"
        assert state.cwd == "/tmp/new-project"
        assert state.transcript_path == str(new_transcript)

    async def test_first_registration_unaffected(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Empty-state windows still register normally (gate only fires on conflict)."""
        transcript = tmp_path / "first.jsonl"
        transcript.write_text('{"type": "assistant"}\n')
        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@7": {
                    "session_id": "first-uuid",
                    "cwd": "/tmp/first",
                    "window_name": "first",
                    "transcript_path": str(transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        await session_map_sync.load_session_map()

        state = window_store.get_window_state("@7")
        assert state.session_id == "first-uuid"
        assert state.cwd == "/tmp/first"

    async def test_same_session_id_update_unaffected(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Same session_id refresh (e.g. cwd change) still applies even if fresh."""
        transcript = tmp_path / "same.jsonl"
        transcript.write_text('{"type": "assistant"}\n')
        _set_mtime(transcript, age_seconds=2.0)

        window_store.window_states["@9"] = WindowState(
            session_id="stable-uuid",
            cwd="/tmp/old-cwd",
            transcript_path=str(transcript),
            provider_name="claude",
        )

        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@9": {
                    "session_id": "stable-uuid",
                    "cwd": "/tmp/new-cwd",
                    "window_name": "win",
                    "transcript_path": str(transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        await session_map_sync.load_session_map()

        state = window_store.get_window_state("@9")
        assert state.session_id == "stable-uuid"
        # cwd update for the same session_id is allowed.
        assert state.cwd == "/tmp/new-cwd"

    async def test_grace_sec_env_override(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """CCGRAM_NESTED_SESSION_GRACE_SEC env var tunes the lock window."""
        # Parent transcript is 5s old. Default grace=60 would protect; setting
        # grace=1 should release.
        parent_transcript = tmp_path / "parent.jsonl"
        parent_transcript.write_text('{"type": "assistant"}\n')
        _set_mtime(parent_transcript, age_seconds=5.0)

        window_store.window_states["@44"] = WindowState(
            session_id="parent-uuid",
            cwd="/tmp/parent",
            transcript_path=str(parent_transcript),
            provider_name="claude",
        )

        new_transcript = tmp_path / "new.jsonl"
        new_transcript.write_text('{"type": "assistant"}\n')
        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@44": {
                    "session_id": "new-uuid",
                    "cwd": "/tmp/new",
                    "window_name": "win",
                    "transcript_path": str(new_transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setenv("CCGRAM_NESTED_SESSION_GRACE_SEC", "1.0")
        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        await session_map_sync.load_session_map()

        # Tighter grace window → existing 5s-old session counts as stale.
        state = window_store.get_window_state("@44")
        assert state.session_id == "new-uuid"

    async def test_missing_transcript_releases_lock(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """If the existing transcript path no longer exists, treat as stale."""
        # Reference a path that doesn't exist.
        window_store.window_states["@44"] = WindowState(
            session_id="parent-uuid",
            cwd="/tmp/parent",
            transcript_path=str(tmp_path / "vanished.jsonl"),
            provider_name="claude",
        )

        new_transcript = tmp_path / "new.jsonl"
        new_transcript.write_text('{"type": "assistant"}\n')
        session_map_file = tmp_path / "session_map.json"
        _write_session_map(
            session_map_file,
            {
                "ccgram:@44": {
                    "session_id": "new-uuid",
                    "cwd": "/tmp/new",
                    "window_name": "win",
                    "transcript_path": str(new_transcript),
                    "provider_name": "claude",
                }
            },
        )

        monkeypatch.setattr(
            "ccgram.session_map.config.session_map_file", session_map_file
        )
        monkeypatch.setattr("ccgram.session_map.config.tmux_session_name", "ccgram")

        await session_map_sync.load_session_map()

        state = window_store.get_window_state("@44")
        assert state.session_id == "new-uuid"
