"""E2E tests for plugin hooks against a real server.

Starts uvicorn in a background thread, then runs hook scripts
as subprocesses with env-var overrides for URL, user, repo_id, and state file.

Scenario:
  1. on_session_end (dev_a) → flushes pending changes
  2. on_session_start (dev_b) → pulls and outputs systemMessage with dev_a's event
  3. on_pre_tool_use (dev_b) → scope-filtered pull for a file edit
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from overmind.api import create_app
from tests.fixtures.server_helpers import ServerThread, HOOKS_DIR, api_post as _api_post, api_get as _api_get, run_hook, make_hook_env

REPO_ID = "github.com/hooks-e2e/test"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("e2e_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=17777)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{server.port}"


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("hook_state")


@pytest.fixture(scope="module")
def seed_events(server, base_url):
    """Push test events once for the entire module."""
    _api_post(base_url, "/api/memory/push", {
        "repo_id": REPO_ID,
        "user": "dev_a",
        "events": [
            {
                "id": "e2e_001", "type": "correction",
                "ts": "2026-03-26T01:00:00Z",
                "result": "auth module fix: bcrypt to argon2",
                "files": ["src/auth/hash.ts"],
                "process": ["bcrypt perf issue", "switched to argon2"],
            },
            {
                "id": "e2e_002", "type": "decision",
                "ts": "2026-03-26T01:30:00Z",
                "result": "Redis cache TTL set to 1 hour",
                "files": ["src/cache/config.ts"],
            },
            {
                "id": "e2e_003", "type": "correction",
                "ts": "2026-03-26T02:00:00Z",
                "result": "DO NOT modify deploy scripts directly",
                "files": ["src/deploy/run.sh"],
                "priority": "urgent",
            },
        ],
    })


def _make_hook_env(base_url: str, state_dir: Path, user: str, test_name: str) -> dict:
    state_file = state_dir / f"state_{test_name}_{user}.json"
    return make_hook_env(base_url, state_file, user, REPO_ID)


class TestSessionEndHook:
    """on_session_end.py: flushes pending changes (no push if empty)."""

    def test_no_push_when_no_pending(self, server, base_url, state_dir):
        """SessionEnd with no pending changes should not push anything."""
        env = _make_hook_env(base_url, state_dir, "dev_a", "session_end")
        run_hook("on_session_end.py", env, stdin_data="{}")

        body = _api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "user": "dev_a"})
        # No events from dev_a — SessionEnd only flushes pending, and there were none
        session_events = [e for e in body["events"] if e["user"] == "dev_a"]
        assert len(session_events) == 0

    def test_flushes_pending_changes(self, server, base_url, state_dir):
        """SessionEnd with pending changes should push grouped change events."""
        state_file = state_dir / "state_session_end_flush_dev_a.json"
        state_file.write_text(json.dumps({
            "pending_changes": [
                {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
                {"file": "src/auth/jwt.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:05:00Z", "action": "Edit"},
            ],
            "current_scope": "src/auth/*",
        }))
        env = {
            **_make_hook_env(base_url, state_dir, "dev_a", "session_end_flush"),
            "OVERMIND_STATE_FILE": str(state_file),
        }
        run_hook("on_session_end.py", env, stdin_data="{}")

        body = _api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "user": "dev_a"})
        change_events = [e for e in body["events"] if e["type"] == "change"]
        assert len(change_events) >= 1
        assert "src/auth/*" in change_events[0].get("result", "")


class TestSessionStartHook:
    """on_session_start.py: pulls events and outputs systemMessage."""

    def test_pull_outputs_system_message(self, server, base_url, state_dir, seed_events):
        # Pre-seed state with old last_pull_ts so seed events are within pull window
        state_file = state_dir / "state_session_start_dev_b.json"
        state_file.write_text(json.dumps({"last_pull_ts": "2026-03-25T00:00:00Z"}))
        env = {
            **_make_hook_env(base_url, state_dir, "dev_b", "session_start"),
            "OVERMIND_STATE_FILE": str(state_file),
        }
        stdout = run_hook("on_session_start.py", env)

        assert stdout, "Hook produced no output"
        output = json.loads(stdout)
        assert "systemMessage" in output

        msg = output["systemMessage"]
        assert "[OVERMIND]" in msg
        assert "dev_a" in msg
        # correction → RULES section, decision → RULES section
        assert "RULES" in msg or "CONTEXT" in msg
        # Should contain the seeded auth event
        assert "auth" in msg or "bcrypt" in msg or "argon2" in msg

    def test_session_start_creates_context_file(self, server, base_url, state_dir, seed_events, tmp_path):
        """SessionStart writes .claude/overmind-context.md with pulled events."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        state_file = state_dir / "state_session_start_context_dev_b.json"
        state_file.write_text(json.dumps({"last_pull_ts": "2026-03-25T00:00:00Z"}))
        env = make_hook_env(base_url, state_file, "dev_b", REPO_ID)

        script = HOOKS_DIR / "on_session_start.py"
        subprocess.run(
            [sys.executable, str(script)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=str(project_root),
        )

        context_file = project_root / ".claude" / "overmind-context.md"
        assert context_file.exists(), "overmind-context.md was not created"

        content = context_file.read_text(encoding="utf-8")
        assert "# Overmind Team Context" in content
        assert "argon2" in content or "auth" in content, (
            f"Expected seed event content (argon2/auth) in context file, got: {content[:300]}"
        )

    def test_self_excluded(self, server, base_url, state_dir, seed_events):
        env = _make_hook_env(base_url, state_dir, "dev_a", "session_start_self")
        stdout = run_hook("on_session_start.py", env)
        assert stdout == ""


class TestPreToolUseHook:
    """on_pre_tool_use.py: scope-filtered pull when editing a file."""

    def test_scope_filtered_pull(self, server, base_url, state_dir, seed_events):
        env = _make_hook_env(base_url, state_dir, "dev_b", "pretool_scope")
        stdin_data = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth/login.ts"},
        })
        stdout = run_hook("on_pre_tool_use.py", env, stdin_data=stdin_data)

        assert stdout, "Hook produced no output for auth scope"
        output = json.loads(stdout)
        msg = output["systemMessage"]
        assert "[OVERMIND]" in msg
        assert "src/auth/*" in msg
        assert "dev_a" in msg

    def test_unrelated_scope_no_output(self, server, base_url, state_dir, seed_events):
        env = _make_hook_env(base_url, state_dir, "dev_b", "pretool_unrelated")
        stdin_data = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/unrelated/foo.ts"},
        })
        stdout = run_hook("on_pre_tool_use.py", env, stdin_data=stdin_data)
        assert stdout == ""

    def test_no_file_path_no_output(self, server, base_url, state_dir, seed_events):
        env = _make_hook_env(base_url, state_dir, "dev_b", "pretool_nofile")
        stdin_data = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        })
        stdout = run_hook("on_pre_tool_use.py", env, stdin_data=stdin_data)
        assert stdout == ""

    def test_urgent_correction_blocks_edit(self, server, base_url, state_dir, seed_events):
        """Urgent correction in scope → tool use BLOCKED."""
        env = _make_hook_env(base_url, state_dir, "dev_b", "pretool_block")
        stdin_data = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/deploy/config.sh"},
        })
        stdout = run_hook("on_pre_tool_use.py", env, stdin_data=stdin_data)

        assert stdout, "Hook should produce blocking output"
        output = json.loads(stdout)
        hook_output = output.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny"
        assert "OVERMIND BLOCK" in hook_output.get("permissionDecisionReason", "")
        assert "deploy" in hook_output.get("permissionDecisionReason", "").lower()
