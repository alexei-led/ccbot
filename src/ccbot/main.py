"""Application entry point — Click CLI dispatcher and bot bootstrap.

The ``main()`` function invokes the Click command group defined in cli.py,
which dispatches to subcommands (run, hook, status, doctor).
``run_bot()`` contains the actual bot startup logic, called by the ``run``
command after CLI flags have been applied to the environment.
"""

import logging
import os
import sys

import structlog

# Set by the upgrade handler to trigger os.execv() after run_polling() returns
_restart_requested = False


def _short_name_processor(
    _logger: structlog.types.WrappedLogger,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Strip 'ccbot.' and 'handlers.' prefixes, cap at 20 chars."""
    name = event_dict.get("_record", {}).get("name", "")
    if not name:
        name = event_dict.get("logger_name", "")
    if name.startswith("ccbot.handlers."):
        name = name[len("ccbot.handlers.") :]
    elif name.startswith("ccbot."):
        name = name[len("ccbot.") :]
    event_dict["short_name"] = name[:20]
    return event_dict


def setup_logging(log_level: str) -> None:
    """Configure structured, colored logging for interactive CLI use."""
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _short_name_processor,
            structlog.dev.ConsoleRenderer(
                colors=True,
                pad_event=40,
            ),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging for third-party libs
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            ],
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    logging.getLogger("ccbot").setLevel(numeric_level)
    for name in ("httpx", "httpcore", "telegram.ext"):
        logging.getLogger(name).setLevel(logging.WARNING)


def run_bot() -> None:
    """Start the bot. Called by the ``run`` Click command after env is set."""
    log_level = os.environ.get("CCBOT_LOG_LEVEL", "INFO").upper()
    setup_logging(log_level)

    try:
        from .config import config
    except ValueError as e:
        from .utils import ccbot_dir

        config_dir = ccbot_dir()
        env_path = config_dir / ".env"
        print(f"Error: {e}\n")
        print(f"Create {env_path} with the following content:\n")
        print("  TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("  ALLOWED_USERS=your_telegram_user_id")
        print()
        print("Get your bot token from @BotFather on Telegram.")
        print("Get your user ID from @userinfobot on Telegram.")
        sys.exit(1)

    logger = structlog.get_logger()

    from .tmux_manager import tmux_manager

    logger.info("Allowed users: %s", config.allowed_users)
    logger.info("Claude projects path: %s", config.claude_projects_path)

    session = tmux_manager.get_or_create_session()
    logger.info("Tmux session '%s' ready", session.session_name)

    logger.info("Starting Telegram bot...")
    from .bot import create_bot

    application = create_bot()
    application.run_polling(allowed_updates=["message", "callback_query"])

    if _restart_requested:
        logger.info("Restarting bot via os.execv(%s)", sys.argv)
        os.execv(sys.argv[0], sys.argv)


def main() -> None:
    """Main entry point — dispatches via Click CLI group."""
    from .cli import cli

    cli()


if __name__ == "__main__":
    main()
