# Session Map Resolution

## Functional Responsibilities

Reads Claude Code's hook-written `session_map.json` and `events.jsonl`, resolves transcript files, and publishes parsed messages and events to the rest of the system. This is the input side of the "agent → Telegram" pipeline.

Files:

- **`session_map.py`** (~500 lines) — `session_map_sync` singleton. Loads `session_map.json`, prunes stale entries, registers hookless sessions (for Codex/Gemini which have no hook), writes the map, syncs window display names with hook-provided metadata.
- **`session_resolver.py`** — Window → Session resolution via `session_map` lookup; exposes `get_recent_messages`, `resolve_session_for_window`, `ClaudeSession` dataclass. Delegates transcript parsing to the provider layer.
- **`session_monitor.py`** (~890 lines) — the poll loop that watches transcript files and `events.jsonl` incrementally. Reads new bytes via stored offsets, dispatches `NewMessage` events via a callback, dispatches `HookEvent` events to `hook_events.handle_event`.
- **`monitor_state.py`** — `MonitorState` dataclass and serialisation (`monitor_state.json` with per-session byte offsets + mtime cache).

## Encapsulated Knowledge

- **Incremental read semantics** — only `session_monitor` knows how to seek to a stored byte offset, read until EOF, detect truncation, reset on truncation, and update the offset atomically on success.
- **`session_map.json` schema** — only `session_map.py` reads/writes this file.
- **`events.jsonl` schema** — only `session_monitor` reads this; `hook_events` parses the payload.
- **NewMessage classification** — `session_monitor` owns the predicates for `is_tool_use`, `is_tool_result`, `is_thinking`, `is_interactive_tool` — by asking the provider to parse transcript entries and then classifying the result.
- **Session pruning rules** — entries are removed when the window is gone, the session file is deleted, or the tmux window ID is no longer in the live list.

## Subdomain Classification

**Core.** The input side of message delivery. Evolution tracks Claude Code's event surface and provider differences (hook-based vs. hookless).

## Integration Contracts

### Inbound

| From                                                                                          | Kind     | Contract           |
| --------------------------------------------------------------------------------------------- | -------- | ------------------ |
| `bot.post_init` → `session_monitor.start(bot, message_callback=..., hook_event_callback=...)` | Contract | Callback injection |
| `session_manager.load_session_map()` → `session_map_sync.load()`                              | Contract | Startup            |
| `session_manager.prune_session_map(live_ids)` → `session_map_sync.prune(...)`                 | Contract | Periodic cleanup   |

### Outbound

| To                                                                      | Kind     | Contract                                 |
| ----------------------------------------------------------------------- | -------- | ---------------------------------------- |
| `bot.message_callback` → `message_routing.handle_new_message(msg, bot)` | Contract | `NewMessage` event                       |
| `bot.hook_event_callback` → `hook_events.handle_event(event, bot)`      | Contract | `HookEvent` dataclass                    |
| `provider.parse_transcript_entries(...)`                                | Contract | Provider-specific parsing                |
| `provider.read_transcript_file(path, offset)`                           | Contract | Incremental read                         |
| `thread_router.set_display_name(wid, name)`                             | Contract | Display-name sync (after facade cleanup) |
| `window_store.update_cwd`, `clear_session_fields`                       | Contract | Session state sync                       |

## Change Vectors

- **New hook event type** — add parse + dispatch in `session_monitor`; add handler in `hook_events`.
- **Change the poll cadence** — `session_monitor.POLL_INTERVAL` constant.
- **Add a new provider's transcript format** — implement `provider.read_transcript_file` + `parse_transcript_entries`; no change to `session_monitor`.
- **Persist `MonitorState` differently** — `monitor_state.py` only.

## Testability Goals

- **Unit-test incremental byte-offset read** with a fixture file and a sequence of appends; verify each read picks up only new content.
- **Unit-test truncation recovery** — seed a large offset, truncate the file to smaller, verify the offset resets.
- **Unit-test `session_map_sync.prune`** with a synthetic map and a live-ID set.
- **Integration-test the monitor→callback chain** with a fake transcript file and a fake callback; verify `NewMessage` events are delivered in order.
- **Unit-test `NewMessage` classification** with fixture Claude JSONL entries.
