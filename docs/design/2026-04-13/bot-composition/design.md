# Bot Composition Root

## Functional Responsibilities

Wires the PTB `Application`, registers handlers, starts background tasks, runs the main loop, and handles graceful shutdown. Should contain no business logic — every command handler, callback handler, and message handler is implemented in its own module and registered here.

Files:

- **`bot.py`** (~620 lines) — `create_bot()` builds the `Application`; `post_init` / `post_stop` / `post_shutdown` lifecycle hooks; `new_command` / `history_command` / `commands_command` / `toolbar_command` / `verbose_command` / `inline_query_handler` / `unsupported_content_handler` / `text_handler` thin wrappers; global exception handler; error handler. After the Apr 12 refactor, business logic for `handle_new_message`, topic lifecycle, screenshot command, and recall command is now delegated to `message_routing.py`, `topic_lifecycle.py`, `screenshot_callbacks.py`, and `command_history.py` respectively.
- **`main.py`** — Click dispatcher, `run_bot` bootstrap (loads config, instantiates session manager, starts hooks check, runs the application).
- **`cli.py`** — Click command definitions (`run`, `doctor`, `status`, `msg`, `hook`, `upgrade`).
- **`config.py`** — `Config` singleton; env var + .env + CLI flag precedence chain.

## Encapsulated Knowledge

- **PTB wiring order** — only `create_bot` knows the right order to register handlers, set up rate limiter, attach callback handlers, add command handlers. Order matters because PTB matches on first filter hit.
- **CLI flag → config field mapping** — `cli.py` owns the argument list; `config.py` owns the resolution chain.
- **Startup invariants** — `post_init` knows the right order to: resolve stale IDs → prune stale state → load session map → start session monitor → start polling loop → check hooks installed → send startup notification. Changing this order breaks session recovery.
- **Shutdown flow** — `post_stop` sends the shutdown notification while HTTP transport is still alive; `post_shutdown` flushes state and cancels background tasks.

## Subdomain Classification

**Supporting.** Composition wiring rarely changes — new handlers are added, but the patterns of registration are stable. The business logic extraction in Apr 12 already moved the bulk of volatile code out of `bot.py`.

## Integration Contracts

### Inbound

- User runs `ccgram run` → `cli.run` → `main.run_bot(config)` → `create_bot()` → PTB `application.run_polling()`.

### Outbound

| To                                                                           | Kind               | Contract                                                                             |
| ---------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------ |
| All handler modules                                                          | Contract (imports) | `create_bot()` imports each module, calls `load_handlers()` on the callback registry |
| `session_manager.resolve_stale_ids()`, `load_session_map()`, `flush_state()` | Contract           | Startup / shutdown                                                                   |
| `session_monitor.start()`, `stop()`                                          | Contract           | Background task lifecycle                                                            |
| `polling_coordinator.status_poll_loop(bot)`                                  | Contract           | Background task                                                                      |
| `periodic_tasks.run_periodic_tasks(bot)`                                     | Contract           | Per-tick driver                                                                      |
| `topic_orchestration.check_hooks_installed()`                                | Contract           | Startup warning                                                                      |
| `message_queue.shutdown_workers()`                                           | Contract           | Graceful stop                                                                        |

## Change Vectors

- **Add a new command** — add a registration line in `create_bot`; handler lives elsewhere.
- **Add a new startup task** — add to `post_init`; decide placement relative to existing order.
- **Change rate limiter settings** — `create_bot` only.
- **New global exception type** — `_global_exception_handler` + `_error_handler`.
- **Add a new CLI subcommand** — `cli.py` Click group.

## Testability Goals

- **Unit-test individual command wrappers** in `bot.py` with a mocked `Update` and mocked delegates.
- **Integration-test `create_bot()`** — instantiate, verify handler registration count, verify no exceptions.
- **Unit-test `_global_exception_handler`** — verify it swallows specific exception types without crashing the loop.
- **Unit-test config precedence** — CLI flag > env var > .env > default, for each field.
