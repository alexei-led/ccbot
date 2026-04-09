import socket
from pathlib import Path

import pytest

from ccgram.config import Config


@pytest.fixture
def _base_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token")
    monkeypatch.setenv("ALLOWED_USERS", "12345")
    monkeypatch.setenv("CCGRAM_DIR", str(tmp_path))


@pytest.mark.usefixtures("_base_env")
class TestConfigValid:
    def test_valid_config(self):
        cfg = Config()
        assert cfg.telegram_bot_token == "test:token"
        assert cfg.allowed_users == {12345}

    def test_custom_tmux_session_name(self, monkeypatch):
        monkeypatch.setenv("TMUX_SESSION_NAME", "mysession")
        cfg = Config()
        assert cfg.tmux_session_name == "mysession"

    def test_custom_monitor_poll_interval(self, monkeypatch):
        monkeypatch.setenv("MONITOR_POLL_INTERVAL", "5.0")
        cfg = Config()
        assert cfg.monitor_poll_interval == 5.0

    def test_is_user_allowed_true(self):
        cfg = Config()
        assert cfg.is_user_allowed(12345) is True

    def test_is_user_allowed_false(self):
        cfg = Config()
        assert cfg.is_user_allowed(99999) is False

    def test_group_id_default_none(self):
        cfg = Config()
        assert cfg.group_id is None

    def test_group_id_parsed_as_int(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_GROUP_ID", "-1001234567890")
        cfg = Config()
        assert cfg.group_id == -1001234567890

    def test_instance_name_defaults_to_hostname(self):
        cfg = Config()
        assert cfg.instance_name == socket.gethostname()

    def test_instance_name_from_env(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_INSTANCE_NAME", "bot-1")
        cfg = Config()
        assert cfg.instance_name == "bot-1"


@pytest.mark.usefixtures("_base_env")
class TestOwnWindowId:
    def test_own_window_id_default_none(self):
        cfg = Config()
        assert cfg.own_window_id is None

    def test_own_window_id_set_directly(self):
        cfg = Config()
        cfg.own_window_id = "@3"
        assert cfg.own_window_id == "@3"


@pytest.mark.usefixtures("_base_env")
class TestConfigMissingEnv:
    def test_missing_telegram_bot_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            Config()

    def test_missing_allowed_users(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_USERS", raising=False)
        with pytest.raises(ValueError, match="ALLOWED_USERS"):
            Config()

    def test_non_numeric_allowed_users(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", "abc")
        with pytest.raises(ValueError, match="non-numeric"):
            Config()

    def test_non_numeric_group_id(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_GROUP_ID", "not-a-number")
        with pytest.raises(ValueError, match="CCGRAM_GROUP_ID must be a valid integer"):
            Config()


@pytest.mark.usefixtures("_base_env")
class TestClaudeConfigDir:
    def test_claude_config_dir_default(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        cfg = Config()
        assert cfg.claude_config_dir == Path.home() / ".claude"
        assert cfg.claude_projects_path == Path.home() / ".claude" / "projects"

    def test_claude_config_dir_override(self, monkeypatch, tmp_path):
        custom_dir = tmp_path / "custom-claude"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom_dir))
        cfg = Config()
        assert cfg.claude_config_dir == custom_dir
        assert cfg.claude_projects_path == custom_dir / "projects"


@pytest.mark.usefixtures("_base_env")
class TestShowHiddenDirs:
    def test_show_hidden_dirs_default_false(self):
        cfg = Config()
        assert cfg.show_hidden_dirs is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "True", "YES"])
    def test_show_hidden_dirs_enabled(self, monkeypatch, value):
        monkeypatch.setenv("CCGRAM_SHOW_HIDDEN_DIRS", value)
        cfg = Config()
        assert cfg.show_hidden_dirs is True


@pytest.mark.usefixtures("_base_env")
class TestMessagingConfig:
    def test_msg_auto_spawn_default_false(self):
        cfg = Config()
        assert cfg.msg_auto_spawn is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "True"])
    def test_msg_auto_spawn_enabled(self, monkeypatch, value):
        monkeypatch.setenv("CCGRAM_MSG_AUTO_SPAWN", value)
        cfg = Config()
        assert cfg.msg_auto_spawn is True

    def test_msg_max_windows_default(self):
        cfg = Config()
        assert cfg.msg_max_windows == 10

    def test_msg_max_windows_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_MSG_MAX_WINDOWS", "20")
        cfg = Config()
        assert cfg.msg_max_windows == 20

    def test_msg_wait_timeout_default(self):
        cfg = Config()
        assert cfg.msg_wait_timeout == 60

    def test_msg_wait_timeout_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_MSG_WAIT_TIMEOUT", "120")
        cfg = Config()
        assert cfg.msg_wait_timeout == 120

    def test_msg_spawn_timeout_default(self):
        cfg = Config()
        assert cfg.msg_spawn_timeout == 300

    def test_msg_spawn_timeout_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_MSG_SPAWN_TIMEOUT", "600")
        cfg = Config()
        assert cfg.msg_spawn_timeout == 600

    def test_msg_spawn_rate_default(self):
        cfg = Config()
        assert cfg.msg_spawn_rate == 3

    def test_msg_spawn_rate_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_MSG_SPAWN_RATE", "5")
        cfg = Config()
        assert cfg.msg_spawn_rate == 5

    def test_msg_rate_limit_default(self):
        cfg = Config()
        assert cfg.msg_rate_limit == 10

    def test_msg_rate_limit_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_MSG_RATE_LIMIT", "25")
        cfg = Config()
        assert cfg.msg_rate_limit == 25

    def test_mailbox_dir_derived_from_config_dir(self, tmp_path):
        cfg = Config()
        assert cfg.mailbox_dir == tmp_path / "mailbox"


@pytest.mark.usefixtures("_base_env")
class TestLiveViewConfig:
    def test_live_view_interval_default(self):
        cfg = Config()
        assert cfg.live_view_interval == 5

    def test_live_view_interval_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_INTERVAL", "10")
        cfg = Config()
        assert cfg.live_view_interval == 10

    def test_live_view_timeout_default(self):
        cfg = Config()
        assert cfg.live_view_timeout == 300

    def test_live_view_timeout_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_TIMEOUT", "600")
        cfg = Config()
        assert cfg.live_view_timeout == 600

    def test_live_view_interval_zero_clamped_to_one(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_INTERVAL", "0")
        cfg = Config()
        assert cfg.live_view_interval == 1

    def test_live_view_timeout_zero_clamped_to_one(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_TIMEOUT", "0")
        cfg = Config()
        assert cfg.live_view_timeout == 1

    def test_live_view_interval_invalid(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_INTERVAL", "not-a-number")
        with pytest.raises(ValueError, match="CCGRAM_LIVE_VIEW_INTERVAL"):
            Config()

    def test_live_view_timeout_invalid(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_LIVE_VIEW_TIMEOUT", "not-a-number")
        with pytest.raises(ValueError, match="CCGRAM_LIVE_VIEW_TIMEOUT"):
            Config()


@pytest.mark.usefixtures("_base_env")
class TestPollingConfig:
    def test_monitor_poll_interval_default(self):
        cfg = Config()
        assert cfg.monitor_poll_interval == 1.0

    def test_monitor_poll_interval_override(self, monkeypatch):
        monkeypatch.setenv("MONITOR_POLL_INTERVAL", "0.8")
        cfg = Config()
        assert cfg.monitor_poll_interval == 0.8

    def test_monitor_poll_interval_clamped_to_min(self, monkeypatch):
        monkeypatch.setenv("MONITOR_POLL_INTERVAL", "0.1")
        cfg = Config()
        assert cfg.monitor_poll_interval == 0.5

    def test_status_poll_interval_default(self):
        cfg = Config()
        assert cfg.status_poll_interval == 1.0

    def test_status_poll_interval_override(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_STATUS_POLL_INTERVAL", "2.0")
        cfg = Config()
        assert cfg.status_poll_interval == 2.0

    def test_status_poll_interval_clamped_to_min(self, monkeypatch):
        monkeypatch.setenv("CCGRAM_STATUS_POLL_INTERVAL", "0.2")
        cfg = Config()
        assert cfg.status_poll_interval == 0.5
