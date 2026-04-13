"""Tests for src/ccgram/handlers/send_security.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from ccgram.handlers.send_security import (
    check_gitleaks_rules,
    is_excluded_dir,
    is_gitignored,
    is_hidden,
    is_path_contained,
    matches_secret_pattern,
    validate_sendable,
)


class TestIsPathContained:
    def test_file_inside_root(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        assert is_path_contained(f, tmp_path) is True

    def test_file_in_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "file.txt"
        f.touch()
        assert is_path_contained(f, tmp_path) is True

    def test_file_outside_root(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "other.txt"
        assert is_path_contained(outside, tmp_path) is False

    def test_dotdot_traversal(self, tmp_path: Path) -> None:
        traversal = tmp_path / ".." / "secret.txt"
        assert is_path_contained(traversal, tmp_path) is False

    def test_symlink_escape(self, tmp_path: Path) -> None:
        real_outside = tmp_path.parent / "outside.txt"
        real_outside.touch()
        link = tmp_path / "link.txt"
        link.symlink_to(real_outside)
        assert is_path_contained(link, tmp_path) is False

    def test_symlink_within_root(self, tmp_path: Path) -> None:
        real_file = tmp_path / "real.txt"
        real_file.touch()
        link = tmp_path / "link.txt"
        link.symlink_to(real_file)
        assert is_path_contained(link, tmp_path) is True

    def test_root_itself(self, tmp_path: Path) -> None:
        assert is_path_contained(tmp_path, tmp_path) is True


class TestIsHidden:
    def test_dotfile(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.touch()
        assert is_hidden(f, tmp_path) is True

    def test_nested_dotdir(self, tmp_path: Path) -> None:
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()
        f = hidden_dir / "config"
        f.touch()
        assert is_hidden(f, tmp_path) is True

    def test_non_hidden_file(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        f.touch()
        assert is_hidden(f, tmp_path) is False

    def test_non_hidden_nested(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        f = sub / "module.py"
        f.touch()
        assert is_hidden(f, tmp_path) is False

    def test_root_itself_not_hidden(self, tmp_path: Path) -> None:
        assert is_hidden(tmp_path, tmp_path) is False

    def test_file_in_dotdir_is_hidden(self, tmp_path: Path) -> None:
        dotdir = tmp_path / ".venv"
        dotdir.mkdir()
        f = dotdir / "pyvenv.cfg"
        f.touch()
        assert is_hidden(f, tmp_path) is True


class TestMatchesSecretPattern:
    def test_env_file(self) -> None:
        assert matches_secret_pattern(Path(".env")) == ".env"

    def test_pem_file(self) -> None:
        assert matches_secret_pattern(Path("cert.pem")) == "*.pem"

    def test_key_file(self) -> None:
        assert matches_secret_pattern(Path("id_rsa.key")) == "*.key"

    def test_credential_json(self) -> None:
        result = matches_secret_pattern(Path("credential.json"))
        assert result == "*credential*"

    def test_secret_yaml(self) -> None:
        result = matches_secret_pattern(Path("app.secret.yaml"))
        assert result is not None
        assert "secret" in result

    def test_normal_file(self) -> None:
        assert matches_secret_pattern(Path("main.py")) is None

    def test_normal_config(self) -> None:
        assert matches_secret_pattern(Path("config.toml")) is None

    def test_case_insensitive_pem(self) -> None:
        assert matches_secret_pattern(Path("CERT.PEM")) == "*.pem"

    def test_env_with_suffix(self) -> None:
        assert matches_secret_pattern(Path(".env.local")) == ".env.*"

    def test_p12_file(self) -> None:
        assert matches_secret_pattern(Path("keystore.p12")) == "*.p12"


class TestIsGitignored:
    def test_ignored_via_git(self, tmp_path: Path) -> None:
        f = tmp_path / "ignored.log"
        f.touch()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert is_gitignored(f, tmp_path) is True

    def test_not_ignored_via_git(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        f.touch()
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert is_gitignored(f, tmp_path) is False

    def test_git_not_found_falls_back_to_pathspec(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n", encoding="utf-8")
        f = tmp_path / "debug.log"
        f.touch()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_gitignored(f, tmp_path) is True

    def test_git_error_non_matching_pathspec_fallback(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n", encoding="utf-8")
        f = tmp_path / "main.py"
        f.touch()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_gitignored(f, tmp_path) is False

    def test_timeout_falls_back_to_pathspec(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/\n", encoding="utf-8")
        build = tmp_path / "build"
        build.mkdir()
        f = build / "output.bin"
        f.touch()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 5)):
            assert is_gitignored(f, tmp_path) is True

    def test_no_gitignore_returns_false(self, tmp_path: Path) -> None:
        f = tmp_path / "file.py"
        f.touch()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_gitignored(f, tmp_path) is False

    def test_fatal_git_error_falls_back_to_pathspec(self, tmp_path: Path) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n", encoding="utf-8")
        f = tmp_path / "debug.log"
        f.touch()
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch("subprocess.run", return_value=mock_result):
            assert is_gitignored(f, tmp_path) is True

    def test_fatal_git_error_non_matching_falls_back_to_pathspec(
        self, tmp_path: Path
    ) -> None:
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n", encoding="utf-8")
        f = tmp_path / "main.py"
        f.touch()
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch("subprocess.run", return_value=mock_result):
            assert is_gitignored(f, tmp_path) is False


class TestCheckGitleaksRules:
    def test_no_toml_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "main.py"
        assert check_gitleaks_rules(f, tmp_path) is None

    def test_matching_rule_returns_id(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"""
[[rules]]
id = "aws-key"
path = ".*credentials.*"
""")
        f = tmp_path / "aws-credentials.txt"
        assert check_gitleaks_rules(f, tmp_path) == "aws-key"

    def test_non_matching_rule_returns_none(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"""
[[rules]]
id = "aws-key"
path = ".*credentials.*"
""")
        f = tmp_path / "main.py"
        assert check_gitleaks_rules(f, tmp_path) is None

    def test_rule_without_id_returns_default(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"""
[[rules]]
path = '.*[.]pfx$'
""")
        f = tmp_path / "cert.pfx"
        assert check_gitleaks_rules(f, tmp_path) == "gitleaks rule"

    def test_malformed_toml_returns_none(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"this is [not valid toml }{")
        f = tmp_path / "main.py"
        assert check_gitleaks_rules(f, tmp_path) is None

    def test_rule_with_invalid_regex_skipped(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"""
[[rules]]
id = "bad-regex"
path = "[invalid("

[[rules]]
id = "good-rule"
path = ".*secret.*"
""")
        f = tmp_path / "my-secret.txt"
        assert check_gitleaks_rules(f, tmp_path) == "good-rule"

    def test_empty_rules_returns_none(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"[title]\nversion = 1\n")
        f = tmp_path / "main.py"
        assert check_gitleaks_rules(f, tmp_path) is None


class TestValidateSendable:
    def test_clean_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("hello", encoding="utf-8")
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert validate_sendable(f, tmp_path) is None

    def test_outside_cwd_denied(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "secret.txt"
        assert (
            validate_sendable(outside, tmp_path) == "File is outside project directory"
        )

    def test_hidden_file_denied(self, tmp_path: Path) -> None:
        f = tmp_path / ".env"
        f.write_text("TOKEN=secret", encoding="utf-8")
        assert validate_sendable(f, tmp_path) == "Hidden files cannot be sent"

    def test_secret_pattern_denied(self, tmp_path: Path) -> None:
        f = tmp_path / "server.pem"
        f.write_text("cert", encoding="utf-8")
        result = validate_sendable(f, tmp_path)
        assert result is not None
        assert "credentials" in result
        assert "*.pem" in result

    def test_gitleaks_rule_denied(self, tmp_path: Path) -> None:
        toml = tmp_path / ".gitleaks.toml"
        toml.write_bytes(b"""
[[rules]]
id = "my-rule"
path = ".*private.*"
""")
        f = tmp_path / "private-key.txt"
        f.write_text("data", encoding="utf-8")
        result = validate_sendable(f, tmp_path)
        assert result is not None
        assert "gitleaks" in result
        assert "my-rule" in result

    def test_gitignored_denied(self, tmp_path: Path) -> None:
        f = tmp_path / "output.log"
        f.write_text("log", encoding="utf-8")
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = validate_sendable(f, tmp_path)
        assert result == "File is gitignored"

    def test_file_too_large_denied(self, tmp_path: Path) -> None:
        f = tmp_path / "huge.bin"
        f.write_text("x", encoding="utf-8")
        import stat as stat_module

        mock_stat = MagicMock()
        mock_stat.st_size = 60 * 1024 * 1024
        mock_stat.st_mode = stat_module.S_IFREG | 0o644
        mock_result = MagicMock()
        mock_result.returncode = 1
        with (
            patch("subprocess.run", return_value=mock_result),
            patch.object(Path, "stat", return_value=mock_stat),
            patch.object(Path, "is_file", return_value=True),
        ):
            result = validate_sendable(f, tmp_path)
        assert result is not None
        assert "too large" in result

    def test_not_regular_file_denied(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            result = validate_sendable(d, tmp_path)
        assert result == "Not a regular file"

    def test_state_file_denied(self, tmp_path: Path) -> None:
        f = tmp_path / "state.json"
        f.write_text("{}", encoding="utf-8")
        mock_result = MagicMock()
        mock_result.returncode = 1
        with (
            patch("subprocess.run", return_value=mock_result),
            patch("ccgram.utils.ccgram_dir", return_value=tmp_path),
        ):
            result = validate_sendable(f, tmp_path)
        assert result is not None
        assert "state" in result.lower() or "refusing" in result.lower()


class TestIsExcludedDir:
    def test_node_modules(self) -> None:
        assert is_excluded_dir("node_modules") is True

    def test_pycache(self) -> None:
        assert is_excluded_dir("__pycache__") is True

    def test_git_dir(self) -> None:
        assert is_excluded_dir(".git") is True

    def test_venv_dir(self) -> None:
        assert is_excluded_dir(".venv") is True

    def test_dot_prefix(self) -> None:
        assert is_excluded_dir(".mydir") is True

    def test_normal_dir(self) -> None:
        assert is_excluded_dir("src") is False

    def test_tests_dir(self) -> None:
        assert is_excluded_dir("tests") is False

    def test_dist_dir(self) -> None:
        assert is_excluded_dir("dist") is True

    def test_build_dir(self) -> None:
        assert is_excluded_dir("build") is True
