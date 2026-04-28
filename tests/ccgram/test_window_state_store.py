"""Tests for WindowStateStore — pane management, serialization, helpers."""

from __future__ import annotations

import pytest

from ccgram.window_state_store import (
    DEFAULT_PANE_STATE,
    PaneInfo,
    WindowState,
    WindowStateStore,
)


@pytest.fixture
def store() -> WindowStateStore:
    s = WindowStateStore()
    save_calls: list[int] = []
    s._schedule_save = lambda: save_calls.append(1)
    s._save_calls = save_calls  # type: ignore[attr-defined]
    return s


class TestPaneInfoSerialization:
    def test_round_trip_full(self) -> None:
        pane = PaneInfo(
            pane_id="%5",
            name="api-gateway",
            provider="claude",
            last_active_ts=1700000000.5,
            state="blocked",
            subscribed=True,
        )
        loaded = PaneInfo.from_dict(pane.to_dict())
        assert loaded == pane

    def test_round_trip_defaults_omits_optional_keys(self) -> None:
        pane = PaneInfo(pane_id="%6")
        d = pane.to_dict()
        assert d == {"pane_id": "%6"}
        loaded = PaneInfo.from_dict(d)
        assert loaded == pane

    def test_invalid_state_falls_back_to_default(self) -> None:
        pane = PaneInfo.from_dict({"pane_id": "%7", "state": "garbage"})
        assert pane.state == DEFAULT_PANE_STATE

    def test_pane_id_filled_from_dict_key_when_missing(self) -> None:
        pane = PaneInfo.from_dict({"name": "build"})
        assert pane.pane_id == ""

    def test_last_active_ts_coerces_to_float(self) -> None:
        pane = PaneInfo.from_dict({"pane_id": "%9", "last_active_ts": 0})
        assert pane.last_active_ts == 0.0


class TestWindowStatePanes:
    def test_default_empty_dict(self) -> None:
        ws = WindowState()
        assert ws.panes == {}

    def test_to_dict_omits_panes_when_empty(self) -> None:
        ws = WindowState(cwd="/tmp/x")
        assert "panes" not in ws.to_dict()

    def test_to_dict_includes_panes_when_present(self) -> None:
        ws = WindowState(cwd="/tmp/x")
        ws.panes["%5"] = PaneInfo(pane_id="%5", state="active", subscribed=True)
        ws.panes["%6"] = PaneInfo(pane_id="%6")
        d = ws.to_dict()
        assert "panes" in d
        assert set(d["panes"].keys()) == {"%5", "%6"}
        assert d["panes"]["%5"]["state"] == "active"
        assert d["panes"]["%6"] == {"pane_id": "%6"}

    def test_from_dict_missing_panes_defaults_to_empty(self) -> None:
        ws = WindowState.from_dict({"session_id": "abc", "cwd": "/p"})
        assert ws.panes == {}

    def test_from_dict_round_trip(self) -> None:
        original = WindowState(
            session_id="sid",
            cwd="/p",
            window_name="proj",
            panes={
                "%5": PaneInfo(pane_id="%5", name="api", state="blocked"),
                "%6": PaneInfo(pane_id="%6", subscribed=True),
            },
        )
        loaded = WindowState.from_dict(original.to_dict())
        assert loaded == original

    def test_from_dict_skips_non_dict_pane_entries(self) -> None:
        ws = WindowState.from_dict(
            {
                "panes": {"%5": "garbage", "%6": {"pane_id": "%6"}},
            }
        )
        assert "%5" not in ws.panes
        assert ws.panes["%6"].pane_id == "%6"


class TestStoreCRUD:
    def test_get_pane_returns_none_for_missing_window(
        self, store: WindowStateStore
    ) -> None:
        assert store.get_pane("@1", "%5") is None

    def test_get_pane_returns_none_for_missing_pane(
        self, store: WindowStateStore
    ) -> None:
        store.get_window_state("@1")
        assert store.get_pane("@1", "%5") is None

    def test_upsert_pane_creates_entry(self, store: WindowStateStore) -> None:
        pane = store.upsert_pane("@1", "%5", provider="claude", state="active")
        assert pane.pane_id == "%5"
        assert pane.provider == "claude"
        assert pane.state == "active"
        assert store.get_pane("@1", "%5") is pane

    def test_upsert_pane_updates_only_provided_fields(
        self, store: WindowStateStore
    ) -> None:
        store.upsert_pane(
            "@1",
            "%5",
            name="orig",
            provider="claude",
            last_active_ts=10.0,
            state="active",
            subscribed=True,
        )
        store.upsert_pane("@1", "%5", state="idle")
        pane = store.get_pane("@1", "%5")
        assert pane is not None
        assert pane.name == "orig"
        assert pane.provider == "claude"
        assert pane.last_active_ts == 10.0
        assert pane.state == "idle"
        assert pane.subscribed is True

    def test_upsert_pane_clears_name_when_explicitly_none(
        self, store: WindowStateStore
    ) -> None:
        store.upsert_pane("@1", "%5", name="api")
        store.upsert_pane("@1", "%5", name=None)
        pane = store.get_pane("@1", "%5")
        assert pane is not None and pane.name is None

    def test_upsert_pane_rejects_invalid_state(self, store: WindowStateStore) -> None:
        with pytest.raises(ValueError):
            store.upsert_pane("@1", "%5", state="garbage")  # type: ignore[arg-type]

    def test_upsert_pane_schedules_save(self, store: WindowStateStore) -> None:
        store._save_calls.clear()  # type: ignore[attr-defined]
        store.upsert_pane("@1", "%5", state="active")
        assert len(store._save_calls) == 1  # type: ignore[attr-defined]

    def test_remove_pane_removes_entry(self, store: WindowStateStore) -> None:
        store.upsert_pane("@1", "%5")
        assert store.remove_pane("@1", "%5") is True
        assert store.get_pane("@1", "%5") is None

    def test_remove_pane_returns_false_when_missing(
        self, store: WindowStateStore
    ) -> None:
        assert store.remove_pane("@1", "%5") is False
        store.upsert_pane("@1", "%5")
        assert store.remove_pane("@1", "%99") is False

    def test_store_to_dict_round_trip_preserves_panes(
        self, store: WindowStateStore
    ) -> None:
        store.upsert_pane(
            "@1",
            "%5",
            name="api",
            provider="claude",
            state="blocked",
            subscribed=True,
        )
        store.upsert_pane("@1", "%6", state="idle")
        snapshot = store.to_dict()

        new_store = WindowStateStore()
        new_store.from_dict(snapshot)
        assert "@1" in new_store.window_states
        panes = new_store.window_states["@1"].panes
        assert panes["%5"].name == "api"
        assert panes["%5"].subscribed is True
        assert panes["%5"].state == "blocked"
        assert panes["%6"].state == "idle"

    def test_legacy_state_without_panes_loads_cleanly(
        self, store: WindowStateStore
    ) -> None:
        legacy = {
            "@1": {
                "session_id": "s",
                "cwd": "/p",
                "window_name": "proj",
            }
        }
        store.from_dict(legacy)
        assert store.window_states["@1"].panes == {}


class TestPaneLifecycleNotify:
    def test_window_state_default_is_none(self) -> None:
        ws = WindowState()
        assert ws.pane_lifecycle_notify is None

    def test_to_dict_omits_when_none(self) -> None:
        ws = WindowState(cwd="/p")
        assert "pane_lifecycle_notify" not in ws.to_dict()

    def test_to_dict_includes_when_set(self) -> None:
        ws = WindowState(cwd="/p", pane_lifecycle_notify=True)
        d = ws.to_dict()
        assert d["pane_lifecycle_notify"] is True

    def test_to_dict_includes_when_explicitly_false(self) -> None:
        ws = WindowState(cwd="/p", pane_lifecycle_notify=False)
        d = ws.to_dict()
        assert d["pane_lifecycle_notify"] is False

    def test_from_dict_round_trip(self) -> None:
        original = WindowState(cwd="/p", pane_lifecycle_notify=True)
        loaded = WindowState.from_dict(original.to_dict())
        assert loaded.pane_lifecycle_notify is True

    def test_from_dict_missing_field_defaults_to_none(self) -> None:
        ws = WindowState.from_dict({"session_id": "s", "cwd": "/p"})
        assert ws.pane_lifecycle_notify is None

    def test_get_returns_default_when_unknown_window(
        self, store: WindowStateStore
    ) -> None:
        assert store.get_pane_lifecycle_notify("@missing", default=False) is False
        assert store.get_pane_lifecycle_notify("@missing", default=True) is True

    def test_get_returns_default_when_override_unset(
        self, store: WindowStateStore
    ) -> None:
        store.get_window_state("@1")
        assert store.get_pane_lifecycle_notify("@1", default=False) is False
        assert store.get_pane_lifecycle_notify("@1", default=True) is True

    def test_get_returns_override_when_set(self, store: WindowStateStore) -> None:
        store.set_pane_lifecycle_notify("@1", True)
        assert store.get_pane_lifecycle_notify("@1", default=False) is True
        store.set_pane_lifecycle_notify("@1", False)
        assert store.get_pane_lifecycle_notify("@1", default=True) is False

    def test_set_schedules_save(self, store: WindowStateStore) -> None:
        save_calls = store._save_calls  # type: ignore[attr-defined]
        save_calls.clear()
        store.set_pane_lifecycle_notify("@1", True)
        assert len(save_calls) == 1

    def test_set_to_same_value_does_not_save(self, store: WindowStateStore) -> None:
        store.set_pane_lifecycle_notify("@1", True)
        save_calls = store._save_calls  # type: ignore[attr-defined]
        save_calls.clear()
        store.set_pane_lifecycle_notify("@1", True)
        assert save_calls == []

    def test_set_to_none_clears_override(self, store: WindowStateStore) -> None:
        store.set_pane_lifecycle_notify("@1", True)
        store.set_pane_lifecycle_notify("@1", None)
        assert store.get_pane_lifecycle_notify("@1", default=False) is False
        assert store.get_pane_lifecycle_notify("@1", default=True) is True
