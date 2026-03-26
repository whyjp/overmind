"""E2E tests for plugin hooks against a real server.

Starts uvicorn in a background thread, then runs hook scripts
as subprocesses with env-var overrides for URL, user, repo_id, and state file.

Scenario:
  1. on_session_end (dev_a) → pushes a "session ended" event
  2. on_session_start (dev_b) → pulls and outputs systemMessage with dev_a's event
  3. on_pre_tool_use (dev_b) → scope-filtered pull for a file edit
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
import uvicorn

from overmind.api import create_app

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
HOOKS_DIR = PLUGIN_DIR / "hooks"
REPO_ID = "github.com/hooks-e2e/test"


class ServerThread:
    """Run uvicorn in a daemon thread with graceful shutdown."""

    def __init__(self, app, port: int):
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(50):
            time.sleep(0.1)
            if self.server.started:
                break
        else:
            raise RuntimeError("Server failed to start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _api_post(base_url: str, path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _api_get(base_url: str, path: str, params: dict | None = None):
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


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
    return {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
        "PYTHONIOENCODING": "utf-8",
    }


def run_hook(script_name: str, env: dict, stdin_data: str = "") -> str:
    """Run a hook script as subprocess, return stdout."""
    script = HOOKS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(PLUGIN_DIR),
    )
    if result.returncode != 0 and result.stderr:
        print(f"Hook stderr: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


class TestSessionEndHook:
    """on_session_end.py: pushes a session-ended event."""

    def test_push_event_to_server(self, server, base_url, state_dir):
        env = _make_hook_env(base_url, state_dir, "dev_a", "session_end")
        run_hook("on_session_end.py", env, stdin_data="{}")

        body = _api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID})
        assert body["count"] >= 1
        session_events = [e for e in body["events"] if "Session ended" in e["result"]]
        assert len(session_events) == 1
        assert session_events[0]["user"] == "dev_a"
        assert session_events[0]["type"] == "discovery"


class TestSessionStartHook:
    """on_session_start.py: pulls events and outputs systemMessage."""

    def test_pull_outputs_system_message(self, server, base_url, state_dir, seed_events):
        env = _make_hook_env(base_url, state_dir, "dev_b", "session_start")
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
