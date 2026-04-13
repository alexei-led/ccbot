# Inter-Agent Messaging

## Functional Responsibilities

Agents running in tmux windows (Claude Code, Codex, Gemini) can discover each other, send messages, broadcast, and request spawning of new agents — with human oversight via Telegram. Uses a file-based mailbox at `~/.ccgram/mailbox/` with per-window inbox directories and timestamp-prefixed JSON messages.

Files:

- **`mailbox.py`** (~592 lines) — core file-based mailbox. Message CRUD, TTL expiration, sweep, ID migration, broadcast fanout. Atomic writes.
- **`msg_cmd.py`** (~545 lines) — CLI `ccgram msg` group: send, inbox, read, reply, broadcast, register, spawn, list-peers, find, sweep.
- **`msg_discovery.py`** — peer discovery: view over SessionManager + self-declared overlay (task, team).
- **`msg_skill.py`** — messaging skill auto-installation for Claude Code agents. Copies a skill file into the agent's working directory so the agent sees it as an available capability.
- **`spawn_request.py`** — spawn request data types, file-based CRUD, public accessor API (get/pop/iter/register_pending).
- **`handlers/msg_broker.py`** — broker delivery: poll loop injects pending messages into idle agent windows via `send_keys`.
- **`handlers/msg_delivery.py`** — message delivery state: per-window tracking, rate limiting, loop detection (extracted from msg_broker).
- **`handlers/msg_spawn.py`** — agent spawn requests with Telegram approval flow and auto-topic creation.
- **`handlers/msg_telegram.py`** — Telegram notifications for inter-agent messages (silent, grouped, edit-in-place).

## Encapsulated Knowledge

- **Mailbox file format** — `mailbox.py` owns the JSON schema and the timestamp-prefixed filename convention. Atomic write via rename.
- **Qualified ID format** — `session:@N` matching session_map convention. Parsing and validation live in `mailbox.py`.
- **Peer discovery overlay** — `msg_discovery.py` knows how to combine live session information with self-declared metadata (task, team) into a peer view.
- **Broker injection mechanism** — `msg_broker.py` owns the "find idle windows, inject messages via send_keys" logic. Shell windows are inbox-only and bypassed by the broker.
- **Rate limiting and loop detection** — `msg_delivery.py` owns per-window tracking of message count, spawn count, and loop prevention.
- **Spawn approval flow** — `msg_spawn.py` owns the Telegram inline-keyboard approval UI, timeout, and auto-topic creation on accept.
- **Messaging skill installation** — `msg_skill.py` owns the skill file content and the install path under the Claude config dir.

## Subdomain Classification

**Core.** New feature still stabilising. Active development on rate limiting, loop detection, discovery overlay.

## Integration Contracts

### Inbound

| From                                                                                                                                                      | Kind     |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `ccgram msg send/inbox/read/...` CLI → `mailbox.*`                                                                                                        | Contract |
| `periodic_tasks.run_periodic_tasks` → `msg_broker.deliver_pending_messages(bot)`, `msg_broker.sweep_expired()`, `msg_spawn.process_pending_requests(bot)` | Contract |
| `msg_skill.install` called from `directory_callbacks._create_window_and_bind` for Claude windows                                                          | Contract |

### Outbound

| To                                                                                 | Kind     |
| ---------------------------------------------------------------------------------- | -------- |
| `session_manager.thread_bindings` / `window_states` (read-only) for peer discovery | Model    |
| `tmux_manager.send_keys` for broker injection                                      | Contract |
| `message_sender.safe_send` / `safe_edit` for Telegram notifications                | Contract |
| `topic_orchestration.create_topic_for_window` for spawn auto-create                | Contract |
| `thread_router.resolve_chat_id` / `set_display_name`                               | Contract |
| `atomic_write_json`, `os.rename` for persistence                                   | stdlib   |

### File-based contract

```
~/.ccgram/mailbox/
  {session}:@{window}/
    inbox/
      {timestamp}-{sender}-{id}.json
    outbox/
      {timestamp}-{to}-{id}.json (optional — delivery receipts)
    task.json     (self-declared task)
    team.json     (self-declared team)
```

The filesystem IS the contract — multiple bot instances on the same host can share the mailbox by filesystem convention.

## Change Vectors

- **New message field** — `mailbox.Message` dataclass + JSON schema.
- **New discovery attribute** — `msg_discovery` overlay.
- **New spawn constraint** — `msg_spawn` approval flow.
- **Change rate limit values** — config.
- **New CLI subcommand** — `msg_cmd.py` Click command.

## Testability Goals

- **Unit-test mailbox CRUD** with a tmpfs fixture.
- **Unit-test ID migration** from old formats to current format.
- **Unit-test `msg_delivery.rate_limit_check`** with a fake clock.
- **Unit-test broker idle detection** with fake pane text showing prompt/busy/interactive.
- **Unit-test spawn approval** with a mocked bot — verify accept triggers `create_topic_for_window`, reject discards the request.
- **Integration-test `ccgram msg send --wait` deadlock prevention** — two agents message each other with `--wait`, verify the timeout fires instead of hanging.
- **Filesystem test** — two `Mailbox` instances (simulating two bot processes) share a directory, verify concurrent writes don't collide.
