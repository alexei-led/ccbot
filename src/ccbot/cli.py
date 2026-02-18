"""Command-line argument parsing for ccbot.

Defines CLI flags and applies precedence: CLI flag > env var > .env > default.
Called by main.py before Config instantiation; sets os.environ for any
explicitly provided flags so Config reads the overridden values.
"""

import argparse
import os
from pathlib import Path

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _positive_float(value: str) -> float:
    """Argparse type for positive floats."""
    result = float(value)
    if result <= 0:
        msg = f"must be positive, got {value}"
        raise argparse.ArgumentTypeError(msg)
    return result


def _non_negative_int(value: str) -> int:
    """Argparse type for non-negative integers."""
    result = int(value)
    if result < 0:
        msg = f"must be non-negative, got {value}"
        raise argparse.ArgumentTypeError(msg)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments and return namespace.

    Args:
        argv: Argument list (defaults to sys.argv[1:]). Pass explicitly for testing.
    """
    parser = argparse.ArgumentParser(
        prog="ccbot",
        description="Telegram bot bridging Telegram topics to Claude Code sessions via tmux",
    )

    parser.add_argument(
        "--version",
        action="store_true",
        help="show version and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging (env: CCBOT_LOG_LEVEL=DEBUG)",
    )
    parser.add_argument(
        "--log-level",
        choices=_LOG_LEVELS,
        metavar="LEVEL",
        help="logging level: DEBUG, INFO, WARNING, ERROR (env: CCBOT_LOG_LEVEL)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        metavar="DIR",
        help="config directory (default: ~/.ccbot, env: CCBOT_DIR)",
    )
    parser.add_argument(
        "--allowed-users",
        metavar="ID[,ID...]",
        help="comma-separated Telegram user IDs (env: ALLOWED_USERS)",
    )
    parser.add_argument(
        "--tmux-session",
        metavar="NAME",
        help="tmux session name (default: ccbot, env: TMUX_SESSION_NAME)",
    )
    parser.add_argument(
        "--claude-command",
        metavar="CMD",
        help="claude command to run (default: claude, env: CLAUDE_COMMAND)",
    )
    parser.add_argument(
        "--monitor-interval",
        type=_positive_float,
        metavar="SEC",
        help="session monitor poll interval in seconds (default: 2.0, env: MONITOR_POLL_INTERVAL)",
    )
    parser.add_argument(
        "--group-id",
        type=int,
        metavar="ID",
        help="restrict to one Telegram group (env: CCBOT_GROUP_ID)",
    )
    parser.add_argument(
        "--instance-name",
        metavar="NAME",
        help="display label for multi-instance (default: hostname, env: CCBOT_INSTANCE_NAME)",
    )
    parser.add_argument(
        "--autoclose-done",
        type=_non_negative_int,
        metavar="MIN",
        help="auto-close done topics after N minutes, 0=disabled (default: 30, env: AUTOCLOSE_DONE_MINUTES)",
    )
    parser.add_argument(
        "--autoclose-dead",
        type=_non_negative_int,
        metavar="MIN",
        help="auto-close dead sessions after N minutes, 0=disabled (default: 10, env: AUTOCLOSE_DEAD_MINUTES)",
    )

    # Optional "run" positional — accepted and ignored for explicitness
    parser.add_argument(
        "command",
        nargs="?",
        choices=["run"],
        help=argparse.SUPPRESS,
    )

    return parser.parse_args(argv)


# Mapping: argparse dest → environment variable name
_FLAG_TO_ENV: list[tuple[str, str]] = [
    ("config_dir", "CCBOT_DIR"),
    ("allowed_users", "ALLOWED_USERS"),
    ("tmux_session", "TMUX_SESSION_NAME"),
    ("claude_command", "CLAUDE_COMMAND"),
    ("monitor_interval", "MONITOR_POLL_INTERVAL"),
    ("group_id", "CCBOT_GROUP_ID"),
    ("instance_name", "CCBOT_INSTANCE_NAME"),
    ("autoclose_done", "AUTOCLOSE_DONE_MINUTES"),
    ("autoclose_dead", "AUTOCLOSE_DEAD_MINUTES"),
]


def apply_args_to_env(args: argparse.Namespace) -> None:
    """Set environment variables from explicitly provided CLI flags.

    Call BEFORE Config instantiation to ensure CLI flags take precedence.
    Only sets env vars for flags that were explicitly provided (not None).
    """
    # --verbose always wins over --log-level
    if args.verbose:
        os.environ["CCBOT_LOG_LEVEL"] = "DEBUG"
    elif args.log_level is not None:
        os.environ["CCBOT_LOG_LEVEL"] = args.log_level.upper()

    for attr, env_var in _FLAG_TO_ENV:
        value = getattr(args, attr)
        if value is None:
            continue
        if isinstance(value, Path):
            os.environ[env_var] = str(value.expanduser().resolve())
        else:
            os.environ[env_var] = str(value)
