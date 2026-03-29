"""Unit tests for branch_conflict scaffold — check_config + create_scaffold."""

import subprocess
from pathlib import Path

import pytest

from tests.fixtures.ab_scaffolds.branch_conflict import check_config, create_scaffold


class TestCheckConfig:
    """Test check_config() validation logic."""

    def _write_config(self, repo_dir: Path, config_toml: str, env: str) -> None:
        (repo_dir / "config.toml").write_text(config_toml, encoding="utf-8")
        (repo_dir / ".env").write_text(env, encoding="utf-8")

    def test_all_ok(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[database]
pool_size = 5

[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", """DATABASE_URL=postgresql://localhost/db
AUTH_TOKEN=my-auth-token
API_TOKEN=my-api-token
""")
        result = check_config(repo)
        assert result["all_ok"] is True
        assert result["no_port_conflict"] is True
        assert result["tokens_separated"] is True

    def test_port_conflict(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 8080
rate_limit = 100
session_timeout = 900
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["no_port_conflict"] is False
        assert result["all_ok"] is False

    def test_missing_auth_section(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "API_TOKEN=y\n")
        result = check_config(repo)
        assert result["auth_ok"] is False
        assert result["all_ok"] is False

    def test_auth_timeout_too_low(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 1800

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["auth_timeout_ok"] is False

    def test_api_timeout_too_high(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 3600
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["api_timeout_ok"] is False

    def test_tokens_not_separated(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "SERVICE_TOKEN=some-token\n")
        result = check_config(repo)
        assert result["tokens_separated"] is False


class TestCreateScaffold:
    """Test create_scaffold() git repo creation with branches."""

    def test_creates_on_main(self, tmp_path):
        repo_dir = create_scaffold(tmp_path, branch="main")
        assert repo_dir.exists()
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "main"

    def test_creates_on_feat_auth(self, tmp_path):
        repo_dir = create_scaffold(tmp_path / "auth", branch="feat/auth")
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat/auth"

    def test_creates_on_feat_api(self, tmp_path):
        repo_dir = create_scaffold(tmp_path / "api", branch="feat/api")
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat/api"

    def test_has_remote_origin(self, tmp_path):
        repo_dir = create_scaffold(tmp_path, branch="main")
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert "hive-branch-conflict" in result.stdout

    def test_base_branch_is_main(self, tmp_path):
        """feat/auth should have main as merge-base."""
        repo_dir = create_scaffold(tmp_path / "b", branch="feat/auth")
        result = subprocess.run(
            ["git", "merge-base", "main", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip()
