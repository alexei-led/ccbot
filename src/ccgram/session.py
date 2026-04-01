"""Claude Code session management — the core state hub.

Manages the key mappings:
  Window→Session (window_states): which Claude session_id a window holds (keyed by window_id).
  User→Thread→Window: delegated to ThreadRouter (see thread_router.py).

Responsibilities:
  - Persist/load state to ~/.ccgram/state.json.
  - Sync window↔session bindings from session_map.json (written by hook).
  - Resolve window IDs to ClaudeSession objects (JSONL file reading).
  - Delegate thread↔window routing to ThreadRouter.
  - Send keystrokes to tmux windows and retrieve message history.
  - Re-resolve stale window IDs on startup (tmux server restart recovery).

Key class: SessionManager (singleton instantiated as `session_manager`).
Thread routing: delegated to ThreadRouter (see thread_router.py) — no pass-throughs.
"""

import asyncio
import fcntl
import json
import structlog
from dataclasses import dataclass, field
from typing import Any

import aiofiles

from .config import config
from .session_resolver import ClaudeSession
from .state_persistence import StatePersistence
from .tmux_manager import tmux_manager
from .thread_router import thread_router
from .user_preferences import user_preferences
from .utils import atomic_write_json
from .window_resolver import EMDASH_SESSION_PREFIX, is_foreign_window, is_window_id
from .window_state_store import (
    APPROVAL_MODES,
    BATCH_MODES,
    DEFAULT_APPROVAL_MODE,
    DEFAULT_BATCH_MODE,
    NOTIFICATION_MODES,
    WindowState,
    window_store,
)

logger = structlog.get_logger()


_LEGACY_SESSION_PREFIX = "ccbot:"


def parse_session_map(raw: dict[str, Any], prefix: str) -> dict[str, dict[str, str]]:
    """Parse session_map.json entries matching a tmux session prefix.

    Also matches legacy "ccbot:" prefix keys when the current prefix is "ccgram:".
    Returns {window_name: {"session_id": ..., "cwd": ...}} for matching entries.
    """
    result: dict[str, dict[str, str]] = {}
    # Also accept legacy "ccbot:" prefix keys when session is "ccgram"
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
        session_id = info.get("session_id", "")
        if session_id:
            result[window_name] = {
                "session_id": session_id,
                "cwd": info.get("cwd", ""),
                "window_name": info.get("window_name", ""),
                "transcript_path": info.get("transcript_path", ""),
                "provider_name": info.get("provider_name", ""),
            }
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
class AuditIssue:
    """A single issue found during state audit."""

    category: str  # ghost_binding | orphaned_display_name | orphaned_group_chat_id | stale_window_state | stale_offset | display_name_drift
    detail: str
    fixable: bool


@dataclass
class AuditResult:
    """Result of a state audit."""

    issues: list[AuditIssue]
    total_bindings: int
    live_binding_count: int

    @property
    def fixable_count(self) -> int:
        return sum(1 for i in self.issues if i.fixable)

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0


def _migrate_mailbox_ids(
    old_display: dict[str, str],
    new_states: dict[str, "WindowState"],
    tmux_session: str,
) -> None:
    """Migrate mailbox directories when window IDs change after tmux restart.

    Builds a remap dict by matching old→new IDs via display name, then
    renames mailbox directories to match.
    """
    # Build new key→display_name from current window_display_names
    new_display = {
        wid: thread_router.window_display_names.get(wid, "") for wid in new_states
    }
    # Invert new display → new_id
    display_to_new: dict[str, str] = {}
    for wid, name in new_display.items():
        if name:
            display_to_new[name] = wid

    remap: dict[str, str] = {}
    for old_id, name in old_display.items():
        if not name or old_id in new_states:
            continue
        new_id = display_to_new.get(name)
        if new_id and new_id != old_id:
            remap[f"{tmux_session}:{old_id}"] = f"{tmux_session}:{new_id}"

    if remap:
        from .mailbox import Mailbox

        Mailbox(config.mailbox_dir).migrate_ids(remap)


@dataclass
class SessionManager:
    """Manages session state for Claude Code.

    All internal keys use window_id (e.g. '@0', '@12') for uniqueness.
    Display names (window_name) are stored separately for UI presentation.

    Thread routing (thread_bindings, display names, group_chat_ids) is
    delegated to ThreadRouter — see thread_router.py.

    window_states: window_id -> WindowState (session_id, cwd, window_name)

    User preferences (starred dirs, MRU, read offsets) are delegated to
    UserPreferences — see user_preferences.py.
    """

    # Delegated persistence (not serialized)
    _persistence: StatePersistence = field(default=None, repr=False, init=False)  # type: ignore[assignment]

    @property
    def window_states(self) -> dict[str, WindowState]:
        return window_store.window_states

    # Backward-compat properties for routing data (owned by thread_router)
    @property
    def thread_bindings(self) -> dict[int, dict[int, str]]:
        return thread_router.thread_bindings

    @property
    def group_chat_ids(self) -> dict[str, int]:
        return thread_router.group_chat_ids

    @property
    def window_display_names(self) -> dict[str, str]:
        return thread_router.window_display_names

    def __post_init__(self) -> None:
        self._persistence = StatePersistence(config.state_file, self._serialize_state)
        window_store._schedule_save = self._save_state
        window_store._on_hookless_provider_switch = self._clear_session_map_entry
        thread_router._schedule_save = self._save_state
        thread_router._has_window_state = lambda wid: wid in window_store.window_states
        user_preferences._schedule_save = self._save_state
        self._load_state()

    def _serialize_state(self) -> dict[str, Any]:
        """Serialize all state to a dict for persistence."""
        result = {"window_states": window_store.to_dict()}
        result.update(user_preferences.to_dict())
        result.update(thread_router.to_dict())
        return result

    def _save_state(self) -> None:
        """Schedule debounced save (0.5s delay, resets on each call)."""
        self._persistence.schedule_save()

    def flush_state(self) -> None:
        """Force immediate save. Call on shutdown."""
        self._persistence.flush()

    def _is_window_id(self, key: str) -> bool:
        """Check if a key looks like a tmux window ID (e.g. '@0', '@12')."""
        return is_window_id(key)

    def _load_state(self) -> None:
        """Load state during initialization.

        Detects old-format state (window_name keys without '@' prefix) and
        marks for migration on next startup re-resolution.
        """
        state = self._persistence.load()
        if not state:
            return

        window_store.from_dict(state.get("window_states", {}))

        # Load user preferences (starred dirs, MRU, read offsets)
        user_preferences.from_dict(state)

        # Load routing data into ThreadRouter (handles dedup + reverse index)
        thread_router.from_dict(state)

        # Detect old format: keys that don't look like window IDs
        # Foreign windows (emdash) use qualified IDs — not old format.
        needs_migration = False
        for k in window_store.window_states:
            if not self._is_window_id(k) and not is_foreign_window(k):
                needs_migration = True
                break
        if not needs_migration:
            for bindings in thread_router.thread_bindings.values():
                for wid in bindings.values():
                    if not self._is_window_id(wid) and not is_foreign_window(wid):
                        needs_migration = True
                        break
                if needs_migration:
                    break

        if needs_migration:
            logger.info(
                "Detected old-format state (window_name keys), "
                "will re-resolve on startup"
            )

    async def resolve_stale_ids(self) -> None:
        """Re-resolve persisted window IDs against live tmux windows.

        Called on startup. Delegates to window_resolver for the heavy lifting.
        Dead window bindings and states are preserved for /restore recovery.
        Also migrates mailbox directories when window IDs change.
        """
        from .window_resolver import LiveWindow, resolve_stale_ids as _resolve

        windows = await tmux_manager.list_windows()
        live = [
            LiveWindow(window_id=w.window_id, window_name=w.window_name)
            for w in windows
        ]

        # Snapshot old key→display_name mapping for mailbox migration
        tmux_session = config.tmux_session_name
        old_display = {
            wid: thread_router.window_display_names.get(wid, "")
            for wid in self.window_states
        }

        changed = _resolve(
            live,
            self.window_states,
            thread_router.thread_bindings,
            user_preferences.user_window_offsets,
            thread_router.window_display_names,
        )

        if changed:
            thread_router._rebuild_reverse_index()
            self._save_state()
            logger.info("Startup re-resolution complete")

            # Migrate mailbox directories for remapped window IDs
            _migrate_mailbox_ids(old_display, self.window_states, tmux_session)

        # Prune session_map.json entries for dead windows
        live_ids = {w.window_id for w in live}
        self.prune_session_map(live_ids)

        # Sync display names from live tmux windows (detect external renames)
        live_pairs = [(w.window_id, w.window_name) for w in live]
        self.sync_display_names(live_pairs)

        # Prune orphaned display names (preserve group_chat_ids for post-restart topic creation)
        self.prune_stale_state(live_ids, skip_chat_ids=True)

    # --- Display name management (delegated to thread_router) ---

    def get_display_name(self, window_id: str) -> str:
        """Get display name for a window_id, fallback to window_id itself."""
        return thread_router.get_display_name(window_id)

    def set_display_name(self, window_id: str, window_name: str) -> None:
        """Update display name for a window_id."""
        thread_router.set_display_name(window_id, window_name)
        # Also update WindowState if it exists
        ws = self.window_states.get(window_id)
        if ws:
            ws.window_name = window_name

    def sync_display_names(self, live_windows: list[tuple[str, str]]) -> bool:
        """Sync display names from live tmux windows. Returns True if changed."""
        router_changed = thread_router.sync_display_names(live_windows)
        # Always reconcile WindowState.window_name — the router may already
        # have the correct name while WindowState is still stale from older
        # persisted state.
        ws_changed = False
        for window_id, window_name in live_windows:
            ws = self.window_states.get(window_id)
            if ws and ws.window_name != window_name:
                ws.window_name = window_name
                ws_changed = True
        # Router saves itself when router_changed; persist WindowState repairs
        # even when the router side was already correct.
        if ws_changed and not router_changed:
            self._save_state()
        return router_changed or ws_changed

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
                        # Found — load into window_states immediately
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

    def prune_stale_state(
        self, live_window_ids: set[str], *, skip_chat_ids: bool = False
    ) -> bool:
        """Remove orphaned entries from window_display_names and group_chat_ids.

        Returns True if any changes were made.
        When skip_chat_ids=True, group_chat_ids are preserved (used during startup
        so they remain available for post-restart topic creation).
        """
        # Collect window_ids that are "in use" (bound or have window_states)
        in_use = set(self.window_states.keys())
        for bindings in thread_router.thread_bindings.values():
            in_use.update(bindings.values())

        # Prune window_display_names for dead windows not in use and not live
        stale_display = [
            wid
            for wid in thread_router.window_display_names
            if wid not in live_window_ids and wid not in in_use
        ]

        # Collect all bound thread keys "user_id:thread_id"
        bound_keys: set[str] = set()
        for user_id, bindings in thread_router.thread_bindings.items():
            for thread_id in bindings:
                bound_keys.add(f"{user_id}:{thread_id}")

        # Prune group_chat_ids for unbound threads (unless skipped)
        stale_chat = (
            []
            if skip_chat_ids
            else [k for k in thread_router.group_chat_ids if k not in bound_keys]
        )

        # Prune stale byte offsets (independent of display/chat pruning)
        all_known = live_window_ids | in_use
        offsets_changed = self.prune_stale_offsets(all_known)

        # Prune dead mailbox directories
        qualified_live: set[str] = set()
        for wid in all_known:
            if is_foreign_window(wid):
                qualified_live.add(wid)
            else:
                qualified_live.add(f"{config.tmux_session_name}:{wid}")
        from .mailbox import Mailbox

        Mailbox(config.mailbox_dir).prune_dead(qualified_live)

        if not stale_display and not stale_chat:
            return offsets_changed

        for wid in stale_display:
            logger.info(
                "Pruning stale display name: %s (%s)",
                wid,
                thread_router.window_display_names[wid],
            )
            del thread_router.window_display_names[wid]
        for key in stale_chat:
            logger.info("Pruning stale group_chat_id: %s", key)
            del thread_router.group_chat_ids[key]

        self._save_state()
        return True

    def prune_session_map(self, live_window_ids: set[str]) -> None:
        """Remove session_map.json entries for windows that no longer exist.

        Reads session_map.json, drops entries whose window_id is not in
        live_window_ids, and writes back only if changes were made.
        Also removes corresponding window_states.
        """
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
            if self._is_window_id(window_id) and window_id not in live_window_ids:
                dead_entries.append((key, window_id))

        if not dead_entries:
            return

        changed_state = False
        for key, window_id in dead_entries:
            logger.info(
                "Pruning dead session_map entry: %s (window %s)", key, window_id
            )
            del raw[key]
            if window_id in self.window_states:
                del self.window_states[window_id]
                changed_state = True

        atomic_write_json(config.session_map_file, raw)
        if changed_state:
            self._save_state()

    def _get_session_map_window_ids(self) -> set[str]:
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
                if self._is_window_id(wid):
                    result.add(wid)
            elif key.startswith(EMDASH_SESSION_PREFIX):
                result.add(key)
        return result

    def audit_state(
        self,
        live_window_ids: set[str],
        live_windows: list[tuple[str, str]],
    ) -> AuditResult:
        """Read-only audit of all state maps against live tmux windows.

        Args:
            live_window_ids: Set of currently alive tmux window IDs.
            live_windows: List of (window_id, window_name) for live windows.

        Returns:
            AuditResult with discovered issues.
        """
        issues: list[AuditIssue] = []

        # Collect all bound window IDs
        bound_window_ids: set[str] = set()
        total_bindings = 0
        live_binding_count = 0
        for _uid, bindings in thread_router.thread_bindings.items():
            for _tid, wid in bindings.items():
                total_bindings += 1
                bound_window_ids.add(wid)
                if wid in live_window_ids:
                    live_binding_count += 1

        session_map_wids = self._get_session_map_window_ids()

        # 1. Ghost bindings (thread → dead window) — fixable (close topic)
        for uid, bindings in thread_router.thread_bindings.items():
            for tid, wid in bindings.items():
                if wid not in live_window_ids:
                    display = self.get_display_name(wid)
                    issues.append(
                        AuditIssue(
                            category="ghost_binding",
                            detail=f"user:{uid} thread:{tid} window:{wid} ({display})",
                            fixable=True,
                        )
                    )

        # 2. Orphaned display names
        in_use = set(self.window_states.keys()) | bound_window_ids
        for wid in thread_router.window_display_names:
            if wid not in live_window_ids and wid not in in_use:
                name = thread_router.window_display_names[wid]
                issues.append(
                    AuditIssue(
                        category="orphaned_display_name",
                        detail=f"{wid} ({name})",
                        fixable=True,
                    )
                )

        # 3. Orphaned group_chat_ids
        bound_keys: set[str] = set()
        for user_id, bindings in thread_router.thread_bindings.items():
            for thread_id in bindings:
                bound_keys.add(f"{user_id}:{thread_id}")
        for key in thread_router.group_chat_ids:
            if key not in bound_keys:
                issues.append(
                    AuditIssue(
                        category="orphaned_group_chat_id",
                        detail=f"key {key}",
                        fixable=True,
                    )
                )

        # 4. Stale window_states (not in session_map, not bound, not live)
        for wid in self.window_states:
            if (
                wid not in session_map_wids
                and wid not in bound_window_ids
                and wid not in live_window_ids
            ):
                display = self.window_states[wid].window_name or wid
                issues.append(
                    AuditIssue(
                        category="stale_window_state",
                        detail=f"{wid} ({display})",
                        fixable=True,
                    )
                )

        # 5. Stale user_window_offsets
        known_wids = live_window_ids | bound_window_ids | set(self.window_states.keys())
        for uid, offsets in user_preferences.user_window_offsets.items():
            for wid in offsets:
                if wid not in known_wids:
                    issues.append(
                        AuditIssue(
                            category="stale_offset",
                            detail=f"user {uid}, window {wid}",
                            fixable=True,
                        )
                    )

        # 6. Display name drift (stored != tmux)
        for wid, tmux_name in live_windows:
            stored_name = thread_router.window_display_names.get(wid)
            if stored_name and stored_name != tmux_name:
                issues.append(
                    AuditIssue(
                        category="display_name_drift",
                        detail=f"{wid}: stored={stored_name!r} tmux={tmux_name!r}",
                        fixable=True,
                    )
                )

        # 7. Orphaned tmux windows (live, known to ccgram, but not bound to any topic)
        known_wids = session_map_wids | set(self.window_states.keys())
        for wid in live_window_ids:
            if wid not in bound_window_ids and wid in known_wids:
                name = dict(live_windows).get(wid, wid)
                issues.append(
                    AuditIssue(
                        category="orphaned_window",
                        detail=f"{wid} ({name})",
                        fixable=True,
                    )
                )

        return AuditResult(
            issues=issues,
            total_bindings=total_bindings,
            live_binding_count=live_binding_count,
        )

    def prune_stale_offsets(self, known_window_ids: set[str]) -> bool:
        """Remove user_window_offsets entries for unknown windows.

        Returns True if any changes were made.
        """
        return user_preferences.prune_stale_offsets(known_window_ids)

    def prune_stale_window_states(self, live_window_ids: set[str]) -> bool:
        """Remove window_states not in session_map, not bound, and not live.

        Returns True if any changes were made.
        """
        session_map_wids = self._get_session_map_window_ids()
        bound_window_ids: set[str] = set()
        for bindings in thread_router.thread_bindings.values():
            bound_window_ids.update(bindings.values())

        stale = [
            wid
            for wid in self.window_states
            if (
                wid not in session_map_wids
                and wid not in bound_window_ids
                and wid not in live_window_ids
            )
        ]
        if not stale:
            return False
        for wid in stale:
            logger.info("Pruning stale window_state: %s", wid)
            del self.window_states[wid]
        self._save_state()
        return True

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
        new_sid = info.get("session_id", "")
        if not new_sid:
            return False
        new_cwd = info.get("cwd", "")
        new_wname = info.get("window_name", "")
        new_transcript = info.get("transcript_path", "")
        changed = False

        state = self.get_window_state(window_id)
        if mark_external and not state.external:
            state.external = True
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
        # Sync provider_name from session_map (hook data is authoritative).
        new_provider = info.get("provider_name", "")
        if new_provider and state.provider_name != new_provider:
            state.provider_name = new_provider
            changed = True
        # Initialize display name from session_map only when unknown.
        if (
            new_wname
            and not thread_router.window_display_names.get(window_id)
            and not state.window_name
        ):
            state.window_name = new_wname
            thread_router.window_display_names[window_id] = new_wname
            changed = True
        return changed

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
        valid_wids: set[str] = set()
        # Track session_ids from old-format entries so we don't nuke
        # migrated window_states before the new hook has fired.
        old_format_sids: set[str] = set()
        changed = False

        old_format_keys: list[str] = []
        for key, info in session_map.items():
            if not isinstance(info, dict):
                continue

            # Emdash entries: use the full key as window_id
            if key.startswith(EMDASH_SESSION_PREFIX):
                valid_wids.add(key)
                if self._sync_window_from_session_map(key, info, mark_external=True):
                    changed = True
                # Infer provider from session name — always attempt if missing,
                # regardless of whether _sync changed other fields.
                state = self.get_window_state(key)
                if not state.provider_name:
                    session_name = key.rsplit(":", 1)[0]
                    detected = parse_emdash_provider(session_name)
                    if detected:
                        state.provider_name = detected
                        changed = True
                continue

            # Native entries: strip prefix, process by window_id
            if not key.startswith(prefix):
                continue
            window_id = key[len(prefix) :]
            # Old-format key (window_name instead of window_id): remember the
            # session_id so migrated window_states survive stale cleanup,
            # then mark for removal from session_map.json.
            if not self._is_window_id(window_id):
                sid = info.get("session_id", "")
                if sid:
                    old_format_sids.add(sid)
                old_format_keys.append(key)
                continue
            valid_wids.add(window_id)
            if self._sync_window_from_session_map(window_id, info):
                changed = True

        # Clean up window_states entries not in current session_map.
        # Protect entries whose session_id is still referenced by old-format
        # keys — those sessions are valid but haven't re-triggered the hook yet.
        # Also protect entries bound to a topic (hookless providers like codex/gemini
        # never appear in session_map but still need their window state preserved).
        bound_wids = {
            wid
            for user_bindings in thread_router.thread_bindings.values()
            for wid in user_bindings.values()
            if wid
        }
        stale_wids = [
            w
            for w in self.window_states
            if w
            and w not in valid_wids
            and w not in bound_wids
            and self.window_states[w].session_id not in old_format_sids
        ]
        for wid in stale_wids:
            logger.info("Removing stale window_state: %s", wid)
            del self.window_states[wid]
            changed = True

        # Purge old-format keys from session_map.json so they don't
        # get logged every poll cycle.
        if old_format_keys:
            for key in old_format_keys:
                logger.info("Removing old-format session_map key: %s", key)
                del session_map[key]
            atomic_write_json(config.session_map_file, session_map)

        if changed:
            self._save_state()

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
        because _save_state() touches asyncio timer handles.

        Pair with write_hookless_session_map() for the file-locked
        session_map.json write, which is safe to call from any thread.
        """
        state = self.get_window_state(window_id)
        state.session_id = session_id
        state.cwd = cwd
        state.transcript_path = transcript_path
        state.provider_name = provider_name
        self._save_state()

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
        import fcntl

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
                    display_name = self.get_display_name(window_id)
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

    def get_session_id_for_window(self, window_id: str) -> str | None:
        """Look up session_id for a window from window_states."""
        return window_store.get_session_id_for_window(window_id)

    # --- Window state management ---

    def get_window_state(self, window_id: str) -> WindowState:
        """Get or create window state."""
        return window_store.get_window_state(window_id)

    def clear_window_session(self, window_id: str) -> None:
        """Clear session association for a window (e.g., after /clear command)."""
        window_store.clear_window_session(window_id)

    # --- Provider management ---

    def set_window_provider(
        self,
        window_id: str,
        provider_name: str,
        *,
        cwd: str | None = None,
    ) -> None:
        """Set the provider for a window."""
        window_store.set_window_provider(window_id, provider_name, cwd=cwd)

    def _clear_session_map_entry(self, window_id: str) -> None:
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

    def get_approval_mode(self, window_id: str) -> str:
        """Get approval mode for a window (default: 'normal')."""
        state = self.window_states.get(window_id)
        mode = state.approval_mode if state else DEFAULT_APPROVAL_MODE
        return mode if mode in APPROVAL_MODES else DEFAULT_APPROVAL_MODE

    def set_window_approval_mode(self, window_id: str, mode: str) -> None:
        """Set approval mode for a window."""
        normalized = mode.lower()
        if normalized not in APPROVAL_MODES:
            raise ValueError(f"Invalid approval mode: {mode!r}")
        state = self.get_window_state(window_id)
        state.approval_mode = normalized
        self._save_state()

    def get_window_for_chat_thread(self, chat_id: int, thread_id: int) -> str | None:
        """Resolve window_id for a specific Telegram chat/thread pair."""
        return thread_router.get_window_for_chat_thread(chat_id, thread_id)

    # --- Notification mode ---

    _NOTIFICATION_MODES = NOTIFICATION_MODES

    def get_notification_mode(self, window_id: str) -> str:
        """Get notification mode for a window (default: 'all')."""
        state = self.window_states.get(window_id)
        return state.notification_mode if state else "all"

    def set_notification_mode(self, window_id: str, mode: str) -> None:
        """Set notification mode for a window."""
        if mode not in self._NOTIFICATION_MODES:
            raise ValueError(f"Invalid notification mode: {mode!r}")
        state = self.get_window_state(window_id)
        if state.notification_mode != mode:
            state.notification_mode = mode
            self._save_state()

    def cycle_notification_mode(self, window_id: str) -> str:
        """Cycle notification mode: all → errors_only → muted → all. Returns new mode."""
        current = self.get_notification_mode(window_id)
        modes = self._NOTIFICATION_MODES
        idx = modes.index(current) if current in modes else 0
        new_mode = modes[(idx + 1) % len(modes)]
        self.set_notification_mode(window_id, new_mode)
        return new_mode

    # --- Batch mode ---

    def get_batch_mode(self, window_id: str) -> str:
        """Get batch mode for a window (default: 'batched')."""
        state = self.window_states.get(window_id)
        mode = state.batch_mode if state else DEFAULT_BATCH_MODE
        return mode if mode in BATCH_MODES else DEFAULT_BATCH_MODE

    def set_batch_mode(self, window_id: str, mode: str) -> None:
        """Set batch mode for a window."""
        if mode not in BATCH_MODES:
            raise ValueError(f"Invalid batch mode: {mode!r}")
        state = self.get_window_state(window_id)
        if state.batch_mode != mode:
            state.batch_mode = mode
            self._save_state()

    def cycle_batch_mode(self, window_id: str) -> str:
        """Toggle batch mode: batched ↔ verbose. Returns new mode."""
        current = self.get_batch_mode(window_id)
        new_mode = "verbose" if current == "batched" else "batched"
        self.set_batch_mode(window_id, new_mode)
        return new_mode

    # --- Window → Session resolution (delegated to session_resolver) ---

    async def _get_session_direct(
        self, session_id: str, cwd: str, window_id: str = ""
    ) -> "ClaudeSession | None":
        """Delegate to session_resolver._get_session_direct."""
        from .session_resolver import session_resolver

        return await session_resolver._get_session_direct(session_id, cwd, window_id)

    async def resolve_session_for_window(
        self, window_id: str
    ) -> "ClaudeSession | None":
        """Delegate to session_resolver.resolve_session_for_window."""
        from .session_resolver import session_resolver

        return await session_resolver.resolve_session_for_window(window_id)

    def find_users_for_session(
        self,
        session_id: str,
    ) -> list[tuple[int, str, int]]:
        """Delegate to session_resolver.find_users_for_session."""
        from .session_resolver import session_resolver

        return session_resolver.find_users_for_session(session_id)

    # --- Message history (delegated to session_resolver) ---

    async def get_recent_messages(
        self,
        window_id: str,
        *,
        start_byte: int = 0,
        end_byte: int | None = None,
    ) -> tuple[list[dict], int]:
        """Delegate to session_resolver.get_recent_messages."""
        from .session_resolver import session_resolver

        return await session_resolver.get_recent_messages(
            window_id, start_byte=start_byte, end_byte=end_byte
        )


session_manager = SessionManager()
