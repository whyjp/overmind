"""Tests for plugin/scripts/api_client.py pure functions."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import api_client
from api_client import normalize_git_remote


class TestNormalizeGitRemote:
    def test_https_with_git_suffix(self):
        assert normalize_git_remote("https://github.com/user/repo.git") == "github.com/user/repo"

    def test_https_without_git_suffix(self):
        assert normalize_git_remote("https://github.com/user/repo") == "github.com/user/repo"

    def test_http_url(self):
        assert normalize_git_remote("http://github.com/user/repo.git") == "github.com/user/repo"

    def test_ssh_url(self):
        assert normalize_git_remote("git@github.com:user/repo.git") == "github.com/user/repo"

    def test_ssh_without_git_suffix(self):
        assert normalize_git_remote("git@github.com:user/repo") == "github.com/user/repo"

    def test_trailing_slash(self):
        assert normalize_git_remote("https://github.com/user/repo/") == "github.com/user/repo"

    def test_whitespace(self):
        assert normalize_git_remote("  https://github.com/user/repo.git  ") == "github.com/user/repo"

    def test_gitlab_ssh(self):
        assert normalize_git_remote("git@gitlab.com:org/project.git") == "gitlab.com/org/project"

    def test_nested_path(self):
        assert normalize_git_remote("https://github.com/org/sub/repo.git") == "github.com/org/sub/repo"

    def test_empty_string(self):
        assert normalize_git_remote("") == ""

    def test_plain_domain(self):
        assert normalize_git_remote("github.com/user/repo") == "github.com/user/repo"


class TestFileToScope:
    def test_nested_path(self):
        from api_client import file_to_scope
        assert file_to_scope("src/auth/login.ts") == "src/auth/*"

    def test_deep_path(self):
        from api_client import file_to_scope
        assert file_to_scope("src/components/ui/button.tsx") == "src/components/ui/*"

    def test_root_file(self):
        from api_client import file_to_scope
        assert file_to_scope("README.md") == "*"

    def test_windows_backslash(self):
        from api_client import file_to_scope
        assert file_to_scope("src\\auth\\login.ts") == "src/auth/*"

    def test_single_dir(self):
        from api_client import file_to_scope
        assert file_to_scope("src/file.ts") == "src/*"


class TestLoadSaveState:
    def test_load_empty_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_client, "STATE_FILE", tmp_path / "state.json")
        assert api_client.load_state() == {}

    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_client, "STATE_FILE", tmp_path / "state.json")
        api_client.save_state({"last_pull_ts": "2026-03-27T10:00:00Z", "pending_changes": []})
        state = api_client.load_state()
        assert state["last_pull_ts"] == "2026-03-27T10:00:00Z"
        assert state["pending_changes"] == []

    def test_overwrite_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_client, "STATE_FILE", tmp_path / "state.json")
        api_client.save_state({"key": "old"})
        api_client.save_state({"key": "new"})
        state = api_client.load_state()
        assert state["key"] == "new"

    def test_preserves_unicode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_client, "STATE_FILE", tmp_path / "state.json")
        api_client.save_state({"result": "한글 테스트"})
        state = api_client.load_state()
        assert state["result"] == "한글 테스트"


class TestGetCurrentBranch:
    def test_returns_branch_name(self, monkeypatch):
        monkeypatch.setattr(
            api_client.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "feature/auth\n"})(),
        )
        assert api_client.get_current_branch() == "feature/auth"

    def test_detached_head_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            api_client.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "HEAD\n"})(),
        )
        assert api_client.get_current_branch() is None

    def test_git_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            api_client.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 128, "stdout": ""})(),
        )
        assert api_client.get_current_branch() is None


class TestGetBaseBranch:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OVERMIND_BASE_BRANCH", "develop")
        assert api_client.get_base_branch() == "develop"

    def test_detects_main(self, monkeypatch):
        monkeypatch.delenv("OVERMIND_BASE_BRANCH", raising=False)
        def mock_run(cmd, **kw):
            if "main" in cmd:
                return type("R", (), {"returncode": 0, "stdout": "abc123\n"})()
            return type("R", (), {"returncode": 1, "stdout": ""})()
        monkeypatch.setattr(api_client.subprocess, "run", mock_run)
        assert api_client.get_base_branch() == "main"

    def test_falls_back_to_master(self, monkeypatch):
        monkeypatch.delenv("OVERMIND_BASE_BRANCH", raising=False)
        def mock_run(cmd, **kw):
            if "master" in cmd:
                return type("R", (), {"returncode": 0, "stdout": "abc123\n"})()
            return type("R", (), {"returncode": 1, "stdout": ""})()
        monkeypatch.setattr(api_client.subprocess, "run", mock_run)
        assert api_client.get_base_branch() == "master"

    def test_no_base_returns_none(self, monkeypatch):
        monkeypatch.delenv("OVERMIND_BASE_BRANCH", raising=False)
        monkeypatch.setattr(
            api_client.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})(),
        )
        assert api_client.get_base_branch() is None


class TestBranchDetectionWithCwd:
    """Test branch detection with explicit cwd on real git repos."""

    def _make_repo(self, tmp_path, branch="feat/auth"):
        """Create a minimal git repo on the given branch."""
        import subprocess
        repo = tmp_path / "repo"
        repo.mkdir()
        git_env = {
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com",
        }
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True, check=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True, env=git_env)
        if branch != "main":
            subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo), capture_output=True, check=True)
        return repo

    def test_current_branch_with_cwd(self, tmp_path):
        repo = self._make_repo(tmp_path, "feat/auth")
        assert api_client.get_current_branch(cwd=str(repo)) == "feat/auth"

    def test_current_branch_main(self, tmp_path):
        repo = self._make_repo(tmp_path, "main")
        assert api_client.get_current_branch(cwd=str(repo)) == "main"

    def test_base_branch_with_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OVERMIND_BASE_BRANCH", raising=False)
        repo = self._make_repo(tmp_path, "feat/api")
        assert api_client.get_base_branch(cwd=str(repo)) == "main"

    def test_cwd_overrides_process_cwd(self, tmp_path):
        """Even if process CWD is not a git repo, explicit cwd works."""
        repo = self._make_repo(tmp_path, "feat/auth")
        # Run from a non-git directory — should still detect branch via cwd
        assert api_client.get_current_branch(cwd=str(repo)) == "feat/auth"

    def test_none_cwd_falls_back_to_process_cwd(self):
        """Without cwd, uses process CWD (backward compat)."""
        # Just verify it doesn't crash — result depends on test runner CWD
        result = api_client.get_current_branch(cwd=None)
        assert result is None or isinstance(result, str)
