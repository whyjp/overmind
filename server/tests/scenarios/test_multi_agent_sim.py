# server/tests/scenarios/test_multi_agent_sim.py
"""Multi-agent simulation: two agents work on overlapping scopes.

Uses real Overmind server (thread) + hook subprocesses to simulate
the full PostToolUse → PreToolUse → SessionEnd pipeline with two agents
working on a Hive project scaffold.

Scenario:
  Agent A: OAuth2+PKCE authentication (auth/*, config/*)
  Agent B: Task assignment + notifications (api/*, models/*, auth/*, config/*)
  Overlap: auth/middleware.ts, config/env.ts
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
from tests.fixtures.scaffold_hive import create_hive_repo

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
HOOKS_DIR = PLUGIN_DIR / "hooks"
REPO_ID = "github.com/test/hive"
PORT = 17888


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


def _api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _make_env(base_url: str, state_file: Path, user: str) -> dict:
    return {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": "5",
        "OVERMIND_FLUSH_INTERVAL": "60",
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
        encoding="utf-8",
        timeout=10,
        env=env,
        cwd=str(PLUGIN_DIR),
    )
    return result.stdout.strip()


def _post_tool_use(env: dict, file_path: str, tool: str = "Edit") -> str:
    """Simulate PostToolUse hook for a file edit."""
    return run_hook("on_post_tool_use.py", env, json.dumps({
        "tool_name": tool,
        "tool_input": {"file_path": file_path},
    }))


def _pre_tool_use(env: dict, file_path: str) -> str:
    """Simulate PreToolUse hook for a file edit."""
    return run_hook("on_pre_tool_use.py", env, json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
    }))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("multi_agent_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=PORT)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def hive_repo(tmp_path_factory):
    base = tmp_path_factory.mktemp("hive_scaffold")
    return create_hive_repo(base)


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("agent_states")


@pytest.mark.multi_agent
class TestMultiAgentSimulation:
    """Full cross-agent simulation: PostToolUse → PreToolUse → flush → verify."""

    def test_full_sequence(self, server, base_url, hive_repo, state_dir):
        env_a = _make_env(base_url, state_dir / "state_a.json", "agent_a")
        env_b = _make_env(base_url, state_dir / "state_b.json", "agent_b")

        # ── Phase 1: Agent A starts OAuth2 work ──
        # SessionStart: no events yet
        out = run_hook("on_session_start.py", env_a)
        assert out == "", "No events yet — SessionStart should be silent"

        # Agent A edits auth files (3 PostToolUse calls)
        _post_tool_use(env_a, "src/auth/jwt.ts")
        _post_tool_use(env_a, "src/auth/routes.ts")
        _post_tool_use(env_a, "src/auth/middleware.ts")

        # Verify accumulation in state — all 3 pending, no premature flush
        state_a = json.loads((state_dir / "state_a.json").read_text())
        assert len(state_a["pending_changes"]) == 3
        assert state_a["current_scope"] == "src/auth/*"

        # ── Phase 2: Agent B starts, enters auth scope ──
        # A hasn't flushed yet (3 < threshold 5), so B sees nothing
        out = run_hook("on_session_start.py", env_b)
        assert out == "", "A hasn't flushed yet — SessionStart should be silent"

        # Agent B: PreToolUse on auth/middleware.ts
        # A hasn't pushed, so no cross-agent warning
        out = _pre_tool_use(env_b, "src/auth/middleware.ts")
        assert out == "", "A hasn't flushed yet — no warning expected"

        # Agent B edits non-overlapping files
        _post_tool_use(env_b, "src/api/tasks.ts")
        _post_tool_use(env_b, "src/models/task.ts")

        # ── Phase 3: Agent A hits flush — scope change from auth/* to config/* ──
        _post_tool_use(env_a, "src/config/env.ts")  # scope change → flush 3 auth/* files
        _post_tool_use(env_a, ".env.example")  # scope change again → flush config/*

        # Verify A's auth/* events are now on server
        pull = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
            "exclude_user": "agent_b",
        })
        assert pull["count"] >= 1, "Agent A's auth scope events should be on server"
        assert any("src/auth/*" in e.get("scope", "") or
                    any("src/auth/" in f for f in e.get("files", []))
                    for e in pull["events"])

        # ── Phase 4: Agent B enters auth scope again — NOW sees A's events ──
        out = _pre_tool_use(env_b, "src/auth/middleware.ts")
        assert out != "", "B should now see A's auth/* events after flush"
        parsed = json.loads(out)
        assert "systemMessage" in parsed
        assert "agent_a" in parsed["systemMessage"]
        assert "OVERMIND" in parsed["systemMessage"]

        # Agent B continues working, hits overlapping scopes
        _post_tool_use(env_b, "src/services/notification.ts")
        _post_tool_use(env_b, "src/auth/middleware.ts")
        _post_tool_use(env_b, "src/config/env.ts")  # scope change → flush previous

        # ── Phase 5: Verify cross-agent visibility ──
        # Agent A checks config scope — should see B's changes
        out = _pre_tool_use(env_a, "src/config/env.ts")
        # B's config/env.ts change should be visible after B's flush
        # (B had scope change from api/* to auth/* to config/*)

        # ── Phase 6: SessionEnd — flush remaining ──
        run_hook("on_session_end.py", env_a, "{}")
        run_hook("on_session_end.py", env_b, "{}")

        # ── Phase 7: Verify final server state ──
        # Both agents should have events
        pull_all = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "limit": "50",
        })
        assert pull_all["count"] >= 2, "Both agents should have pushed events"
        users = {e["user"] for e in pull_all["events"]}
        assert "agent_a" in users, "Agent A events missing"
        assert "agent_b" in users, "Agent B events missing"

        # Report stats
        report = _api_get(base_url, "/api/report", {"repo_id": REPO_ID})
        assert report["unique_users"] >= 2
        assert report["events_by_type"].get("change", 0) >= 2

        # Graph: polymorphism detection on auth/* scope
        graph = _api_get(base_url, "/api/report/graph", {"repo_id": REPO_ID})
        auth_polys = [
            p for p in graph.get("polymorphisms", [])
            if "auth" in p.get("scope", "")
        ]
        assert len(auth_polys) >= 1, (
            f"Expected polymorphism on auth/* scope, got: {graph.get('polymorphisms', [])}"
        )
        poly_users = set(auth_polys[0]["users"])
        assert poly_users == {"agent_a", "agent_b"}

    def test_scope_isolation(self, server, base_url, state_dir):
        """Events in api/* scope should not appear in auth/* pull."""
        pull_api = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/api/*",
        })
        pull_auth = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
        })
        api_ids = {e["id"] for e in pull_api["events"]}
        auth_ids = {e["id"] for e in pull_auth["events"]}
        assert not api_ids.intersection(auth_ids), "api/* and auth/* events should not overlap"
