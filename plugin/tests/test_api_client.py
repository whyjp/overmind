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
        assert file_to_scope("README.md") == "README.md"

    def test_windows_backslash(self):
        from api_client import file_to_scope
        assert file_to_scope("src\\auth\\login.ts") == "src/auth/*"

    def test_single_dir(self):
        from api_client import file_to_scope
        assert file_to_scope("src/file.ts") == "src/*"


class TestLoadSaveState:
    def test_load_empty_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        assert api_client.load_state() == {}

    def test_save_and_load(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"last_pull_ts": "2026-03-27T10:00:00Z", "pending_changes": []})
        state = api_client.load_state()
        assert state["last_pull_ts"] == "2026-03-27T10:00:00Z"
        assert state["pending_changes"] == []

    def test_overwrite_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"key": "old"})
        api_client.save_state({"key": "new"})
        state = api_client.load_state()
        assert state["key"] == "new"

    def test_preserves_unicode(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"result": "한글 테스트"})
        state = api_client.load_state()
        assert state["result"] == "한글 테스트"
