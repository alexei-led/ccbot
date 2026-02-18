"""Unit tests for CLI argument parsing and env var application."""

import os

import pytest

from ccbot.cli import _FLAG_TO_ENV, apply_args_to_env, parse_args

_ALL_ENV_VARS = ["CCBOT_LOG_LEVEL", *[env for _, env in _FLAG_TO_ENV]]


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure apply_args_to_env changes don't leak between tests."""
    saved = {var: os.environ.get(var) for var in _ALL_ENV_VARS}
    yield
    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value


class TestParseArgs:
    def test_no_args(self):
        args = parse_args([])
        assert args.version is False
        assert args.verbose is False
        assert args.log_level is None
        assert args.config_dir is None
        assert args.command is None

    def test_version_flag(self):
        args = parse_args(["--version"])
        assert args.version is True

    def test_verbose_short(self):
        args = parse_args(["-v"])
        assert args.verbose is True

    def test_verbose_long(self):
        args = parse_args(["--verbose"])
        assert args.verbose is True

    def test_log_level(self):
        args = parse_args(["--log-level", "WARNING"])
        assert args.log_level == "WARNING"

    def test_run_positional_accepted(self):
        args = parse_args(["run"])
        assert args.command == "run"

    def test_run_with_flags(self):
        args = parse_args(["run", "--tmux-session", "test"])
        assert args.command == "run"
        assert args.tmux_session == "test"

    def test_all_config_flags(self):
        args = parse_args(
            [
                "--config-dir",
                "/tmp/ccbot",
                "--allowed-users",
                "123,456",
                "--tmux-session",
                "my-session",
                "--claude-command",
                "/usr/bin/claude",
                "--monitor-interval",
                "1.5",
                "--group-id",
                "789",
                "--instance-name",
                "prod",
                "--autoclose-done",
                "60",
                "--autoclose-dead",
                "5",
            ]
        )
        assert str(args.config_dir) == "/tmp/ccbot"
        assert args.allowed_users == "123,456"
        assert args.tmux_session == "my-session"
        assert args.claude_command == "/usr/bin/claude"
        assert args.monitor_interval == 1.5
        assert args.group_id == 789
        assert args.instance_name == "prod"
        assert args.autoclose_done == 60
        assert args.autoclose_dead == 5

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["--nonexistent"], id="unknown_flag"),
            pytest.param(["start"], id="invalid_command"),
            pytest.param(["--log-level", "XYZZY"], id="invalid_log_level"),
            pytest.param(["--monitor-interval", "0"], id="zero_interval"),
            pytest.param(["--monitor-interval", "-1"], id="negative_interval"),
            pytest.param(["--autoclose-done", "-5"], id="negative_autoclose_done"),
            pytest.param(["--autoclose-dead", "-1"], id="negative_autoclose_dead"),
        ],
    )
    def test_invalid_args_raise(self, argv):
        with pytest.raises(SystemExit, match="2"):
            parse_args(argv)

    def test_autoclose_zero_accepted(self):
        args = parse_args(["--autoclose-done", "0", "--autoclose-dead", "0"])
        assert args.autoclose_done == 0
        assert args.autoclose_dead == 0


class TestApplyArgsToEnv:
    def test_verbose_sets_debug(self):
        args = parse_args(["-v"])
        apply_args_to_env(args)
        assert os.environ["CCBOT_LOG_LEVEL"] == "DEBUG"

    def test_log_level_sets_env(self):
        args = parse_args(["--log-level", "WARNING"])
        apply_args_to_env(args)
        assert os.environ["CCBOT_LOG_LEVEL"] == "WARNING"

    def test_verbose_overrides_log_level(self):
        args = parse_args(["-v", "--log-level", "ERROR"])
        apply_args_to_env(args)
        assert os.environ["CCBOT_LOG_LEVEL"] == "DEBUG"

    def test_config_dir_resolved(self, tmp_path):
        args = parse_args(["--config-dir", str(tmp_path)])
        apply_args_to_env(args)
        assert os.environ["CCBOT_DIR"] == str(tmp_path.resolve())

    def test_tmux_session(self):
        args = parse_args(["--tmux-session", "custom"])
        apply_args_to_env(args)
        assert os.environ["TMUX_SESSION_NAME"] == "custom"

    def test_group_id(self):
        args = parse_args(["--group-id", "789"])
        apply_args_to_env(args)
        assert os.environ["CCBOT_GROUP_ID"] == "789"

    def test_monitor_interval(self):
        args = parse_args(["--monitor-interval", "1.5"])
        apply_args_to_env(args)
        assert os.environ["MONITOR_POLL_INTERVAL"] == "1.5"

    def test_none_flags_dont_overwrite_env(self, monkeypatch):
        monkeypatch.setenv("TMUX_SESSION_NAME", "from-env")
        args = parse_args([])
        apply_args_to_env(args)
        assert os.environ["TMUX_SESSION_NAME"] == "from-env"

    def test_flag_overwrites_env(self, monkeypatch):
        monkeypatch.setenv("TMUX_SESSION_NAME", "from-env")
        args = parse_args(["--tmux-session", "from-flag"])
        apply_args_to_env(args)
        assert os.environ["TMUX_SESSION_NAME"] == "from-flag"

    def test_all_flag_env_mappings(self):
        args = parse_args(
            [
                "--config-dir",
                "/tmp/cc",
                "--allowed-users",
                "1,2",
                "--tmux-session",
                "s",
                "--claude-command",
                "c",
                "--monitor-interval",
                "3.0",
                "--group-id",
                "99",
                "--instance-name",
                "n",
                "--autoclose-done",
                "10",
                "--autoclose-dead",
                "5",
            ]
        )
        apply_args_to_env(args)

        assert os.environ["ALLOWED_USERS"] == "1,2"
        assert os.environ["TMUX_SESSION_NAME"] == "s"
        assert os.environ["CLAUDE_COMMAND"] == "c"
        assert os.environ["MONITOR_POLL_INTERVAL"] == "3.0"
        assert os.environ["CCBOT_GROUP_ID"] == "99"
        assert os.environ["CCBOT_INSTANCE_NAME"] == "n"
        assert os.environ["AUTOCLOSE_DONE_MINUTES"] == "10"
        assert os.environ["AUTOCLOSE_DEAD_MINUTES"] == "5"
