"""Integration tests: run hook scripts as subprocesses with env overrides.

These tests verify hook scripts handle stdin/stdout correctly.
Server is NOT running — hooks should gracefully handle connection failures.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"
PLUGIN_DIR = Path(__file__).resolve().parents[1]


def run_hook(script_name: str, env: dict, stdin_data: str = "") -> subprocess.CompletedProcess:
    """Run a hook script as subprocess."""
    script = HOOKS_DIR / script_name
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(PLUGIN_DIR),
    )


class TestPostToolUseHook:
    """on_post_tool_use.py: accumulates changes in state file."""

    def test_accumulates_change_in_state(self, plugin_env, tmp_state_file):
        """PostToolUse writes pending_changes to state file."""
        stdin_data = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth/login.ts"},
        })
        result = run_hook("on_post_tool_use.py", plugin_env, stdin_data)
        assert result.returncode == 0

        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert len(state.get("pending_changes", [])) == 1
        assert state["pending_changes"][0]["file"] == "src/auth/login.ts"
        assert state["pending_changes"][0]["scope"] == "src/auth/*"
        assert state["current_scope"] == "src/auth/*"

    def test_multiple_accumulations(self, plugin_env, tmp_state_file):
        """Multiple PostToolUse calls accumulate in state."""
        from datetime import datetime, timezone
        # Use recent timestamp to prevent time-based flush trigger
        now = datetime.now(timezone.utc).isoformat()
        tmp_state_file.write_text(json.dumps({
            "last_push_ts": now,
            "pending_changes": []
        }))

        for f in ["src/auth/login.ts", "src/auth/oauth2.ts", "src/auth/jwt.ts"]:
            stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": f}})
            run_hook("on_post_tool_use.py", plugin_env, stdin_data)

        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert len(state["pending_changes"]) == 3

    def test_no_file_path_no_state_change(self, plugin_env, tmp_state_file):
        """No file_path in input → no state change."""
        stdin_data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        run_hook("on_post_tool_use.py", plugin_env, stdin_data)
        assert not tmp_state_file.exists()

    def test_empty_stdin_no_crash(self, plugin_env, tmp_state_file):
        """Empty stdin → graceful exit, no crash."""
        result = run_hook("on_post_tool_use.py", plugin_env, "")
        assert result.returncode == 0

    def test_no_repo_id_no_crash(self, plugin_env, tmp_state_file):
        """Missing OVERMIND_REPO_ID → graceful exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/foo.ts"}})
        result = run_hook("on_post_tool_use.py", env, stdin_data)
        assert result.returncode == 0


class TestSessionEndHook:
    """on_session_end.py: flushes remaining pending changes."""

    def test_no_pending_no_push(self, plugin_env, tmp_state_file):
        """No pending changes → no push attempt, clean exit."""
        tmp_state_file.write_text(json.dumps({"last_pull_ts": "2026-03-27T10:00:00Z"}))
        result = run_hook("on_session_end.py", plugin_env, "{}")
        assert result.returncode == 0

    def test_clears_current_scope(self, plugin_env, tmp_state_file):
        """SessionEnd clears current_scope from state."""
        tmp_state_file.write_text(json.dumps({
            "current_scope": "src/auth/*",
            "pending_changes": [],
        }))
        result = run_hook("on_session_end.py", plugin_env, "{}")
        assert result.returncode == 0
        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert "current_scope" not in state

    def test_no_repo_id_no_crash(self, plugin_env, tmp_state_file):
        """Missing repo_id → graceful exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        result = run_hook("on_session_end.py", env, "{}")
        assert result.returncode == 0


class TestPreToolUseHook:
    """on_pre_tool_use.py: basic subprocess behavior (no server)."""

    def test_no_file_path_no_output(self, plugin_env):
        """No file_path → no output, clean exit."""
        stdin_data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        result = run_hook("on_pre_tool_use.py", plugin_env, stdin_data)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_no_repo_id_no_output(self, plugin_env):
        """Missing repo_id → no output, clean exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/foo.ts"}})
        result = run_hook("on_pre_tool_use.py", env, stdin_data)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestSessionStartHook:
    """on_session_start.py: basic subprocess behavior (no server)."""

    def test_no_repo_id_no_output(self, plugin_env):
        """Missing repo_id → no output, clean exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        result = run_hook("on_session_start.py", env, "")
        assert result.returncode == 0
        assert result.stdout.strip() == ""
