#!/usr/bin/env python3
"""Run two Claude agents in parallel against a Hive scaffold.

Usage:
  1. Start Overmind server:  cd server && python -m overmind.main
  2. Open dashboard:         http://localhost:7777/dashboard
  3. Run this script:        python server/tests/scenarios/run_live_agents.py

Requires: claude CLI installed and authenticated.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parents[1]
PLUGIN_DIR = SERVER_DIR.parent / "plugin"

sys.path.insert(0, str(SERVER_DIR))
from tests.fixtures.scaffold_hive import create_hive_repo

OVERMIND_URL = os.environ.get("OVERMIND_URL", "http://localhost:7777")
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


def api_get(path: str, params: dict | None = None) -> dict:
    url = f"{OVERMIND_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def check_server():
    try:
        api_get("/api/repos")
        return True
    except Exception:
        return False


def run_agent(name: str, prompt: str, cwd: Path, state_file: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "OVERMIND_URL": OVERMIND_URL,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": name,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": "3",
    }
    return subprocess.run(
        ["claude", "-p", prompt, "--max-turns", "10", "--plugin-dir", str(PLUGIN_DIR)],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def main():
    # 1. Check prerequisites
    if not shutil.which("claude"):
        print("ERROR: claude CLI not found. Install Claude Code first.")
        sys.exit(1)

    if not check_server():
        print(f"ERROR: Overmind server not running at {OVERMIND_URL}")
        print("Start it first:  cd server && python -m overmind.main")
        sys.exit(1)

    print(f"Server: {OVERMIND_URL}")
    print(f"Dashboard: {OVERMIND_URL}/dashboard")
    print()

    # 2. Create Hive scaffold
    tmp_dir = Path(tempfile.mkdtemp(prefix="hive_"))
    repo_dir = create_hive_repo(tmp_dir)
    print(f"Hive scaffold: {repo_dir}")
    print()

    state_dir = tmp_dir / "states"
    state_dir.mkdir()

    # 3. Run agents in parallel
    print("=" * 60)
    print("Starting 2 agents in parallel...")
    print("  Agent A: OAuth2+PKCE authentication")
    print("  Agent B: Task assignment + notifications")
    print("=" * 60)
    print()
    print("Watch the dashboard for live updates!")
    print()

    results = {}

    def _run(name, prompt):
        state_file = state_dir / f"state_{name}.json"
        print(f"  [{name}] Starting...")
        t0 = time.time()
        try:
            results[name] = run_agent(name, prompt, repo_dir, state_file)
            elapsed = time.time() - t0
            rc = results[name].returncode
            status = "OK" if rc == 0 else f"EXIT {rc}"
            print(f"  [{name}] Done ({elapsed:.1f}s) — {status}")
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            print(f"  [{name}] TIMEOUT ({elapsed:.1f}s) — agent took too long, but events may have been pushed")
            results[name] = None

    thread_a = threading.Thread(target=_run, args=("agent_a", AGENT_A_PROMPT))
    thread_b = threading.Thread(target=_run, args=("agent_b", AGENT_B_PROMPT))

    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=320)
    thread_b.join(timeout=320)

    print()

    # 4. Print agent status
    for name in ["agent_a", "agent_b"]:
        r = results.get(name)
        if r is None:
            print(f"  [{name}] Timed out (events may still have been pushed)")
        elif r.returncode != 0:
            print(f"  [{name}] stderr: {r.stderr[:300]}")

    # 5. Verify server state
    print()
    print("=" * 60)
    print("Verification")
    print("=" * 60)

    pull = api_get("/api/memory/pull", {"repo_id": REPO_ID, "limit": "100"})
    users = {e["user"] for e in pull["events"]}
    types = {e["type"] for e in pull["events"]}
    print(f"  Events: {pull['count']}")
    print(f"  Users:  {users}")
    print(f"  Types:  {types}")

    report = api_get("/api/report", {"repo_id": REPO_ID})
    print(f"  Pushes: {report['total_pushes']}")
    print(f"  By type: {report['events_by_type']}")

    graph = api_get("/api/report/graph", {"repo_id": REPO_ID})
    polys = graph.get("polymorphisms", [])
    if polys:
        print(f"  Polymorphisms: {len(polys)}")
        for p in polys:
            print(f"    {p['scope']}: {p['users']}")
    else:
        print("  Polymorphisms: none detected")

    print()

    # 5. Assertions
    ok = True
    if pull["count"] < 2:
        print("FAIL: Expected >= 2 events")
        ok = False
    if "agent_a" not in users:
        print("FAIL: agent_a events missing")
        ok = False
    if "agent_b" not in users:
        print("FAIL: agent_b events missing")
        ok = False
    if "change" not in types:
        print("FAIL: no 'change' type events")
        ok = False

    if ok:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")

    print()
    print(f"Dashboard: {OVERMIND_URL}/dashboard")
    print(f"Scaffold kept at: {repo_dir}")
    print("(delete manually when done)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
