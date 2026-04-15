"""Tests for idle_tracker — per-session activity timestamps."""

import time

from ccgram.idle_tracker import IdleTracker


def test_get_last_activity_returns_none_for_unknown_session() -> None:
    tracker = IdleTracker()
    assert tracker.get_last_activity("unknown") is None


def test_record_activity_defaults_to_now() -> None:
    tracker = IdleTracker()
    before = time.monotonic()
    tracker.record_activity("s1")
    after = time.monotonic()
    ts = tracker.get_last_activity("s1")
    assert ts is not None
    assert before <= ts <= after


def test_record_activity_with_explicit_timestamp() -> None:
    tracker = IdleTracker()
    tracker.record_activity("s1", ts=12345.0)
    assert tracker.get_last_activity("s1") == 12345.0


def test_record_activity_overwrites_previous() -> None:
    tracker = IdleTracker()
    tracker.record_activity("s1", ts=100.0)
    tracker.record_activity("s1", ts=200.0)
    assert tracker.get_last_activity("s1") == 200.0


def test_clear_session_removes_tracking() -> None:
    tracker = IdleTracker()
    tracker.record_activity("s1", ts=100.0)
    tracker.clear_session("s1")
    assert tracker.get_last_activity("s1") is None


def test_clear_session_noop_for_unknown() -> None:
    tracker = IdleTracker()
    tracker.clear_session("nonexistent")
    assert tracker.get_last_activity("nonexistent") is None


def test_multiple_sessions_are_independent() -> None:
    tracker = IdleTracker()
    tracker.record_activity("a", ts=1.0)
    tracker.record_activity("b", ts=2.0)
    tracker.clear_session("a")
    assert tracker.get_last_activity("a") is None
    assert tracker.get_last_activity("b") == 2.0
