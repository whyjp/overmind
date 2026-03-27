"""Tests for diff_collector — git diff snippet collection."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diff_collector import collect_diff_summary


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with one committed file."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True, env=GIT_ENV)
    config_file = tmp_path / "config.toml"
    config_file.write_text("[server]\nhost = \"localhost\"\nport = 8080\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True, env=GIT_ENV)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path), check=True, capture_output=True, env=GIT_ENV,
    )
    return tmp_path


class TestCollectDiffSummary:
    def test_returns_diff_for_modified_file(self, git_repo):
        config_file = git_repo / "config.toml"
        config_file.write_text("[server]\nhost = \"localhost\"\nport = 9090\ndebug = true\n")
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        assert result != ""
        assert "+port = 9090" in result or "+debug = true" in result

    def test_returns_empty_for_no_changes(self, git_repo):
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        assert result == ""

    def test_returns_empty_for_nonexistent_file(self, git_repo):
        result = collect_diff_summary(["nonexistent.txt"], cwd=str(git_repo))
        assert result == ""

    def test_truncates_long_diff(self, git_repo):
        config_file = git_repo / "config.toml"
        lines = [f"line{i} = {i}" for i in range(50)]
        config_file.write_text("\n".join(lines))
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo), max_lines=10)
        output_lines = result.splitlines()
        # 10 kept + 1 truncation notice
        assert len(output_lines) == 11
        assert "truncated" in output_lines[-1]

    def test_only_added_lines_shown(self, git_repo):
        config_file = git_repo / "config.toml"
        config_file.write_text("[server]\nhost = \"localhost\"\nport = 9090\n")
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        for line in result.splitlines():
            assert line.startswith("+") or line.startswith("@@"), f"Unexpected line: {line}"

    def test_returns_empty_for_empty_file_list(self):
        result = collect_diff_summary([])
        assert result == ""
