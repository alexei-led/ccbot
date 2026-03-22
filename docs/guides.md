# Guides

## Upgrading

```bash
uv tool upgrade ccgram                # uv (recommended)
pipx upgrade ccgram                   # pipx
brew upgrade ccgram                   # Homebrew
```

## CLI Reference

```
ccgram                        # Start the bot
ccgram status                 # Show running state (no token needed)
ccgram doctor                 # Validate setup and diagnose issues
ccgram doctor --fix           # Auto-fix issues (install hook, kill orphans)
ccgram hook --install         # Install Claude Code hooks
ccgram hook --uninstall       # Remove all hooks
ccgram hook --status          # Check per-event hook installation status
ccgram --version              # Show version
ccgram -v                     # Run with debug logging
```

## Local Dev in tmux

Recommended local development model:

- Run ccgram in a dedicated control window `ccgram:__main__`.
- Keep agent windows in the same `ccgram` tmux session.
- Restart by sending Ctrl-C to the control pane.

Use the helper script:

```bash
./scripts/restart.sh start      # fresh start; creates ccgram:__main__ if missing
./scripts/restart.sh status     # show current command + last logs
./scripts/restart.sh restart    # sends Ctrl-C to control pane (supervisor restarts)
./scripts/restart.sh stop       # sends Ctrl-\ to control pane (supervisor exits)
```

Direct key behavior in the control pane (`ccgram:__main__`):

- `Ctrl-C`: restart ccgram.
- `Ctrl-\`: stop the local dev supervisor loop.

### Fresh Start Guide

If you are starting from scratch:

1. `cd /path/to/ccgram`
2. `./scripts/restart.sh start`
3. `tmux attach -t ccgram`
4. In another terminal (or another pane), open your agent windows in the same tmux session.

The `start` command creates the tmux session/window if they do not exist, so no manual tmux bootstrap is required.

## Testing

CCGram has three test tiers:

| Tier        | Command                 | Time     | Requirements      |
| ----------- | ----------------------- | -------- | ----------------- |
| Unit        | `make test`             | ~10s     | None (all mocked) |
| Integration | `make test-integration` | ~7s      | tmux              |
| E2E         | `make test-e2e`         | ~3-4 min | tmux + agent CLIs |

`make check` runs unit + integration tests together with formatting, linting, and type checking.

### E2E Tests

End-to-end tests exercise the full lifecycle: inject fake Telegram updates → real PTB application → real tmux windows → real agent CLI processes → intercept Bot API responses. Each provider's tests are skipped automatically if its CLI is not installed.

**Prerequisites:**

- tmux installed and in PATH
- One or more agent CLIs installed and authenticated: `claude`, `codex`, `gemini`

**Test coverage per provider:**

| Provider | Tests | Scenarios                                                                                                                                                    |
| -------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Claude   | 9     | Lifecycle, `/sessions`, `/screenshot`, `/help` forwarding, recovery (fresh + continue), status transitions, multi-topic isolation, notification mode cycling |
| Codex    | 3     | Lifecycle, command forwarding, recovery                                                                                                                      |
| Gemini   | 3     | Lifecycle, command forwarding, recovery                                                                                                                      |

**How it works:** The Bot API HTTP layer is mocked — fake `Update` objects are injected via `app.process_update()` and all outgoing API calls are intercepted and recorded for assertions. The tests drive through the full topic binding flow (directory browser → provider picker → mode select → window creation) and verify agent processes launch, messages are forwarded, and responses are delivered.

**Running:**

```bash
make test-e2e                                         # All providers
uv run pytest tests/e2e/test_claude_lifecycle.py -v   # Claude only
uv run pytest tests/e2e/test_codex_lifecycle.py -v    # Codex only
uv run pytest tests/e2e/test_gemini_lifecycle.py -v   # Gemini only
```

The tests create an isolated `ccgram-e2e` tmux session that does not interfere with a running `ccgram` instance. Safe to run from a tmux window.

## Configuration

All settings accept both CLI flags and environment variables. CLI flags take precedence. `TELEGRAM_BOT_TOKEN` is env-only for security (flags are visible in `ps`).

| Variable / Flag                                  | Default              | Description                                                   |
| ------------------------------------------------ | -------------------- | ------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`                             | _(required)_         | Bot token from @BotFather (env only)                          |
| `ALLOWED_USERS` / `--allowed-users`              | _(required)_         | Comma-separated Telegram user IDs                             |
| `CCGRAM_DIR` / `--config-dir`                    | `~/.ccgram`          | Config and state directory                                    |
| `TMUX_SESSION_NAME` / `--tmux-session`           | `ccgram`             | tmux session name                                             |
| `CCGRAM_PROVIDER` / `--provider`                 | `claude`             | Default agent provider (`claude`, `codex`, `gemini`)          |
| `CCGRAM_<NAME>_COMMAND`                          | _(from provider)_    | Per-provider launch command (env only, see below)             |
| `CCGRAM_GROUP_ID` / `--group-id`                 | _(all groups)_       | Restrict to one Telegram group                                |
| `CCGRAM_INSTANCE_NAME` / `--instance-name`       | hostname             | Display label for this instance                               |
| `CCGRAM_LOG_LEVEL` / `--log-level`               | `INFO`               | Logging level (DEBUG, INFO, WARNING, ERROR)                   |
| `MONITOR_POLL_INTERVAL` / `--monitor-interval`   | `2.0`                | Seconds between transcript polls                              |
| `AUTOCLOSE_DONE_MINUTES` / `--autoclose-done`    | `30`                 | Auto-close done topics after N minutes (0=off)                |
| `AUTOCLOSE_DEAD_MINUTES` / `--autoclose-dead`    | `10`                 | Auto-close dead sessions after N minutes (0=off)              |
| `CCGRAM_WHISPER_PROVIDER` / `--whisper-provider` | _(empty)_            | Whisper provider: `openai`, `groq`, or empty to disable       |
| `CCGRAM_WHISPER_API_KEY`                         | _(empty)_            | API key (env only); falls back to OPENAI_API_KEY/GROQ_API_KEY |
| `CCGRAM_WHISPER_BASE_URL` / `--whisper-base-url` | _(provider default)_ | Custom OpenAI-compatible endpoint URL                         |
| `CCGRAM_WHISPER_MODEL` / `--whisper-model`       | _(provider default)_ | Model override (e.g., `whisper-large-v3-turbo`)               |
| `CCGRAM_WHISPER_LANGUAGE` / `--whisper-language` | _(auto-detect)_      | Force language code (e.g., `en`, `zh`)                        |
| `CCGRAM_LLM_PROVIDER`                            | _(empty = disabled)_ | LLM provider for shell command generation                     |
| `CCGRAM_LLM_API_KEY`                             | _(empty)_            | API key for LLM provider (env only)                           |
| `CCGRAM_LLM_BASE_URL`                            | _(from provider)_    | Custom LLM API endpoint                                       |
| `CCGRAM_LLM_MODEL`                               | _(from provider)_    | LLM model override                                            |
| `CCGRAM_LLM_TEMPERATURE`                         | `0.1`                | LLM sampling temperature (0 = deterministic)                  |

## Voice Message Transcription

Send voice messages in Telegram and have them transcribed and forwarded to the agent.

### Setup

Set a whisper provider and API key:

```ini
# Groq (fast, generous free tier)
CCGRAM_WHISPER_PROVIDER=groq
GROQ_API_KEY=gsk_xxxxxxxx

# Or OpenAI
CCGRAM_WHISPER_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx

# Or any OpenAI-compatible endpoint
CCGRAM_WHISPER_PROVIDER=openai
CCGRAM_WHISPER_API_KEY=your_key
CCGRAM_WHISPER_BASE_URL=http://localhost:8000/v1
```

Optional overrides:

```ini
CCGRAM_WHISPER_MODEL=whisper-large-v3-turbo   # default depends on provider
CCGRAM_WHISPER_LANGUAGE=en                     # omit for auto-detect
```

### How It Works

1. Send a voice message in a topic bound to an agent
2. Bot downloads the audio (max 25 MB) and sends it to the Whisper API
3. Transcription appears with **✓ Send to agent** and **✗ Discard** buttons
4. Tap **Send** to forward the text to the agent, or **Discard** to cancel

Leave `CCGRAM_WHISPER_PROVIDER` empty (the default) to disable voice transcription.

## Tmux Session Auto-Detection

When ccgram starts inside an existing tmux session, it auto-detects the session name and attaches to it instead of creating a new `ccgram` session. This is useful when you already have a tmux session with agent windows.

**How it works:**

1. If `$TMUX` is set and no `--tmux-session` flag is given, ccgram detects the current session name
2. The bot's own tmux window is automatically excluded from the window list
3. If another ccgram instance is already running in the same session, startup is refused

**Override:** `--tmux-session=NAME` or `TMUX_SESSION_NAME=NAME` always takes precedence over auto-detection.

**Outside tmux:** Behavior is unchanged — ccgram creates a `ccgram` session with a `__main__` placeholder window.

| Scenario                         | Behavior                                            |
| -------------------------------- | --------------------------------------------------- |
| Outside tmux, no flags           | Creates `ccgram` session + `__main__` window        |
| Outside tmux, `--tmux-session=X` | Creates/attaches `X` + `__main__` window            |
| Inside tmux, no flags            | Auto-detects session, skips own window, no creation |
| Inside tmux, `--tmux-session=X`  | Overrides auto-detect, uses `X`                     |

## Auto-Close Behavior

CCGram automatically closes Telegram topics when sessions end, reducing clutter:

- **Done topics** (`--autoclose-done`, default: 30 min) — When Claude finishes a task and the session completes normally, the topic auto-closes after 30 minutes.
- **Dead sessions** (`--autoclose-dead`, default: 10 min) — When a Claude process crashes or the tmux window is killed externally, the topic auto-closes after 10 minutes.

Set to `0` to disable:

```bash
ccgram --autoclose-done 0 --autoclose-dead 0
```

## Multi-Instance Setup

Run multiple ccgram instances on the same machine, each owning a different Telegram group. All instances can share a single bot token.

**Example: work + personal instances**

Instance 1 (`~/.ccgram-work/.env`):

```ini
TELEGRAM_BOT_TOKEN=same_token_for_both
ALLOWED_USERS=123456789
CCGRAM_GROUP_ID=-1001111111111
CCGRAM_INSTANCE_NAME=work
CCGRAM_DIR=~/.ccgram-work
TMUX_SESSION_NAME=ccgram-work
```

Instance 2 (`~/.ccgram-personal/.env`):

```ini
TELEGRAM_BOT_TOKEN=same_token_for_both
ALLOWED_USERS=123456789
CCGRAM_GROUP_ID=-1002222222222
CCGRAM_INSTANCE_NAME=personal
CCGRAM_DIR=~/.ccgram-personal
TMUX_SESSION_NAME=ccgram-personal
```

Run both:

```bash
CCGRAM_DIR=~/.ccgram-work ccgram &
CCGRAM_DIR=~/.ccgram-personal ccgram &
```

Each instance uses a separate tmux session, config directory, and state. When `CCGRAM_GROUP_ID` is set, an instance silently ignores updates from other groups.

Without `CCGRAM_GROUP_ID`, a single instance processes all groups (the default).

> To find your group's chat ID, add [@RawDataBot](https://t.me/RawDataBot) to the group — it replies with the chat ID (a negative number like `-1001234567890`).

## Creating Sessions from the Terminal

Besides creating sessions through Telegram topics, you can create tmux windows directly:

```bash
# Attach to the ccgram tmux session
tmux attach -t ccgram

# Create a new window for your project
tmux new-window -n myproject -c ~/Code/myproject

# Start any supported agent CLI
claude     # or: codex, gemini
```

The window must be in the ccgram tmux session (configurable via `TMUX_SESSION_NAME`). For Claude, the SessionStart hook registers it automatically. For Codex and Gemini, CCGram auto-detects the provider from the running process name. In both cases, the bot creates a matching Telegram topic.

This works even on a fresh instance with no existing topic bindings (cold-start).

## Session Recovery

When an agent session exits or crashes, the bot detects the dead window and offers recovery options via inline buttons:

- **Fresh** — Kill the old window, create a new one in the same directory
- **Continue** — Resume the last conversation (all providers support this)
- **Resume** — Browse and select a past session to resume from

The buttons shown adapt to each provider's capabilities. All three providers (Claude, Codex, Gemini) support Fresh, Continue, and Resume.

## Providers

CCGram supports Claude Code, Codex CLI, Gemini CLI, and Shell. Each topic can use a different provider. See **[docs/providers.md](providers.md)** for full details on each provider, session modes, custom launch commands, LLM configuration, and provider-specific behavior.

## Data Storage

All state files live in `$CCGRAM_DIR` (`~/.ccgram/` by default):

| File                 | Description                                                 |
| -------------------- | ----------------------------------------------------------- |
| `state.json`         | Thread bindings, window states, display names, read offsets |
| `session_map.json`   | Hook-generated window → session mappings                    |
| `events.jsonl`       | Append-only hook event log (read incrementally by monitor)  |
| `monitor_state.json` | Byte offsets per session (prevents duplicate notifications) |

Session transcripts are read from provider-specific locations (read-only): `~/.claude/projects/` (Claude), `~/.codex/sessions/` (Codex), `~/.gemini/tmp/` (Gemini). The bot never writes to agent data directories.

## Running as a Service

For persistent operation, run ccgram as a systemd service or under a process manager:

```bash
# systemd user service (~/.config/systemd/user/ccgram.service)
[Unit]
Description=CCGram - Command & Control Bot for AI coding agents
After=network.target

[Service]
ExecStart=%h/.local/bin/ccgram
Restart=on-failure
RestartSec=5
Environment=CCGRAM_DIR=%h/.ccgram

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable ccgram
systemctl --user start ccgram
```

On macOS, you can use a launchd plist or simply run in a detached tmux session:

```bash
tmux new-session -d -s ccgram-daemon 'ccgram'
```
