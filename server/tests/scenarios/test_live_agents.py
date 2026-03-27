# server/tests/scenarios/test_live_agents.py
"""Live multi-agent E2E: run real Claude CLI agents against Hive scaffold.

Requires:
  - `claude` CLI installed and authenticated
  - Overmind plugin at plugin/ directory
  - Run manually: pytest tests/scenarios/test_live_agents.py -m e2e_live

This test is EXCLUDED from normal test runs via addopts in pyproject.toml.
"""

import json
import os
import subprocess
import sys
import shutil
import threading
import time
import warnings
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
import uvicorn

from overmind.api import create_app
from tests.fixtures.scaffold_hive import create_hive_repo

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
PORT = 17999


class ServerThread:
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
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module")
def claude_cli():
    """Check that claude CLI is available."""
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found — install Claude Code to run this test")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("live_agent_data")
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
    base = tmp_path_factory.mktemp("live_hive")
    return create_hive_repo(base)


REPO_ID = "github.com/test/hive"

AGENT_A_PROMPT = (
    "You are working on a TypeScript Express API project. "
    "Add OAuth2+PKCE authentication support. Specifically:\n"
    "1. In src/auth/jwt.ts — add an OAuth2 token exchange function\n"
    "2. In src/auth/routes.ts — add a GET /auth/oauth2/callback endpoint\n"
    "3. In src/auth/middleware.ts — support both JWT and OAuth2 tokens\n"
    "4. In src/config/env.ts — add OAUTH_CLIENT_ID and OAUTH_SECRET to required vars\n"
    "5. In .env.example — document the new OAuth2 environment variables\n"
    "Important: passport-oauth2 v3.x does NOT support PKCE. Use v4.x.\n"
    "Make minimal, focused edits. Do not create new files."
)

AGENT_B_PROMPT = (
    "You are working on a TypeScript Express API project. "
    "Add task assignment with email notifications. Specifically:\n"
    "1. In src/api/tasks.ts — add POST /api/tasks/:id/assign endpoint\n"
    "2. In src/models/task.ts — add assigneeId and assignedAt fields to Task interface\n"
    "3. In src/services/notification.ts — implement sendAssignmentNotification using nodemailer\n"
    "4. In src/auth/middleware.ts — add a requireRole('admin') middleware function\n"
    "5. In src/config/env.ts — add SMTP_HOST, SMTP_PORT, SMTP_USER to required vars\n"
    "Make minimal, focused edits. Do not create new files."
)


def _run_claude_agent(
    prompt: str,
    cwd: Path,
    user: str,
    state_file: Path,
    base_url: str,
) -> subprocess.CompletedProcess:
    """Run claude -p with Overmind plugin and env overrides."""
    env = {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": "3",
    }
    return subprocess.run(
        [
            "claude", "-p", prompt,
            "--max-turns", "10",
            "--plugin-dir", str(PLUGIN_DIR),
        ],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


@pytest.mark.e2e_live
class TestLiveAgents:
    """Run real Claude CLI agents in parallel against Hive scaffold."""

    def test_parallel_agents(self, claude_cli, server, base_url, hive_repo, tmp_path):
        state_a = tmp_path / "state_a.json"
        state_b = tmp_path / "state_b.json"

        # Run both agents in parallel via threads
        results = {}

        def run_agent(name, prompt, state_file):
            results[name] = _run_claude_agent(
                prompt, hive_repo, name, state_file, base_url,
            )

        thread_a = threading.Thread(target=run_agent, args=("agent_a", AGENT_A_PROMPT, state_a))
        thread_b = threading.Thread(target=run_agent, args=("agent_b", AGENT_B_PROMPT, state_b))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=180)
        thread_b.join(timeout=180)

        # Check agents completed
        assert "agent_a" in results, "Agent A did not complete"
        assert "agent_b" in results, "Agent B did not complete"

        proc_a = results["agent_a"]
        proc_b = results["agent_b"]

        if proc_a.returncode != 0:
            warnings.warn(f"Agent A exited with code {proc_a.returncode}: {proc_a.stderr[:500]}")
        if proc_b.returncode != 0:
            warnings.warn(f"Agent B exited with code {proc_b.returncode}: {proc_b.stderr[:500]}")

        # ── Verify Overmind server state ──

        # Hard: both agents should have pushed at least 1 event
        pull = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "limit": "100",
        })
        assert pull["count"] >= 2, (
            f"Expected >= 2 events from 2 agents, got {pull['count']}"
        )
        users = {e["user"] for e in pull["events"]}
        assert "agent_a" in users, "Agent A events missing from server"
        assert "agent_b" in users, "Agent B events missing from server"

        # Hard: change events should exist
        types = {e["type"] for e in pull["events"]}
        assert "change" in types, f"Expected 'change' type events, got: {types}"

        # Report
        report = _api_get(base_url, "/api/report", {"repo_id": REPO_ID})
        assert report["unique_users"] >= 2
        print(f"\n📊 Report: {report['total_pushes']} pushes, "
              f"{report['unique_users']} users, "
              f"types: {report['events_by_type']}")

        # Soft: polymorphism detection (agents may not overlap)
        graph = _api_get(base_url, "/api/report/graph", {"repo_id": REPO_ID})
        if graph.get("polymorphisms"):
            poly_scopes = [p["scope"] for p in graph["polymorphisms"]]
            print(f"🔀 Polymorphisms detected: {poly_scopes}")
        else:
            warnings.warn(
                "No polymorphism detected — agents may not have overlapped on auth/*. "
                "This is non-deterministic and acceptable."
            )

        # Soft: auth/* scope should have events from both
        pull_auth = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
        })
        auth_users = {e["user"] for e in pull_auth["events"]}
        if auth_users != {"agent_a", "agent_b"}:
            warnings.warn(
                f"Expected both agents in auth/* scope, got: {auth_users}. "
                "Non-deterministic — agent may not have edited auth files."
            )
        else:
            print("✅ Both agents touched auth/* scope — cross-agent visibility confirmed")
