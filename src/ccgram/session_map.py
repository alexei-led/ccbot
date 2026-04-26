"""Session map I/O — reads and writes session_map.json.

Owns all logic for synchronising window states against the session_map.json
file written by the Claude Code hook. Extracted from SessionManager so that
session_map concerns live in one place without pulling in the full
SessionManager stack.

Key class: SessionMapSync (singleton instantiated as ``session_map_sync``).
Free functions: parse_session_map, parse_emdash_provider.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import time
import structlog
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles

from .config import config
from .state_persistence import unwired_save
from .utils import atomic_write_json
from .window_resolver import EMDASH_SESSION_PREFIX, is_foreign_window, is_window_id

logger = structlog.get_logger()

_LEGACY_SESSION_PREFIX = "ccbot:"
_DEFAULT_PRIMARY_SESSION_GRACE_SEC = 60.0


def _primary_session_grace_sec() -> float:
    raw = os.getenv("CCGRAM_NESTED_SESSION_GRACE_SEC")
    if raw is None:
        return _DEFAULT_PRIMARY_SESSION_GRACE_SEC
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "CCGRAM_NESTED_SESSION_GRACE_SEC must be a number, got %r; using default %.1f",
            raw,
            _DEFAULT_PRIMARY_SESSION_GRACE_SEC,
        )
        return _DEFAULT_PRIMARY_SESSION_GRACE_SEC


def _transcript_mtime(transcript_path: str) -> float | None:
    if not transcript_path:
        return None
    try:
        return Path(transcript_path).stat().st_mtime
    except OSError:
        return None


def _transcript_is_fresh(transcript_path: str, *, now: float | None = None) -> bool:
    mtime = _transcript_mtime(transcript_path)
    if mtime is None:
        return False
    reference = time.time() if now is None else now
    return reference - mtime < _primary_session_grace_sec()


def _prefer_existing_primary(
    window_id: str,
    incoming: dict[str, Any],
) -> dict[str, str] | None:
    from .window_state_store import window_store

    state = window_store.window_states.get(window_id)
    if not state or not state.session_id:
        return None

    incoming_sid = incoming.get("session_id", "")
    if not incoming_sid or incoming_sid == state.session_id:
        return None

    existing_mtime = _transcript_mtime(state.transcript_path)
    incoming_mtime = _transcript_mtime(incoming.get("transcript_path", ""))
    existing_is_fresh = _transcript_is_fresh(state.transcript_path)
    existing_is_newer = existing_mtime is not None and (
        incoming_mtime is None or existing_mtime >= incoming_mtime
    )
    if not existing_is_fresh and not existing_is_newer:
        return None

    logger.debug(
        "Preserving primary session for window_id %s: existing %s, incoming %s treated as nested",
        window_id,
        state.session_id,
        incoming_sid,
    )
    return {
        "session_id": state.session_id,
        "cwd": state.cwd,
        "window_name": incoming.get("window_name", "") or state.window_name,
        "transcript_path": state.transcript_path,
        "provider_name": incoming.get("provider_name", "") or state.provider_name,
    }


def effective_session_map_info(
    window_id: str,
    info: dict[str, Any],
) -> dict[str, str]:
    preferred = _prefer_existing_primary(window_id, info)
    if preferred is not None:
        return preferred
    return {
        "session_id": info.get("session_id", ""),
        "cwd": info.get("cwd", ""),
        "window_name": info.get("window_name", ""),
        "transcript_path": info.get("transcript_path", ""),
        "provider_name": info.get("provider_name", ""),
    }


def parse_session_map(raw: dict[str, Any], prefix: str) -> dict[str, dict[str, str]]:
    """Parse session_map.json entries matching a tmux session prefix.

    Also matches legacy "ccbot:" prefix keys when the current prefix is "ccgram:".
    Returns {window_name: {"session_id": ..., "cwd": ...}} for matching entries.
    """
    result: dict[str, dict[str, str]] = {}
    legacy_prefix = _LEGACY_SESSION_PREFIX if prefix.startswith("ccgram:") else ""
    for key, info in raw.items():
        if key.startswith(prefix):
            window_name = key[len(prefix) :]
        elif legacy_prefix and key.startswith(legacy_prefix):
            window_name = key[len(legacy_prefix) :]
        else:
            continue
        if not isinstance(info, dict):
            continue
        effective = effective_session_map_info(window_name, info)
        if effective["session_id"]:
            result[window_name] = effective
    return result


def parse_emdash_provider(session_name: str) -> str:
    """Extract provider name from emdash session name.

    Format: emdash-{provider}-main-{id} or emdash-{provider}-chat-{id}
    """
    for sep in ("-main-", "-chat-"):
        if sep in session_name:
            prefix = session_name.split(sep)[0]
            return prefix.removeprefix(EMDASH_SESSION_PREFIX)
    return ""


@dataclass
class SessionMapSync:
    """Session map I/O and window-state synchronisation.

    Reads and writes session_map.json, syncing window states from hook-written
    entries. Persistence of window_states is delegated: the ``_schedule_save``
    callback (set by SessionManager) triggers a debounced save after mutations.

    Depends on ``window_store`` and ``thread_router`` singletons for state access.
    """

    def __post_init__(self) -> None:
        self._schedule_save: Callable[[], None] = unwired_save("SessionMapSync")

    # ------------------------------------------------------------------
    # Public: async read/sync methods
    # ------------------------------------------------------------------

    async def load_session_map(self) -> None:
        """Read session_map.json and update window_states with new session associations.

        Keys in session_map are formatted as "tmux_session:window_id" (e.g. "ccgram:@12").
        Native entries (matching our tmux_session_name) and emdash entries (prefixed
        with "emdash-") are both processed. Emdash windows are marked as external.
        Also cleans up window_states entries not in current session_map.
        Updates window_display_names from the "window_name" field in values.
        """
        if not config.session_map_file.exists():
            return
        try:
            async with aiofiles.open(config.session_map_file, "r") as f:
                content = await f.read()
            session_map = json.loads(content)
        except (json.JSONDecodeError, OSError):  # fmt: skip
            return

        prefix = f"{config.tmux_session_name}:"
        valid_wids, old_format_sids, old_format_keys, changed = (
            self._process_session_map_entries(session_map, prefix)
        )
        changed |= self._remove_stale_window_states(valid_wids, old_format_sids)
        self._purge_old_format_keys(session_map, old_format_keys)

        if changed:
            self._schedule_save()

    def _process_session_map_entries(
        self,
        session_map: dict[str, Any],
        prefix: str,
    ) -> tuple[set[str], set[str], list[str], bool]:
        """Iterate session_map entries and sync window states.

        Returns (valid_wids, old_format_sids, old_format_keys, changed).
        """
        valid_wids: set[str] = set()
        old_format_sids: set[str] = set()
        old_format_keys: list[str] = []
        changed = False

        for key, info in session_map.items():
            if not isinstance(info, dict):
                continue
            if key.startswith(EMDASH_SESSION_PREFIX):
                valid_wids.add(key)
                if self._sync_emdash_entry(key, info):
                    changed = True
                continue
            if not key.startswith(prefix):
                continue
            window_id = key[len(prefix) :]
            if not is_window_id(window_id):
                sid = info.get("session_id", "")
                if sid:
                    old_format_sids.add(sid)
                old_format_keys.append(key)
                continue
            valid_wids.add(window_id)
            if self._sync_window_from_session_map(window_id, info):
                changed = True

        return valid_wids, old_format_sids, old_format_keys, changed

    def _sync_emdash_entry(self, key: str, info: dict[str, Any]) -> bool:
        """Sync one emdash session_map entry; infer provider if missing.

        Returns True if any state changed.
        """
        from .window_state_store import window_store

        changed = self._sync_window_from_session_map(key, info, mark_external=True)
        state = window_store.get_window_state(key)
        if not state.provider_name:
            detected = parse_emdash_provider(key.rsplit(":", 1)[0])
            if detected:
                state.provider_name = detected
                changed = True
        return changed

    def _remove_stale_window_states(
        self,
        valid_wids: set[str],
        old_format_sids: set[str],
    ) -> bool:
        """Remove window_states not in valid_wids, not bound, and not old-format.

        Returns True if any states were removed.
        """
        from .thread_router import thread_router
        from .window_state_store import window_store

        bound_wids = {
            wid
            for user_bindings in thread_router.thread_bindings.values()
            for wid in user_bindings.values()
            if wid
        }
        stale_wids = [
            w
            for w in window_store.iter_window_ids()
            if (
                w
                and w not in valid_wids
                and w not in bound_wids
                and window_store.get_session_id_for_window(w) not in old_format_sids
            )
        ]
        for wid in stale_wids:
            logger.info("Removing stale window_state: %s", wid)
            window_store.remove_window(wid)
        return bool(stale_wids)

    def _purge_old_format_keys(
        self,
        session_map: dict[str, Any],
        old_format_keys: list[str],
    ) -> None:
        """Remove old-format (window-name-keyed) entries from session_map.json."""
        if not old_format_keys:
            return
        for key in old_format_keys:
            logger.info("Removing old-format session_map key: %s", key)
            del session_map[key]
        atomic_write_json(config.session_map_file, session_map)

    async def wait_for_session_map_entry(
        self, window_id: str, timeout: float = 5.0, interval: float = 0.5
    ) -> bool:
        """Poll session_map.json until an entry for window_id appears.

        Returns True if the entry was found within timeout, False otherwise.
        """
        logger.debug(
            "Waiting for session_map entry: window_id=%s, timeout=%.1f",
            window_id,
            timeout,
        )
        key = f"{config.tmux_session_name}:{window_id}"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                if config.session_map_file.exists():
                    async with aiofiles.open(config.session_map_file, "r") as f:
                        content = await f.read()
                    session_map = json.loads(content)
                    info = session_map.get(key, {})
                    if info.get("session_id"):
                        logger.debug(
                            "session_map entry found for window_id %s", window_id
                        )
                        await self.load_session_map()
                        return True
            except (json.JSONDecodeError, OSError):  # fmt: skip
                pass
            await asyncio.sleep(interval)
        logger.warning(
            "Timed out waiting for session_map entry: window_id=%s", window_id
        )
        return False

    # ------------------------------------------------------------------
    # Public: sync read/write methods
    # ------------------------------------------------------------------

    def prune_session_map(self, live_window_ids: set[str]) -> None:
        """Remove session_map.json entries for windows that no longer exist.

        Reads session_map.json, drops entries whose window_id is not in
        live_window_ids, and writes back only if changes were made.
        Also removes corresponding window_states.
        """
        from .window_state_store import window_store

        if not config.session_map_file.exists():
            return
        try:
            raw = json.loads(config.session_map_file.read_text())
        except (json.JSONDecodeError, OSError):  # fmt: skip
            return

        prefix = f"{config.tmux_session_name}:"
        dead_entries: list[tuple[str, str]] = []  # (map_key, window_id)
        for key in raw:
            if not key.startswith(prefix):
                continue
            window_id = key[len(prefix) :]
            if is_window_id(window_id) and window_id not in live_window_ids:
                dead_entries.append((key, window_id))

        if not dead_entries:
            return

        changed_state = False
        for key, window_id in dead_entries:
            logger.info(
                "Pruning dead session_map entry: %s (window %s)", key, window_id
            )
            del raw[key]
            if window_store.has_window(window_id):
                window_store.remove_window(window_id)
                changed_state = True

        atomic_write_json(config.session_map_file, raw)
        if changed_state:
            self._schedule_save()

    def get_session_map_window_ids(self) -> set[str]:
        """Read session_map.json and return window IDs tracked by ccgram.

        Includes native windows (stripped to @id) and emdash windows
        (full qualified key like "emdash-claude-main-xxx:@0").
        """
        if not config.session_map_file.exists():
            return set()
        try:
            raw = json.loads(config.session_map_file.read_text())
        except (json.JSONDecodeError, OSError):  # fmt: skip
            return set()
        prefix = f"{config.tmux_session_name}:"
        result: set[str] = set()
        for key in raw:
            if key.startswith(prefix):
                wid = key[len(prefix) :]
                if is_window_id(wid):
                    result.add(wid)
            elif key.startswith(EMDASH_SESSION_PREFIX):
                result.add(key)
        return result

    def register_hookless_session(
        self,
        window_id: str,
        session_id: str,
        cwd: str,
        transcript_path: str,
        provider_name: str,
    ) -> None:
        """Register a session for a hookless provider (Codex, Gemini).

        Updates in-memory WindowState and schedules a debounced state save.
        Must be called from the event loop thread (not from asyncio.to_thread)
        because _schedule_save() touches asyncio timer handles.

        Pair with write_hookless_session_map() for the file-locked
        session_map.json write, which is safe to call from any thread.
        """
        from .window_state_store import window_store

        state = window_store.get_window_state(window_id)
        state.session_id = session_id
        state.cwd = cwd
        state.transcript_path = transcript_path
        state.provider_name = provider_name
        self._schedule_save()

    def write_hookless_session_map(
        self,
        window_id: str,
        session_id: str,
        cwd: str,
        transcript_path: str,
        provider_name: str,
    ) -> None:
        """Write a synthetic entry to session_map.json for a hookless provider.

        Uses file locking consistent with hook.py. Safe to call from any
        thread (no asyncio handles touched).
        """
        from .thread_router import thread_router

        map_file = config.session_map_file
        map_file.parent.mkdir(parents=True, exist_ok=True)
        # Foreign windows (emdash) are already fully qualified
        if is_foreign_window(window_id):
            window_key = window_id
        else:
            window_key = f"{config.tmux_session_name}:{window_id}"
        lock_path = map_file.with_suffix(".lock")
        try:
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    session_map: dict[str, Any] = {}
                    if map_file.exists():
                        try:
                            parsed = json.loads(map_file.read_text())
                            if isinstance(parsed, dict):
                                session_map = parsed
                        except json.JSONDecodeError:
                            backup = map_file.with_suffix(".json.corrupt")
                            try:
                                import shutil

                                shutil.copy2(map_file, backup)
                                logger.warning(
                                    "Corrupted session_map.json backed up to %s",
                                    backup,
                                )
                            except OSError:
                                logger.warning(
                                    "Corrupted session_map.json (backup failed)"
                                )
                        except OSError:
                            logger.warning(
                                "Failed to read session_map.json for hookless write"
                            )
                    display_name = thread_router.get_display_name(window_id)
                    session_map[window_key] = {
                        "session_id": session_id,
                        "cwd": cwd,
                        "window_name": display_name,
                        "transcript_path": transcript_path,
                        "provider_name": provider_name,
                    }
                    atomic_write_json(map_file, session_map)
                    logger.info(
                        "Registered hookless session: %s -> session_id=%s, cwd=%s",
                        window_key,
                        session_id,
                        cwd,
                    )
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except OSError:
            logger.exception("Failed to write session_map for hookless session")

    def clear_session_map_entry(self, window_id: str) -> None:
        """Remove a window's entry from session_map.json if present."""
        if not config.session_map_file.exists():
            return
        lock_path = config.session_map_file.with_suffix(".lock")
        try:
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    raw = json.loads(config.session_map_file.read_text())
                    key = f"{config.tmux_session_name}:{window_id}"
                    if key in raw:
                        del raw[key]
                        atomic_write_json(config.session_map_file, raw)
                        logger.debug("Cleared session_map entry for %s", window_id)
                except (json.JSONDecodeError, OSError):  # fmt: skip
                    return
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except OSError:
            logger.debug("Failed to lock session_map for clearing %s", window_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_window_from_session_map(
        self,
        window_id: str,
        info: dict[str, Any],
        *,
        mark_external: bool = False,
    ) -> bool:
        """Sync a single window's state from session_map entry.

        Returns True if any state was changed.
        """
        from .thread_router import thread_router
        from .window_state_store import window_store

        effective = effective_session_map_info(window_id, info)
        new_sid = effective["session_id"]
        if not new_sid:
            return False
        new_cwd = effective["cwd"]
        new_wname = effective["window_name"]
        new_transcript = effective["transcript_path"]
        changed = False

        state = window_store.get_window_state(window_id)
        if mark_external and not state.external:
            state.external = True
            changed = True
        if mark_external and state.origin != "external":
            state.origin = "external"
            changed = True
        if state.session_id != new_sid or state.cwd != new_cwd:
            logger.info(
                "Session map: window_id %s updated sid=%s, cwd=%s",
                window_id,
                new_sid,
                new_cwd,
            )
            state.session_id = new_sid
            state.cwd = new_cwd
            changed = True
        if new_transcript and state.transcript_path != new_transcript:
            state.transcript_path = new_transcript
            changed = True
        new_provider = effective["provider_name"].lower()
        if new_provider and state.provider_name != new_provider:
            state.provider_name = new_provider
            changed = True
        if (
            new_wname
            and thread_router.get_display_name(window_id) == window_id
            and not state.window_name
        ):
            state.window_name = new_wname
            thread_router.set_display_name(window_id, new_wname)
            changed = True
        return changed


session_map_sync = SessionMapSync()
