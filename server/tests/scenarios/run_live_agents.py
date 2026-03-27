#!/usr/bin/env python3
"""Run multiple Claude agents in parallel against a Hive scaffold.

Usage:
  1. Start Overmind server:  cd server && python -m overmind.main
  2. Open dashboard:         http://localhost:7777/dashboard
  3. Run this script:        python server/tests/scenarios/run_live_agents.py [scenario]

Scenarios:
  basic    — 2 agents, simple parallel (default)
  full     — 3 agents in 2 waves, staggered starts, broadcast, high overlap
  stress   — 4 agents, aggressive flush, maximum cross-agent events

Requires: claude CLI installed and authenticated.
"""

import argparse
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

# ============================================================
# Agent Prompts
# ============================================================

PROMPTS = {
    "auth_lead": (
        "You are the AUTH LEAD on a TypeScript Express API project. "
        "Implement OAuth2+PKCE authentication. Tasks:\n"
        "1. src/auth/jwt.ts — add exchangeOAuth2Code() function that calls token endpoint\n"
        "2. src/auth/routes.ts — add GET /auth/oauth2/callback that uses exchangeOAuth2Code\n"
        "3. src/auth/middleware.ts — modify authMiddleware to accept both JWT and OAuth2 tokens\n"
        "4. src/config/env.ts — add OAUTH_CLIENT_ID, OAUTH_SECRET, OAUTH_CALLBACK_URL to required vars\n"
        "5. .env.example — document all new OAuth2 environment variables with example values\n"
        "CRITICAL: passport-oauth2 v3.x does NOT support PKCE. You must use v4.x.\n"
        "Make focused edits. Do not create new files."
    ),
    "task_dev": (
        "You are the TASK FEATURE DEV on a TypeScript Express API project. "
        "Implement task assignment with email notifications. Tasks:\n"
        "1. src/models/task.ts — add assigneeId: string, assignedAt: Date, assignedBy: string to Task interface\n"
        "2. src/api/tasks.ts — add POST /:id/assign endpoint that validates assignee and updates task\n"
        "3. src/services/notification.ts — implement sendAssignmentNotification() using nodemailer with SMTP\n"
        "4. src/auth/middleware.ts — add requireRole(role: string) middleware function for role-based access\n"
        "5. src/config/env.ts — add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS to required vars\n"
        "Make focused edits. Do not create new files."
    ),
    "cache_infra": (
        "You are the CACHE/INFRA engineer on a TypeScript Express API project. "
        "Implement Redis caching layer for performance. Tasks:\n"
        "1. src/services/cache.ts — implement connectCache(), cacheGet(), cacheSet(), cacheDelete() with redis client\n"
        "2. src/config/env.ts — add REDIS_URL, REDIS_TTL_SECONDS to required vars and getEnv()\n"
        "3. src/config/database.ts — add connection pooling config with min/max settings from env\n"
        "4. src/api/tasks.ts — wrap GET / endpoint with cache: check cache first, fallback to DB, cache result\n"
        "5. src/api/users.ts — wrap GET /me with cache using user ID as cache key, 5 min TTL\n"
        "6. src/auth/middleware.ts — cache token verification results for 60 seconds to reduce JWT decode overhead\n"
        "Make focused edits. Do not create new files."
    ),
    "security_audit": (
        "You are the SECURITY AUDITOR on a TypeScript Express API project. "
        "Review and harden the authentication and error handling. Tasks:\n"
        "1. src/auth/middleware.ts — add rate limiting check, add request ID logging, sanitize error messages\n"
        "2. src/auth/jwt.ts — add token refresh logic, validate token audience and issuer fields\n"
        "3. src/utils/errors.ts — add specific error classes: AuthError, ValidationError, RateLimitError\n"
        "4. src/utils/logger.ts — add structured JSON logging with request context (method, path, user)\n"
        "5. src/config/env.ts — add RATE_LIMIT_WINDOW_MS, RATE_LIMIT_MAX_REQUESTS to required vars\n"
        "6. src/api/users.ts — sanitize user input in PATCH /:id, prevent mass assignment\n"
        "Make focused edits. Do not create new files."
    ),
}

# ============================================================
# Scenarios
# ============================================================

SCENARIOS = {
    "basic": {
        "description": "2 agents, simple parallel",
        "waves": [
            {
                "agents": [
                    {"name": "agent_a", "prompt": "auth_lead", "flush_threshold": "3"},
                    {"name": "agent_b", "prompt": "task_dev", "flush_threshold": "3"},
                ],
                "delay_before": 0,
            },
        ],
        "max_turns": "10",
    },
    "full": {
        "description": "3 agents in 2 waves — staggered starts, high overlap on auth/* and config/*",
        "waves": [
            {
                "agents": [
                    {"name": "auth_lead", "prompt": "auth_lead", "flush_threshold": "2"},
                    {"name": "task_dev", "prompt": "task_dev", "flush_threshold": "2"},
                ],
                "delay_before": 0,
            },
            {
                "agents": [
                    {"name": "cache_infra", "prompt": "cache_infra", "flush_threshold": "2"},
                ],
                "delay_before": 30,  # start 30s after wave 1
            },
        ],
        "max_turns": "15",
    },
    "stress": {
        "description": "4 agents, aggressive flush (every 2 edits), maximum cross-agent events",
        "waves": [
            {
                "agents": [
                    {"name": "auth_lead", "prompt": "auth_lead", "flush_threshold": "2"},
                    {"name": "task_dev", "prompt": "task_dev", "flush_threshold": "2"},
                ],
                "delay_before": 0,
            },
            {
                "agents": [
                    {"name": "cache_infra", "prompt": "cache_infra", "flush_threshold": "2"},
                ],
                "delay_before": 20,
            },
            {
                "agents": [
                    {"name": "security_auditor", "prompt": "security_audit", "flush_threshold": "2"},
                ],
                "delay_before": 40,
            },
        ],
        "max_turns": "15",
    },
}

# ============================================================
# Helpers
# ============================================================


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


def run_agent(
    name: str, prompt: str, cwd: Path, state_file: Path,
    flush_threshold: str = "3", max_turns: str = "10",
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "OVERMIND_URL": OVERMIND_URL,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": name,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": flush_threshold,
    }
    return subprocess.run(
        ["claude", "-p", prompt, "--max-turns", max_turns, "--plugin-dir", str(PLUGIN_DIR)],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def launch_agent_thread(
    name: str, prompt_key: str, repo_dir: Path, state_dir: Path,
    results: dict, flush_threshold: str = "3", max_turns: str = "10",
) -> threading.Thread:
    """Create and return (but don't start) an agent thread."""
    prompt = PROMPTS[prompt_key]

    def _run():
        state_file = state_dir / f"state_{name}.json"
        print(f"  [{name}] Starting... (prompt: {prompt_key})")
        t0 = time.time()
        try:
            results[name] = run_agent(name, prompt, repo_dir, state_file, flush_threshold, max_turns)
            elapsed = time.time() - t0
            rc = results[name].returncode
            status = "OK" if rc == 0 else f"EXIT {rc}"
            print(f"  [{name}] Done ({elapsed:.1f}s) — {status}")
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            print(f"  [{name}] TIMEOUT ({elapsed:.1f}s) — events may have been pushed before timeout")
            results[name] = None

    return threading.Thread(target=_run, name=f"agent-{name}")


def print_separator(title: str):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def verify_results(expected_agents: list[str]):
    """Verify Overmind server state and print report."""
    print_separator("Verification")

    pull = api_get("/api/memory/pull", {"repo_id": REPO_ID, "limit": "200"})
    users = {e["user"] for e in pull["events"]}
    types = {e["type"] for e in pull["events"]}
    scopes = set()
    for e in pull["events"]:
        if e.get("scope"):
            scopes.add(e["scope"])
        for f in e.get("files", []):
            parts = f.replace("\\", "/").rsplit("/", 1)
            if len(parts) == 2:
                scopes.add(parts[0] + "/*")

    print(f"  Total events:  {pull['count']}")
    print(f"  Users:         {users}")
    print(f"  Types:         {types}")
    print(f"  Scopes:        {scopes}")

    report = api_get("/api/report", {"repo_id": REPO_ID})
    print(f"  Total pushes:  {report['total_pushes']}")
    print(f"  Unique users:  {report['unique_users']}")
    print(f"  By type:       {report['events_by_type']}")

    graph = api_get("/api/report/graph", {"repo_id": REPO_ID})
    polys = graph.get("polymorphisms", [])
    if polys:
        print(f"  Polymorphisms: {len(polys)}")
        for p in polys:
            print(f"    {p['scope']}: {p['users']}")
    else:
        print(f"  Polymorphisms: none detected")

    # Per-scope breakdown
    print_separator("Scope Breakdown")
    for scope in sorted(scopes):
        scope_pull = api_get("/api/memory/pull", {"repo_id": REPO_ID, "scope": scope, "limit": "50"})
        scope_users = {e["user"] for e in scope_pull["events"]}
        if scope_pull["count"] > 0:
            print(f"  {scope}: {scope_pull['count']} events from {scope_users}")

    # Assertions
    print_separator("Checks")
    ok = True

    if pull["count"] < len(expected_agents):
        print(f"  FAIL: Expected >= {len(expected_agents)} events, got {pull['count']}")
        ok = False

    for agent in expected_agents:
        if agent in users:
            print(f"  OK: {agent} pushed events")
        else:
            print(f"  FAIL: {agent} events missing")
            ok = False

    if "change" in types:
        print(f"  OK: 'change' type events present")
    else:
        print(f"  FAIL: no 'change' type events")
        ok = False

    if polys:
        print(f"  OK: {len(polys)} polymorphism(s) detected")
    else:
        print(f"  WARN: no polymorphisms (agents may not have overlapped enough)")

    cross_agent_scopes = [s for s in scopes if len([
        e for e in pull["events"]
        if e.get("scope") == s or any(s.replace("/*", "/") in f for f in e.get("files", []))
    ]) > 0]

    print()
    if ok:
        print("  ALL CHECKS PASSED")
    else:
        print("  SOME CHECKS FAILED")

    return ok


# ============================================================
# Main
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="Run multi-agent Overmind test")
    parser.add_argument("scenario", nargs="?", default="basic", choices=SCENARIOS.keys(),
                        help="Test scenario (default: basic)")
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]

    # 1. Prerequisites
    if not shutil.which("claude"):
        print("ERROR: claude CLI not found. Install Claude Code first.")
        sys.exit(1)

    if not check_server():
        print(f"ERROR: Overmind server not running at {OVERMIND_URL}")
        print("Start it first:  cd server && python -m overmind.main")
        sys.exit(1)

    print(f"Server:    {OVERMIND_URL}")
    print(f"Dashboard: {OVERMIND_URL}/dashboard")
    print(f"Scenario:  {args.scenario} — {scenario['description']}")

    total_agents = sum(len(w["agents"]) for w in scenario["waves"])
    total_waves = len(scenario["waves"])
    print(f"Agents:    {total_agents} in {total_waves} wave(s)")
    print()

    # 2. Create Hive scaffold
    tmp_dir = Path(tempfile.mkdtemp(prefix="hive_"))
    repo_dir = create_hive_repo(tmp_dir)
    state_dir = tmp_dir / "states"
    state_dir.mkdir()
    print(f"Scaffold:  {repo_dir}")

    # 3. Run waves
    results = {}
    all_agent_names = []
    max_turns = scenario.get("max_turns", "10")

    for wave_idx, wave in enumerate(scenario["waves"]):
        delay = wave.get("delay_before", 0)

        if delay > 0:
            print_separator(f"Wave {wave_idx + 1} — waiting {delay}s for cross-agent events to accumulate")
            # Print live event count during wait
            for i in range(delay):
                if i % 10 == 0 and i > 0:
                    try:
                        pull = api_get("/api/memory/pull", {"repo_id": REPO_ID, "limit": "200"})
                        print(f"    ... {pull['count']} events on server so far ({i}s)")
                    except Exception:
                        pass
                time.sleep(1)
        else:
            if wave_idx == 0:
                print_separator(f"Wave {wave_idx + 1}")

        agent_names = [a["name"] for a in wave["agents"]]
        print(f"  Launching: {', '.join(agent_names)}")
        print()

        threads = []
        for agent_cfg in wave["agents"]:
            name = agent_cfg["name"]
            all_agent_names.append(name)
            t = launch_agent_thread(
                name=name,
                prompt_key=agent_cfg["prompt"],
                repo_dir=repo_dir,
                state_dir=state_dir,
                results=results,
                flush_threshold=agent_cfg.get("flush_threshold", "3"),
                max_turns=max_turns,
            )
            threads.append(t)

        for t in threads:
            t.start()

        # If not last wave, don't join yet — let them run while next wave starts
        if wave_idx == len(scenario["waves"]) - 1:
            # Last wave — wait for all
            for t in threads:
                t.join(timeout=320)
        else:
            # Store threads to join later
            scenario["waves"][wave_idx]["_threads"] = threads

    # Join any remaining threads from earlier waves
    for wave in scenario["waves"][:-1]:
        for t in wave.get("_threads", []):
            if t.is_alive():
                t.join(timeout=320)

    # 4. Agent status
    print()
    for name in all_agent_names:
        r = results.get(name)
        if r is None:
            print(f"  [{name}] Timed out (events may still have been pushed)")
        elif r.returncode != 0:
            print(f"  [{name}] stderr: {r.stderr[:300]}")

    # 5. Verify
    ok = verify_results(all_agent_names)

    print()
    print(f"Dashboard: {OVERMIND_URL}/dashboard")
    print(f"Scaffold:  {repo_dir}")
    print("(delete manually when done)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
