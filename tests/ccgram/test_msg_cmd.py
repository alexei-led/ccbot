import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ccgram.cli import cli
from ccgram.mailbox import Mailbox
from ccgram.msg_discovery import register_declared


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def mailbox_dir(tmp_path: Path) -> Path:
    d = tmp_path / "mailbox"
    d.mkdir()
    return d


@pytest.fixture()
def mailbox(mailbox_dir: Path) -> Mailbox:
    return Mailbox(mailbox_dir)


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ccgram"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _patch_dirs(state_dir: Path, mailbox_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("ccgram.msg_cmd.ccgram_dir", lambda: state_dir)
    monkeypatch.setattr("ccgram.msg_cmd._get_mailbox_dir", lambda: mailbox_dir)
    monkeypatch.setattr("ccgram.spawn_request.ccgram_dir", lambda: state_dir)
    monkeypatch.setattr("ccgram.msg_discovery.ccgram_dir", lambda: state_dir)
    monkeypatch.setenv("CCGRAM_WINDOW_ID", "ccgram:@0")


def _write_state(state_dir: Path, window_states: dict) -> None:
    data = {"window_states": window_states}
    (state_dir / "state.json").write_text(json.dumps(data))


class TestMsgHelp:
    def test_msg_help_shows_subcommands(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "--help"])
        assert result.exit_code == 0
        assert "list-peers" in result.output
        assert "find" in result.output
        assert "send" in result.output
        assert "inbox" in result.output
        assert "read" in result.output
        assert "reply" in result.output
        assert "broadcast" in result.output
        assert "register" in result.output
        assert "sweep" in result.output

    def test_msg_appears_in_main_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "msg" in result.output

    def test_list_peers_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "list-peers", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    def test_send_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "send", "--help"])
        assert result.exit_code == 0
        assert "--notify" in result.output
        assert "--wait" in result.output
        assert "--ttl" in result.output

    def test_find_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "find", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.output
        assert "--team" in result.output
        assert "--cwd" in result.output


class TestListPeers:
    def test_empty_state(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "list-peers"])
        assert result.exit_code == 0
        assert "No peers found" in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_table_output(self, _mock_branch, runner: CliRunner, state_dir: Path):
        _write_state(
            state_dir,
            {
                "@0": {
                    "cwd": "/proj",
                    "window_name": "proj",
                    "provider_name": "claude",
                },
            },
        )
        result = runner.invoke(cli, ["msg", "list-peers"])
        assert result.exit_code == 0
        assert "ccgram:@0" in result.output
        assert "claude" in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_json_output(self, _mock_branch, runner: CliRunner, state_dir: Path):
        _write_state(
            state_dir,
            {
                "@0": {
                    "cwd": "/proj",
                    "window_name": "proj",
                    "provider_name": "claude",
                },
            },
        )
        result = runner.invoke(cli, ["msg", "list-peers", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["window_id"] == "ccgram:@0"


class TestFind:
    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_filter_by_provider(self, _mock_branch, runner: CliRunner, state_dir: Path):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "codex"},
            },
        )
        result = runner.invoke(cli, ["msg", "find", "--provider", "claude"])
        assert result.exit_code == 0
        assert "ccgram:@0" in result.output
        assert "ccgram:@5" not in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_filter_by_team(
        self, _mock_branch, runner: CliRunner, state_dir: Path, mailbox_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "claude"},
            },
        )
        register_declared(
            "ccgram:@0", team="backend", path=mailbox_dir / "declared.json"
        )
        result = runner.invoke(cli, ["msg", "find", "--team", "backend"])
        assert result.exit_code == 0
        assert "ccgram:@0" in result.output
        assert "ccgram:@5" not in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_filter_by_cwd(self, _mock_branch, runner: CliRunner, state_dir: Path):
        _write_state(
            state_dir,
            {
                "@0": {
                    "cwd": "/home/user/proj-a",
                    "window_name": "a",
                    "provider_name": "claude",
                },
                "@5": {
                    "cwd": "/home/user/proj-b",
                    "window_name": "b",
                    "provider_name": "claude",
                },
            },
        )
        result = runner.invoke(cli, ["msg", "find", "--cwd", "*proj-a*"])
        assert result.exit_code == 0
        assert "ccgram:@0" in result.output
        assert "ccgram:@5" not in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_json_output(self, _mock_branch, runner: CliRunner, state_dir: Path):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
            },
        )
        result = runner.invoke(cli, ["msg", "find", "--provider", "claude", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1


class TestSend:
    def test_basic_send(self, runner: CliRunner, mailbox: Mailbox):
        result = runner.invoke(cli, ["msg", "send", "ccgram:@5", "hello"])
        assert result.exit_code == 0
        assert "Sent" in result.output
        messages = mailbox.inbox("ccgram:@5")
        assert len(messages) == 1
        assert messages[0].body == "hello"
        assert messages[0].from_id == "ccgram:@0"
        assert messages[0].type == "request"

    def test_send_notify(self, runner: CliRunner, mailbox: Mailbox):
        result = runner.invoke(cli, ["msg", "send", "ccgram:@5", "info", "--notify"])
        assert result.exit_code == 0
        messages = mailbox.inbox("ccgram:@5")
        assert messages[0].type == "notify"

    def test_send_with_ttl(self, runner: CliRunner, mailbox: Mailbox):
        result = runner.invoke(
            cli, ["msg", "send", "ccgram:@5", "urgent", "--ttl", "5"]
        )
        assert result.exit_code == 0
        messages = mailbox.inbox("ccgram:@5")
        assert messages[0].ttl_minutes == 5

    def test_send_with_subject(self, runner: CliRunner, mailbox: Mailbox):
        result = runner.invoke(
            cli, ["msg", "send", "ccgram:@5", "body", "-s", "API query"]
        )
        assert result.exit_code == 0
        messages = mailbox.inbox("ccgram:@5")
        assert messages[0].subject == "API query"

    def test_send_with_file(self, runner: CliRunner, mailbox: Mailbox, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("file content")
        result = runner.invoke(
            cli, ["msg", "send", "ccgram:@5", "see file", "--file", str(f)]
        )
        assert result.exit_code == 0
        messages = mailbox.inbox("ccgram:@5")
        assert messages[0].file_path == str(f)

    def test_send_rate_limit(
        self, runner: CliRunner, mailbox: Mailbox, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CCGRAM_MSG_RATE_LIMIT", "2")
        runner.invoke(cli, ["msg", "send", "ccgram:@5", "msg1"])
        runner.invoke(cli, ["msg", "send", "ccgram:@5", "msg2"])
        result = runner.invoke(cli, ["msg", "send", "ccgram:@5", "msg3"])
        assert result.exit_code != 0
        assert "rate limit" in result.output

    def test_send_wait_timeout(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("CCGRAM_MSG_WAIT_TIMEOUT", "1")
        result = runner.invoke(cli, ["msg", "send", "ccgram:@5", "question", "--wait"])
        assert result.exit_code != 0
        assert "timeout" in result.output

    def test_send_wait_deadlock_prevention(
        self, runner: CliRunner, mailbox_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        wait_file = mailbox_dir / ".waiting-ccgram-@0"
        wait_file.write_text("some-msg-id")
        result = runner.invoke(cli, ["msg", "send", "ccgram:@5", "question", "--wait"])
        assert result.exit_code != 0
        assert "already waiting" in result.output


class TestInbox:
    def test_empty_inbox(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code == 0
        assert "Inbox empty" in result.output

    def test_inbox_shows_messages(self, runner: CliRunner, mailbox: Mailbox):
        mailbox.send(
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            body="hello",
            msg_type="request",
            subject="test",
        )
        result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code == 0
        assert "ccgram:@5" in result.output
        assert "request" in result.output

    def test_inbox_json(self, runner: CliRunner, mailbox: Mailbox):
        mailbox.send(
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            body="hello",
            msg_type="request",
            subject="test",
        )
        result = runner.invoke(cli, ["msg", "inbox", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["from_id"] == "ccgram:@5"


class TestRead:
    def test_read_message(self, runner: CliRunner, mailbox: Mailbox):
        msg = mailbox.send(
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            body="important info",
            msg_type="request",
            subject="API",
        )
        result = runner.invoke(cli, ["msg", "read", msg.id])
        assert result.exit_code == 0
        assert "From: ccgram:@5" in result.output
        assert "Subject: API" in result.output
        assert "Body: important info" in result.output

    def test_read_unknown_message(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "read", "nonexistent-id"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestReply:
    def test_reply_to_message(self, runner: CliRunner, mailbox: Mailbox):
        msg = mailbox.send(
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            body="question?",
            msg_type="request",
        )
        mailbox.read(msg.id, "ccgram:@0")
        result = runner.invoke(cli, ["msg", "reply", msg.id, "answer!"])
        assert result.exit_code == 0
        assert "Replied" in result.output
        replies = mailbox.inbox("ccgram:@5")
        assert len(replies) == 1
        assert replies[0].body == "answer!"
        assert replies[0].reply_to == msg.id

    def test_reply_unknown_message(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "reply", "nonexistent", "body"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestBroadcast:
    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_to_all(
        self, _mock_branch, runner: CliRunner, mailbox: Mailbox, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "claude"},
                "@8": {"cwd": "/c", "window_name": "c", "provider_name": "gemini"},
            },
        )
        result = runner.invoke(cli, ["msg", "broadcast", "all hands"])
        assert result.exit_code == 0
        assert "2 recipient" in result.output
        assert len(mailbox.inbox("ccgram:@5")) == 1
        assert len(mailbox.inbox("ccgram:@8")) == 1
        assert len(mailbox.inbox("ccgram:@0")) == 0

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_filtered_by_team(
        self,
        _mock_branch,
        runner: CliRunner,
        mailbox: Mailbox,
        state_dir: Path,
        mailbox_dir: Path,
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "claude"},
                "@8": {"cwd": "/c", "window_name": "c", "provider_name": "claude"},
            },
        )
        register_declared(
            "ccgram:@5", team="backend", path=mailbox_dir / "declared.json"
        )
        result = runner.invoke(
            cli, ["msg", "broadcast", "backend only", "--team", "backend"]
        )
        assert result.exit_code == 0
        assert "1 recipient" in result.output
        assert len(mailbox.inbox("ccgram:@5")) == 1
        assert len(mailbox.inbox("ccgram:@8")) == 0

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_filtered_by_provider(
        self, _mock_branch, runner: CliRunner, mailbox: Mailbox, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "codex"},
                "@8": {"cwd": "/c", "window_name": "c", "provider_name": "claude"},
            },
        )
        result = runner.invoke(
            cli, ["msg", "broadcast", "codex only", "--provider", "codex"]
        )
        assert result.exit_code == 0
        assert "1 recipient" in result.output
        assert len(mailbox.inbox("ccgram:@5")) == 1

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_filtered_by_cwd(
        self, _mock_branch, runner: CliRunner, mailbox: Mailbox, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {
                    "cwd": "/projects/backend",
                    "window_name": "b",
                    "provider_name": "claude",
                },
                "@8": {
                    "cwd": "/projects/frontend",
                    "window_name": "c",
                    "provider_name": "claude",
                },
                "@9": {
                    "cwd": "/other/thing",
                    "window_name": "d",
                    "provider_name": "claude",
                },
            },
        )
        result = runner.invoke(
            cli, ["msg", "broadcast", "projects only", "--cwd", "/projects/*"]
        )
        assert result.exit_code == 0
        assert "2 recipient" in result.output
        assert len(mailbox.inbox("ccgram:@5")) == 1
        assert len(mailbox.inbox("ccgram:@8")) == 1
        assert len(mailbox.inbox("ccgram:@9")) == 0

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_no_recipients(
        self, _mock_branch, runner: CliRunner, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
            },
        )
        result = runner.invoke(cli, ["msg", "broadcast", "nobody here"])
        assert result.exit_code == 0
        assert "No matching recipients" in result.output

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_default_ttl(
        self, _mock_branch, runner: CliRunner, mailbox: Mailbox, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "claude"},
            },
        )
        runner.invoke(cli, ["msg", "broadcast", "test"])
        messages = mailbox.inbox("ccgram:@5")
        assert messages[0].ttl_minutes == 480

    @patch("ccgram.msg_discovery.detect_branch", return_value="main")
    def test_broadcast_telegram_visibility(
        self, _mock_branch, runner: CliRunner, mailbox: Mailbox, state_dir: Path
    ):
        _write_state(
            state_dir,
            {
                "@0": {"cwd": "/a", "window_name": "a", "provider_name": "claude"},
                "@5": {"cwd": "/b", "window_name": "b", "provider_name": "claude"},
                "@8": {"cwd": "/c", "window_name": "c", "provider_name": "claude"},
            },
        )
        result = runner.invoke(cli, ["msg", "broadcast", "all"])
        assert "2 recipient" in result.output


class TestRegister:
    def test_register_task(self, runner: CliRunner, mailbox_dir: Path):
        result = runner.invoke(cli, ["msg", "register", "--task", "Implementing auth"])
        assert result.exit_code == 0
        assert "task='Implementing auth'" in result.output
        declared = json.loads((mailbox_dir / "declared.json").read_text())
        assert declared["ccgram:@0"]["task"] == "Implementing auth"

    def test_register_team(self, runner: CliRunner, mailbox_dir: Path):
        result = runner.invoke(cli, ["msg", "register", "--team", "backend"])
        assert result.exit_code == 0
        assert "team='backend'" in result.output

    def test_register_both(self, runner: CliRunner, mailbox_dir: Path):
        result = runner.invoke(
            cli, ["msg", "register", "--task", "API", "--team", "backend"]
        )
        assert result.exit_code == 0
        assert "task='API'" in result.output
        assert "team='backend'" in result.output

    def test_register_update(self, runner: CliRunner, mailbox_dir: Path):
        runner.invoke(cli, ["msg", "register", "--task", "old"])
        runner.invoke(cli, ["msg", "register", "--task", "new"])
        declared = json.loads((mailbox_dir / "declared.json").read_text())
        assert declared["ccgram:@0"]["task"] == "new"

    def test_register_requires_argument(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "register"])
        assert result.exit_code != 0
        assert "at least one" in result.output


class TestSweep:
    def test_sweep_empty(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "sweep"])
        assert result.exit_code == 0
        assert "Swept 0" in result.output

    def test_sweep_expired(self, runner: CliRunner, mailbox: Mailbox):
        mailbox.send(
            from_id="ccgram:@5",
            to_id="ccgram:@0",
            body="old",
            msg_type="request",
            ttl_minutes=0,
        )
        result = runner.invoke(cli, ["msg", "sweep"])
        assert result.exit_code == 0
        assert "Swept" in result.output


class TestWindowSelfIdentification:
    def test_env_var_primary(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, mailbox: Mailbox
    ):
        monkeypatch.setenv("CCGRAM_WINDOW_ID", "custom:@99")
        mailbox.send(
            from_id="ccgram:@5",
            to_id="custom:@99",
            body="hi",
            msg_type="request",
        )
        result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code == 0
        assert "ccgram:@5" in result.output

    def test_tmux_fallback(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        mailbox: Mailbox,
    ):
        monkeypatch.delenv("CCGRAM_WINDOW_ID", raising=False)
        monkeypatch.setenv("TMUX_PANE", "%5")
        mock_result = type("R", (), {"returncode": 0, "stdout": "myses:@3\n"})()
        with patch("ccgram.msg_cmd.subprocess.run", return_value=mock_result):
            mailbox.send(
                from_id="ccgram:@1",
                to_id="myses:@3",
                body="hello via tmux fallback",
                msg_type="request",
            )
            result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code == 0
        assert "ccgram:@1" in result.output

    def test_tmux_fallback_failure(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("CCGRAM_WINDOW_ID", raising=False)
        monkeypatch.setenv("TMUX_PANE", "%5")
        mock_result = type("R", (), {"returncode": 1, "stdout": ""})()
        with patch("ccgram.msg_cmd.subprocess.run", return_value=mock_result):
            result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code != 0
        assert "could not detect window ID" in result.output

    def test_no_env_no_tmux_fails(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("CCGRAM_WINDOW_ID", raising=False)
        monkeypatch.delenv("TMUX_PANE", raising=False)
        result = runner.invoke(cli, ["msg", "inbox"])
        assert result.exit_code != 0
        assert "not in a tmux session" in result.output


class TestSpawnCmd:
    def test_spawn_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "spawn", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.output
        assert "--prompt" in result.output
        assert "--auto" in result.output

    def test_spawn_basic(self, runner: CliRunner, tmp_path: Path):
        result = runner.invoke(
            cli, ["msg", "spawn", "--prompt", "review auth", "--cwd", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Spawn request" in result.output
        assert "awaiting Telegram approval" in result.output

    def test_spawn_auto_mode(self, runner: CliRunner, tmp_path: Path):
        result = runner.invoke(
            cli,
            ["msg", "spawn", "--prompt", "test", "--cwd", str(tmp_path), "--auto"],
        )
        assert result.exit_code == 0
        assert "auto-approve" in result.output

    def test_spawn_bad_cwd(self, runner: CliRunner, tmp_path: Path):
        bad_path = str(tmp_path / "nonexistent")
        result = runner.invoke(
            cli, ["msg", "spawn", "--prompt", "test", "--cwd", bad_path]
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_spawn_max_windows_exceeded(
        self,
        runner: CliRunner,
        state_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("CCGRAM_MSG_MAX_WINDOWS", "2")
        _write_state(
            state_dir,
            {"@0": {"cwd": "/a"}, "@1": {"cwd": "/b"}},
        )
        result = runner.invoke(
            cli, ["msg", "spawn", "--prompt", "test", "--cwd", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "max windows" in result.output

    def test_spawn_rate_limit_exceeded(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from ccgram.spawn_request import reset_spawn_state

        reset_spawn_state()
        monkeypatch.setenv("CCGRAM_MSG_SPAWN_RATE", "1")
        result1 = runner.invoke(
            cli, ["msg", "spawn", "--prompt", "first", "--cwd", str(tmp_path)]
        )
        assert result1.exit_code == 0
        result2 = runner.invoke(
            cli, ["msg", "spawn", "--prompt", "second", "--cwd", str(tmp_path)]
        )
        assert result2.exit_code != 0
        assert "spawn rate limit" in result2.output

    def test_spawn_appears_in_msg_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["msg", "--help"])
        assert result.exit_code == 0
        assert "spawn" in result.output
