"""Application entry point — Click CLI dispatcher and bot bootstrap.

The ``main()`` function invokes the Click command group defined in cli.py,
which dispatches to subcommands (run, hook, status, doctor).
``run_bot()`` contains the actual bot startup logic, called by the ``run``
command after CLI flags have been applied to the environment.
"""

import logging
import os
import signal
import sys
from types import FrameType
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from aiohttp import web

# Set by the upgrade handler to trigger os.execv() after run_polling() returns
_restart_requested = False

# Tracks which signal triggered shutdown (0 = none/clean exit)
_shutdown_signal = 0

# Mini App server runner — populated when CCGRAM_MINIAPP_BASE_URL is set.
_miniapp_runner: "web.AppRunner | None" = None


def _install_signal_handlers() -> None:
    """Install signal handlers that record the signal and trigger PTB shutdown.

    PTB's default signal handling catches SIGINT/SIGTERM/SIGABRT and exits
    with code 0 after graceful shutdown.  The restart.sh supervisor needs the
    real signal exit code (130 for SIGINT=restart, 131 for SIGQUIT=stop), so
    we install our own handlers and tell PTB not to override them via
    ``stop_signals=None``.
    """

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        global _shutdown_signal
        _shutdown_signal = signum
        sig_name = signal.Signals(signum).name
        sys.stderr.write(f"\n[ccgram] {sig_name} received (pid={os.getpid()})\n")
        sys.stderr.flush()
        raise SystemExit

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGQUIT, _on_signal)


def _reraise_shutdown_signal() -> None:
    """Re-raise the original signal with default disposition.

    This makes the process exit with the correct code (128 + signum) so the
    parent (restart.sh) can distinguish restart from stop.
    """
    if _shutdown_signal:
        signal.signal(_shutdown_signal, signal.SIG_DFL)
        os.kill(os.getpid(), _shutdown_signal)


def setup_logging(log_level: str) -> None:
    """Configure structured, colored logging for interactive CLI use."""
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
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

    logging.getLogger("ccgram").setLevel(numeric_level)
    for name in ("httpx", "httpcore", "telegram.ext"):
        logging.getLogger(name).setLevel(logging.WARNING)


def run_bot() -> None:
    """Start the bot. Called by the ``run`` Click command after env is set."""
    log_level = (
        os.environ.get("CCGRAM_LOG_LEVEL")
        or os.environ.get("CCBOT_LOG_LEVEL")
        or "INFO"
    ).upper()
    setup_logging(log_level)

    # --- Auto-detect tmux session (before config import) ---
    explicit_session = os.environ.get("TMUX_SESSION_NAME")
    auto_detected = False

    if not explicit_session and os.environ.get("TMUX"):
        from .utils import check_duplicate_ccgram, detect_tmux_context

        detected, own_wid = detect_tmux_context()
        if detected:
            os.environ["TMUX_SESSION_NAME"] = detected
            auto_detected = True

        dup = check_duplicate_ccgram(detected or "ccgram")
        if dup:
            print(f"Error: {dup}", file=sys.stderr)
            sys.exit(1)
    else:
        own_wid = None

    try:
        from .config import config
    except ValueError as e:
        from .utils import ccgram_dir

        config_dir = ccgram_dir()
        env_path = config_dir / ".env"
        print(f"Error: {e}\n")
        print(f"Create {env_path} with the following content:\n")
        print("  TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("  ALLOWED_USERS=your_telegram_user_id")
        print()
        print("Get your bot token from @BotFather on Telegram.")
        print("Get your user ID from @userinfobot on Telegram.")
        sys.exit(1)

    if own_wid:
        config.own_window_id = own_wid

    logger = structlog.get_logger()

    from .tmux_manager import tmux_manager

    logger.info("Allowed users: %s", config.allowed_users)
    logger.info("Claude projects path: %s", config.claude_projects_path)

    # In auto-detect mode, session must already exist
    if auto_detected:
        session = tmux_manager.get_session()
        if not session:
            logger.error("Tmux session '%s' not found", config.tmux_session_name)
            sys.exit(1)
        logger.info("Auto-detected tmux session '%s'", session.session_name)
    else:
        session = tmux_manager.get_or_create_session()

    logger.info("Tmux session '%s' ready", session.session_name)

    from . import __version__

    dev = "+dev" if "+unknown" in __version__ or ".dev" in __version__ else ""
    logger.info("Starting ccgram %s%s", __version__, dev)
    from .bot import create_bot

    application = create_bot()
    _install_signal_handlers()
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        stop_signals=None,
    )

    if _restart_requested:
        logger.info("Restarting bot via os.execv(%s)", sys.argv)
        os.execv(sys.argv[0], sys.argv)

    _reraise_shutdown_signal()


async def start_miniapp_if_enabled() -> None:
    """Start the Mini App HTTP server when ``CCGRAM_MINIAPP_BASE_URL`` is set.

    Idempotent: a second call when already running is a no-op. Failures are
    logged and swallowed — the bot must keep running even if the optional
    server can't bind.
    """
    global _miniapp_runner

    if _miniapp_runner is not None:
        return

    from .config import config

    if not config.miniapp_base_url:
        return

    logger = structlog.get_logger()
    try:
        from .miniapp import start_server

        _miniapp_runner = await start_server(
            bot_token=config.telegram_bot_token,
            host=config.miniapp_host,
            port=config.miniapp_port,
        )
        logger.info(
            "Mini App server started: base_url=%s host=%s port=%d",
            config.miniapp_base_url,
            config.miniapp_host,
            config.miniapp_port,
        )
    except OSError as exc:
        logger.error("Mini App server failed to bind: %s", exc)
        _miniapp_runner = None


async def stop_miniapp_if_enabled() -> None:
    """Stop the Mini App server if it was started; otherwise no-op."""
    global _miniapp_runner

    if _miniapp_runner is None:
        return

    logger = structlog.get_logger()
    try:
        from .miniapp import stop_server

        await stop_server(_miniapp_runner)
    except OSError as exc:
        logger.warning("Mini App server stop raised: %s", exc)
    finally:
        _miniapp_runner = None


def main() -> None:
    """Main entry point — dispatches via Click CLI group."""
    from .cli import cli

    cli()


if __name__ == "__main__":
    main()
