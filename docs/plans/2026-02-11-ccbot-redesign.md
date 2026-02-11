# ccbot Redesign: Multi-Instance, Command Overhaul & UI Modernization

## Problem

ccbot has grown into a mature bridge between Telegram and Claude Code, but several areas need redesign:

1. **Single-instance limitation** — no clean way to run multiple ccbot instances (across machines or tmux sessions) sharing one Telegram bot
2. **Command clutter** — mix of bot-native and CC pass-through commands with confusing names (`/start`) and dangerous-feeling top-level commands (`/kill`, `/esc`)
3. **No session recovery** — dead tmux windows leave topics permanently broken
4. **Static UI** — no session status indicators, no dashboard, no contextual quick actions

## Solution Overview

```
┌─────────────────────────────────────────────────┐
│              Shared Telegram Bot Token           │
├────────────────────┬────────────────────────────┤
│   ccbot instance A │   ccbot instance B         │
│   GROUP_ID=<A>     │   GROUP_ID=<B>             │
│   TMUX=work        │   TMUX=home                │
│   Machine: mac     │   Machine: server          │
├────────────────────┴────────────────────────────┤
│  Per-instance: state dir, session_map, topics   │
│  Shared: bot token, allowed_users, commands     │
└─────────────────────────────────────────────────┘
```

---

## 1. Multi-Instance Architecture

### Config Changes

New environment variables:

| Variable              | Required    | Default  | Purpose                           |
| --------------------- | ----------- | -------- | --------------------------------- |
| `CCBOT_GROUP_ID`      | Yes (multi) | —        | Telegram group this instance owns |
| `CCBOT_INSTANCE_NAME` | No          | hostname | Display name for dashboard        |

### Update Filtering

Each instance filters all incoming updates at the top of every handler:

```python
def _is_my_group(update: Update) -> bool:
    """Return True if this update belongs to our group."""
    if not config.group_id:
        return True  # single-instance mode, accept all
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id == config.group_id
```

Applied as earliest check in `text_handler`, `callback_query_handler`, `forward_command_handler`, etc. Updates from other groups are silently ignored (the other instance handles them).

### State Isolation

Already supported via `CCBOT_DIR`:

- Instance A: `CCBOT_DIR=~/.ccbot-work/`
- Instance B: `CCBOT_DIR=~/.ccbot-home/`

Each instance has its own `state.json`, `session_map.json`, `monitor_state.json`.

### No Cross-Instance Coordination

Instances are fully independent. They share a bot token but own different groups. No shared state, no IPC, no distributed locking.

---

## 2. Command Overhaul

### Tier 1: Bot-Native Commands

| Command     | Description                                            | Replaces   |
| ----------- | ------------------------------------------------------ | ---------- |
| `/new`      | Create new session (directory browser / window picker) | `/start`   |
| `/resume`   | Resume a closed session (picker by project)            | — new —    |
| `/sessions` | Dashboard: all active sessions with status             | — new —    |
| `/history`  | Paginated message history (keep as-is)                 | `/history` |

### Tier 2: Auto-Discovered CC Commands

Discovered at startup from filesystem, refreshed every 10 minutes:

```python
def discover_cc_commands() -> list[CCCommand]:
    commands = []

    # 1. Built-in CC slash commands (hardcoded)
    CC_BUILTINS = {
        "clear": "Clear conversation history",
        "compact": "Compact conversation context",
        "cost": "Show token/cost usage",
        "help": "Show Claude Code help",
        "memory": "Edit CLAUDE.md",
    }
    for name, desc in CC_BUILTINS.items():
        commands.append(CCCommand(name=name, description=f"↗ {desc}", source="builtin"))

    # 2. User-invocable skills (~/.claude/skills/)
    for skill_dir in Path("~/.claude/skills").expanduser().iterdir():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            meta = parse_yaml_frontmatter(skill_md)
            if meta.get("user-invocable"):
                commands.append(CCCommand(
                    name=meta["name"],
                    description=f"↗ {meta.get('description', '')}",
                    source="skill",
                ))

    # 3. Custom commands (~/.claude/commands/)
    for cmd_dir in Path("~/.claude/commands").expanduser().iterdir():
        for cmd_file in cmd_dir.glob("*.md"):
            group = cmd_dir.name
            name = cmd_file.stem
            meta = parse_yaml_frontmatter(cmd_file)
            commands.append(CCCommand(
                name=f"{group}:{name}",
                description=f"↗ {meta.get('description', '')}",
                source="command",
            ))

    return commands
```

All discovered commands are registered via `set_my_commands()` and forwarded to CC via tmux keystrokes (existing `forward_command_handler` behavior).

### Tier 3: Contextual Inline Actions

Commands demoted from top-level to contextual buttons:

| Old Command   | New Location            | Trigger                                     |
| ------------- | ----------------------- | ------------------------------------------- |
| `/esc`        | `[Esc]` button          | On status messages and screenshot keyboard  |
| `/kill`       | `[Kill Session]` button | In `/sessions` dashboard, with confirmation |
| `/screenshot` | `[📸]` button           | On status messages and as quick action      |

### Menu Registration

```python
async def register_commands(bot: Bot, cc_commands: list[CCCommand]) -> None:
    commands = [
        BotCommand("new", "Create new Claude session"),
        BotCommand("resume", "Resume a closed session"),
        BotCommand("sessions", "Active sessions dashboard"),
        BotCommand("history", "Message history"),
    ]
    for cmd in cc_commands[:46]:  # Telegram limit: 50 commands per menu
        # Truncate description to 256 chars (Telegram limit)
        commands.append(BotCommand(cmd.name, cmd.description[:256]))
    await bot.set_my_commands(commands)
```

---

## 3. Session Resume / Continue

### Dead Window Detection

When a user sends a message in a topic bound to a window that no longer exists:

```
User sends "hello" in topic → thread_bindings → @5 (dead)
  ↓
tmux_manager.find_window_by_id("@5") → None
  ↓
Show recovery inline keyboard
```

### Recovery UI

```
⚠️ Session expired. How to proceed?

[🆕 Fresh]  [▶ Continue]  [📋 Resume]
```

| Option              | Action                          | CC Command             |
| ------------------- | ------------------------------- | ---------------------- |
| **Fresh** (default) | New session in same cwd         | `claude`               |
| **Continue**        | Most recent session in that dir | `claude --continue`    |
| **Resume**          | Pick from session history       | `claude --resume <id>` |

### Fresh Flow

1. Read `cwd` from dead session's `window_states[@5]`
2. `tmux_manager.create_window(cwd=cwd)` → new window `@15`
3. Rebind topic: `thread_bindings[user][thread] = @15`
4. Forward pending message to `@15`

### Continue Flow

1. Read `cwd` from dead session's state
2. `tmux_manager.create_window(cwd=cwd, command="claude --continue")` → `@15`
3. Rebind topic to `@15`
4. Forward pending message

### Resume (Picker) Flow

1. Scan `~/.claude/projects/` for sessions matching the dead session's cwd
2. Read `sessions-index` to get session metadata (timestamps, last message)
3. Show inline keyboard with up to 6 recent sessions:

   ```
   📋 Pick a session to resume:

   [12:30 — "Fix auth bug in login flow"]
   [Yesterday — "Add user notifications"]
   [Feb 9 — "Refactor database queries"]

   [Cancel]
   ```

4. User picks → `claude --resume <session_id>` → rebind → forward

### Explicit /resume Command

Available in any topic (even unbound):

- Lists all recent sessions across all project directories
- Grouped by cwd
- Creates new window with `claude --resume <id>`
- Binds to current topic

### Error Handling

- If `--continue` fails (no recent session): fall back to Fresh
- If `--resume <id>` fails (stale session): show error, offer Fresh/Continue
- If cwd no longer exists: show directory browser

---

## 4. Telegram UI Modernization

### 4a. Topic Status Emoji

Use `editForumTopic(icon_custom_emoji_id=...)` to reflect session state:

| State                    | Emoji | Meaning                |
| ------------------------ | ----- | ---------------------- |
| Active (Claude working)  | ⚡    | Claude is processing   |
| Idle (waiting for input) | 🟢    | Session alive, waiting |
| Dead (window gone)       | 🔴    | Session expired        |

**Requirements**: Bot must be admin with "Manage Topics" permission.

**Graceful degradation**: If bot lacks permission, skip emoji updates silently (log once at startup).

**Update triggers**:

- Status polling detects spinner → ⚡
- Status polling detects idle → 🟢
- Window detection fails → 🔴

### 4b. Sessions Dashboard

New `/sessions` command shows pinned overview in General topic:

```
📊 Sessions — macbook-pro

⚡ ccbot-project  (@3)  — "Running tests..."
🟢 api-refactor   (@7)  — Idle 5m
🔴 old-feature    (@2)  — Dead

[🔄 Refresh]  [🆕 New Session]
```

Per-session actions (tap session name → expand):

```
⚡ ccbot-project (@3)
├── CWD: /Users/alex/projects/ccbot
├── Session: abc-123...
├── Active: 2h 15m
│
[📸 Screenshot]  [Esc]  [💀 Kill]
```

**Kill confirmation**:

```
⚠️ Kill session "ccbot-project"?
This will close the tmux window and unbind all topics.

[Yes, kill it]  [Cancel]
```

### 4c. Richer Message Formatting

**Expandable blockquotes for thinking** (already using sentinel markers):

- Verify using Telegram's native `expandable_blockquote` MessageEntity
- Current `telegramify-markdown` may already support this — verify and align

**Quick actions on messages**:

| Message Type                                 | Inline Buttons                                      |
| -------------------------------------------- | --------------------------------------------------- |
| Status (spinner active)                      | `[Esc]  [📸]`                                       |
| Interactive UI (AskUser/ExitPlan/Permission) | `[↑] [↓] [←] [→] [Enter] [Esc] [📸]` (keep current) |
| Error / failure                              | `[🔄 Retry]  [📸]`                                  |
| Session expired                              | `[🆕 Fresh]  [▶ Continue]  [📋 Resume]`             |

### 4d. Status Message Enhancement

Current: status text edited into first content message.

Enhanced: include quick action buttons on status messages:

```
⏳ Running tests...
[Esc]  [📸 Screenshot]
```

When status clears (spinner stops), remove buttons from the message.

---

## 5. Implementation Plan

### Phase 1: Multi-Instance (foundation)

1. Add `CCBOT_GROUP_ID` and `CCBOT_INSTANCE_NAME` to Config
2. Add `_is_my_group()` filter to all handlers
3. Test: two instances, two groups, one bot token
4. Update docs and `.env.example`

### Phase 2: Command Overhaul

1. Implement `discover_cc_commands()` — scan skills + commands dirs
2. Rename `/start` → `/new`
3. Add `/sessions` dashboard command
4. Demote `/esc`, `/kill`, `/screenshot` to inline buttons
5. Dynamic `set_my_commands()` registration at startup
6. Update `forward_command_handler` to handle discovered commands

### Phase 3: Session Resume

1. Store `cwd` in `window_states` on session death (already stored)
2. Implement dead-window detection in `text_handler`
3. Build recovery UI (Fresh / Continue / Resume picker)
4. Implement `claude --continue` and `claude --resume` window creation
5. Implement `/resume` command with session browser
6. Add error handling and fallbacks

### Phase 4: UI Modernization

1. Topic emoji status updates (with graceful degradation)
2. `/sessions` dashboard with pinned message
3. Quick action buttons on status messages
4. Verify expandable blockquote formatting

### Deferred

- Web App / Mini App for richer UI
- Cross-instance session visibility
- Plugin/MCP discovery in command menu
- Message reactions

---

## 6. Breaking Changes

| Change                                       | Migration                                                               |
| -------------------------------------------- | ----------------------------------------------------------------------- |
| `/start` → `/new`                            | Users learn new command; old `/start` can forward to `/new` temporarily |
| `/esc` removed as command                    | Users use inline `[Esc]` button on status/screenshot messages           |
| `/kill` removed as command                   | Users use `[Kill]` in `/sessions` dashboard                             |
| `/screenshot` removed as command             | Users use `[📸]` inline button                                          |
| `CC_COMMANDS` dict removed                   | Replaced by `discover_cc_commands()` dynamic discovery                  |
| `CCBOT_GROUP_ID` required for multi-instance | Single-instance still works without it (accepts all groups)             |
