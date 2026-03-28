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
