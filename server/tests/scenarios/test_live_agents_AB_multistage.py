# server/tests/scenarios/test_live_agents_AB_multistage.py
"""A/B Test - Multi-Stage Failure Cascade (Node.js scaffold).

A Node.js app with npm install + config.toml parsing across 4 source files.
Each module reads a different config section and throws a raw JS exception
(TypeError, ReferenceError, assertion) when the section is missing/malformed.

Failure cascade:
  Stage 1: npm install (succeeds but adds realistic delay/noise)
  Stage 2: start.sh → TypeError: Cannot read properties of undefined ('host')
            (in src/network.js — config.server is undefined)
  Stage 3: fix [server] → ENOENT: no such file './keys/hmac.key'
            (in src/auth.js — config.auth.key_file points to wrong path)
  Stage 4: fix key_file → TypeError: Cannot read properties of undefined ('store')
            (in src/session.js — config.session is undefined)
  Stage 5: fix [session] → AssertionError: ttl must be a positive integer
            (in src/session.js — ttl_seconds must be positive int)
  Stage 6: fix ttl → TypeError: handler.paths is not iterable
            (in src/routes.js — config.routes is undefined)
  Stage 7: fix [routes] with paths array → server starts OK

Pioneer must iterate: run → fail → read source → fix → run → fail → ...
Student sees Pioneer's events (many config edits, many source reads) → investigates first.
Naive repeats Pioneer's path.

Expected:
  Pioneer: 5-7 start.sh runs, reads multiple src/ files
  Student: 1-3 start.sh runs (fixes all before first run or after single run)
  Naive:   similar to Pioneer (5-7 runs)
"""

import json
import os
import re
import shutil
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
OVERMIND_PORT = int(os.environ.get("TEST_OVERMIND_PORT", "17996"))
REPO_ID = "github.com/test/hive-multistage"


# ============================================================
# Scaffold: multi-module app with cascading failures
# ============================================================

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT create new files. Do NOT modify files under src/ or any .js/.json files.
- The start script handles npm install automatically.
""",
    # ── config.toml: deliberately incomplete — has [database] and [auth] but
    # is missing [server], [session], [routes]; auth.key_file points to wrong
    # path (./keys/hmac.key instead of ./hmac.key). Agent must discover each
    # gap by running the app and reading the crash source. ──
    "config.toml": """# Hive Server Configuration

[database]
url = "postgres://localhost:5432/hive"

[auth]
key_file = "./keys/hmac.key"
algorithm = "HS256"
""",
    # ── The actual HMAC key file lives at project root, not ./keys/ ──
    # 64 hex chars — valid, but config points to wrong path (./keys/hmac.key)
    "hmac.key": "4a7f3c9e1b2d8a0f5e6c7d3b9a1f0e2c4d5b6a8f7e3c1d9b0a2f4e6c8d7b5a3f",
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "[start.sh] Installing dependencies..."
npm install 2>&1
echo "[start.sh] Starting Hive server..."
node src/server.js 2>&1
""",
    "package.json": """{
  "name": "hive-server",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "node src/server.js"
  },
  "dependencies": {
    "@iarna/toml": "2.2.5",
    "assert": "2.1.0"
  }
}
""",
    # ── Main entry point: requires each init module sequentially ──
    "src/server.js": """'use strict';
const fs = require('fs');
const toml = require('@iarna/toml');

const configRaw = fs.readFileSync('config.toml', 'utf8');
const config = toml.parse(configRaw);

// Phase 1: network binding
const network = require('./network');
const { host, port } = network.init(config);

// Phase 2: auth keys
const auth = require('./auth');
auth.init(config);

// Phase 3: session store
const session = require('./session');
session.init(config);

// Phase 4: route table
const routes = require('./routes');
routes.init(config);

// All checks passed — print success and exit
console.log('[Hive] Configuration validated successfully');
console.log(`[Hive] Server running on http://${host}:${port}`);
process.exit(0);
""",
    # ── Stage 1: config.server is undefined → TypeError on .host access ──
    "src/network.js": """'use strict';
/**
 * Network subsystem — binds to host:port from [server] config section.
 */
function init(config) {
  const host = config.server.host;           // TypeError if config.server undefined
  const port = Number(config.server.port);   // same
  if (!host || typeof host !== 'string') {
    throw new TypeError('Expected server.host to be a non-empty string');
  }
  if (isNaN(port) || port < 1 || port > 65535) {
    throw new RangeError(`Port out of valid range: ${port}`);
  }
  return { host, port };
}
module.exports = { init };
""",
    # ── Stage 2-3: auth reads key_file from disk, validates length ──
    "src/auth.js": """'use strict';
const fs = require('fs');
const path = require('path');
/**
 * Auth subsystem — loads HMAC signing key from disk.
 * Expects config.auth.key_file to point to a readable file
 * containing a 64-character hex key.
 */
function init(config) {
  const keyPath = path.resolve(config.auth.key_file);  // resolves relative to cwd
  const raw = fs.readFileSync(keyPath, 'utf8').trim();  // ENOENT if path wrong
  if (raw.length !== 64) {
    throw new RangeError(
      `Invalid key length: expected 64 characters, got ${raw.length} (file: ${keyPath})`
    );
  }
  if (!/^[0-9a-fA-F]+$/.test(raw)) {
    throw new TypeError('Key must be hexadecimal');
  }
  return { key: raw, algorithm: config.auth.algorithm };
}
module.exports = { init };
""",
    # ── Stage 4-5: session config missing entirely, then ttl validation ──
    "src/session.js": """'use strict';
const assert = require('assert');
/**
 * Session subsystem — configures session store from [session] section.
 */
function init(config) {
  const store = config.session.store;         // TypeError if config.session undefined
  const ttl   = config.session.ttl_seconds;   // same
  assert.ok(
    Number.isInteger(ttl) && ttl > 0,
    `ttl must be a positive integer, got: ${JSON.stringify(ttl)}`
  );
  const validStores = ['memory', 'redis', 'file'];
  if (!validStores.includes(store)) {
    throw new RangeError(`Unknown session store "${store}". Valid: ${validStores.join(', ')}`);
  }
  return { store, ttl };
}
module.exports = { init };
""",
    # ── Stage 6-7: routes config missing, then paths must be array ──
    "src/routes.js": """'use strict';
/**
 * Route table — loads API path definitions from [routes] section.
 */
function init(config) {
  const handler = config.routes;              // undefined if [routes] missing
  for (const r of handler.paths) {            // TypeError: handler.paths is not iterable
    if (typeof r !== 'string' || !r.startsWith('/')) {
      throw new SyntaxError(`Invalid route: "${r}" — must start with /`);
    }
  }
  if (!handler.paths.length) {
    throw new RangeError('routes.paths must not be empty');
  }
  return handler;
}
module.exports = { init };
""",
}


def create_scaffold(base_dir: Path) -> Path:
    repo_dir = base_dir / "hive-multi"
    repo_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in SCAFFOLD_FILES.items():
        fp = repo_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial: Hive multi-stage scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-multistage.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


# ============================================================
# Infrastructure (same as single-stage test)
# ============================================================

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
    with urlopen(Request(url, method="GET"), timeout=10) as resp:
        return json.loads(resp.read())


# ============================================================
# Agent runner with JSONL capture
# ============================================================

# Model selection via env var: AGENT_MODEL=haiku|sonnet|opus (default: system default)
AGENT_MODEL = os.environ.get("AGENT_MODEL", "")

SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, read the source file that crashed to understand what it expects, "
    "fix config.toml accordingly, then retry. "
    "You may only edit config.toml — do not modify any .js or .json files."
)


def _run_agent(
    prompt: str, cwd: Path, user: str, state_file: Path,
    base_url: str | None, max_turns: int = 25, with_overmind: bool = True,
) -> tuple[dict, list[dict]]:
    env = {**os.environ}
    cmd = [
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    if AGENT_MODEL:
        cmd.extend(["--model", AGENT_MODEL])

    if with_overmind and base_url:
        env.update({
            "OVERMIND_URL": base_url,
            "OVERMIND_REPO_ID": REPO_ID,
            "OVERMIND_USER": user,
            "OVERMIND_STATE_FILE": str(state_file),
            "OVERMIND_FLUSH_THRESHOLD": "1",
        })
        cmd.extend(["--plugin-dir", str(PLUGIN_DIR)])

    proc = subprocess.run(
        cmd, cwd=str(cwd), env=env,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=600,
    )

    events = []
    result_event = {}
    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
            events.append(evt)
            if evt.get("type") == "result":
                result_event = evt
        except json.JSONDecodeError:
            pass

    return result_event, events


# ============================================================
# JSONL Analysis
# ============================================================

def analyze_conversation(events: list[dict]) -> dict:
    tool_uses = []
    bash_commands = []
    edited_files = []
    read_files = []
    server_runs = 0
    saw_error = False
    saw_server_running = False

    for evt in events:
        if evt.get("type") == "assistant":
            msg = evt.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue
                tool = block.get("name", "")
                inp = block.get("input", {})
                tool_uses.append((tool, inp))

                if tool == "Bash":
                    cmd = inp.get("command", "")
                    bash_commands.append(cmd)
                    if ("start.sh" in cmd
                        or ("server.js" in cmd and "node" in cmd)
                        or "npm run dev" in cmd
                        or "npm start" in cmd):
                        server_runs += 1
                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    edited_files.append(fp)
                elif tool == "Read":
                    fp = inp.get("file_path", "").replace("\\", "/")
                    read_files.append(fp)

        elif evt.get("type") == "user":
            result = evt.get("tool_use_result")
            if result:
                txt = result if isinstance(result, str) else str(result.get("stdout", "")) + str(result.get("stderr", ""))
                if "Error" in txt or "Traceback" in txt or "STARTUP FAILED" in txt:
                    saw_error = True
                if "[Hive] Server running" in txt:
                    saw_server_running = True

            msg = evt.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        content = block.get("content", "")
                        if isinstance(content, str):
                            if "Error" in content or "Traceback" in content:
                                saw_error = True
                            if "[Hive] Server running" in content:
                                saw_server_running = True

    config_edits = [f for f in edited_files if "config.toml" in f]
    src_reads = [f for f in read_files if "/src/" in f or "init_" in f]
    src_edits = [f for f in edited_files if "/src/" in f]

    # Extract just filenames for readability
    src_read_names = list(dict.fromkeys(
        f.rsplit("/", 1)[-1] for f in src_reads
    ))

    return {
        "total_tool_uses": len(tool_uses),
        "server_run_attempts": server_runs,
        "saw_error": saw_error,
        "saw_server_running": saw_server_running,
        "config_toml_edits": len(config_edits),
        "src_file_reads": len(src_reads),
        "src_files_read": src_read_names,
        "src_file_edits": len(src_edits),
        "edited_files": [f.rsplit("/", 1)[-1] for f in edited_files],
        "tools_used": list({t for t, _ in tool_uses}),
    }


def check_config(repo_dir: Path) -> dict:
    path = repo_dir / "config.toml"
    if not path.exists():
        return {"exists": False}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    content = path.read_text(encoding="utf-8")
    try:
        config = tomllib.loads(content)
    except Exception:
        return {"exists": True, "parse_error": True}

    # Check auth.key_file points to a valid file with 64 hex chars
    key_file = config.get("auth", {}).get("key_file", "")
    key_ok = False
    if key_file:
        kp = repo_dir / key_file
        if kp.exists():
            kc = kp.read_text(encoding="utf-8").strip()
            key_ok = len(kc) == 64 and all(c in "0123456789abcdefABCDEF" for c in kc)

    checks = {
        "server_ok": (
            "server" in config
            and "host" in config.get("server", {})
            and "port" in config.get("server", {})
        ),
        "auth_ok": (
            "auth" in config
            and key_ok
        ),
        "session_ok": (
            "session" in config
            and isinstance(config.get("session", {}).get("ttl_seconds", None), int)
            and config.get("session", {}).get("ttl_seconds", 0) > 0
            and config.get("session", {}).get("store", "") in ("memory", "redis", "file")
        ),
        "routes_ok": (
            "routes" in config
            and isinstance(config.get("routes", {}).get("paths", None), list)
            and len(config.get("routes", {}).get("paths", [])) > 0
        ),
    }
    checks["all_ok"] = all(checks.values())
    checks["sections_fixed"] = sum(1 for v in checks.values() if v and v is not True)
    return checks


def check_src_modified(repo_dir: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only", "--", "src/"],
        cwd=str(repo_dir), capture_output=True, text=True, timeout=5,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def claude_cli():
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("ab_multi_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=OVERMIND_PORT)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{OVERMIND_PORT}"


@pytest.fixture(scope="module")
def repo_dirs(tmp_path_factory):
    base = tmp_path_factory.mktemp("ab_multi_repos")
    return {
        name: create_scaffold(base / name)
        for name in ("agent_pioneer", "agent_student", "agent_naive")
    }


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("ab_multi_states")


# ============================================================
# Test
# ============================================================

@pytest.mark.e2e_live
class TestMultiStageAB:

    def test_multistage_ab(
        self, claude_cli, server, base_url, repo_dirs, state_dir,
    ):
        # ── Phase 1: Pioneer ──
        print("\n" + "=" * 70)
        print("  Phase 1: Pioneer (multi-stage discovery)")
        print("=" * 70)

        t0 = time.time()
        p_result, p_events = _run_agent(
            SHARED_PROMPT, repo_dirs["agent_pioneer"], "agent_pioneer",
            state_dir / "state_pioneer.json", base_url, with_overmind=True,
        )
        p_time = time.time() - t0
        p_analysis = analyze_conversation(p_events)

        print(f"  Time: {p_time:.1f}s  Turns: {p_result.get('num_turns', '?')}")
        print(f"  start.sh runs: {p_analysis['server_run_attempts']}")
        print(f"  config edits:  {p_analysis['config_toml_edits']}")
        print(f"  src/ reads:    {p_analysis['src_file_reads']} ({p_analysis['src_files_read']})")
        print(f"  src/ edits:    {p_analysis['src_file_edits']}")
        print(f"  saw error:     {p_analysis['saw_error']}")
        print(f"  server OK:     {p_analysis['saw_server_running']}")
        print(f"  config state:  {check_config(repo_dirs['agent_pioneer'])}")

        # Verify Pioneer pushed events
        p_server = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "limit": "50",
        })
        p_pushed = [e for e in p_server["events"] if e["user"] == "agent_pioneer"]
        assert len(p_pushed) >= 1, "Pioneer must push events"
        print(f"  Overmind events: {len(p_pushed)}")

        # ── Phase 2: Student vs Naive ──
        print("\n" + "=" * 70)
        print("  Phase 2: Student (+Overmind) vs Naive (Control)")
        print("=" * 70)

        # Show what Student will receive
        pull_preview = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "20",
        })
        print(f"\n  Events for Student's pull: {pull_preview['count']}")
        for e in pull_preview["events"][:5]:
            print(f"    [{e['user']}] {e['result'][:70]}")
        print(f"  Events for Naive: 0\n")

        ab_results = {}
        ab_events = {}
        ab_times = {}

        def run_ab(name: str, overmind: bool):
            t = time.time()
            ab_results[name], ab_events[name] = _run_agent(
                SHARED_PROMPT, repo_dirs[name], name,
                state_dir / f"state_{name}.json", base_url,
                with_overmind=overmind,
            )
            ab_times[name] = time.time() - t

        ta = threading.Thread(target=run_ab, args=("agent_student", True))
        tb = threading.Thread(target=run_ab, args=("agent_naive", False))
        ta.start(); tb.start()
        ta.join(timeout=600); tb.join(timeout=600)

        assert "agent_student" in ab_results, "Student didn't complete"
        assert "agent_naive" in ab_results, "Naive didn't complete"

        s_analysis = analyze_conversation(ab_events["agent_student"])
        n_analysis = analyze_conversation(ab_events["agent_naive"])

        # ── Phase 3: Comparison ──
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison")
        print("=" * 70)

        metrics = [
            "server_run_attempts", "config_toml_edits",
            "src_file_reads", "src_file_edits",
            "saw_error", "saw_server_running", "total_tool_uses",
        ]

        print(f"\n  {'Metric':<25} {'Pioneer':>10} {'Student':>10} {'Naive':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for m in metrics:
            print(f"  {m:<25} {str(p_analysis[m]):>10} {str(s_analysis[m]):>10} {str(n_analysis[m]):>10}")
        print(f"  {'time (s)':<25} {p_time:>10.1f} {ab_times['agent_student']:>10.1f} {ab_times['agent_naive']:>10.1f}")
        print(f"  {'turns':<25} {str(p_result.get('num_turns','?')):>10} "
              f"{str(ab_results['agent_student'].get('num_turns','?')):>10} "
              f"{str(ab_results['agent_naive'].get('num_turns','?')):>10}")

        print(f"\n  src/ files read:")
        print(f"    Pioneer: {p_analysis['src_files_read']}")
        print(f"    Student: {s_analysis['src_files_read']}")
        print(f"    Naive:   {n_analysis['src_files_read']}")

        print(f"\n  Edited files:")
        print(f"    Pioneer: {p_analysis['edited_files']}")
        print(f"    Student: {s_analysis['edited_files']}")
        print(f"    Naive:   {n_analysis['edited_files']}")

        # ── Phase 4: Pull Impact ──
        print("\n" + "=" * 70)
        print("  Phase 4: Pull Impact")
        print("=" * 70)

        pull_all = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "limit": "100",
        })
        all_users = {e["user"] for e in pull_all["events"]}

        assert "agent_pioneer" in all_users, "Pioneer events missing"
        print("  PASS: Pioneer pushed events")

        assert "agent_student" in all_users, "Student events missing"
        print("  PASS: Student pushed events (Overmind active)")

        naive_events = [e for e in pull_all["events"] if e["user"] == "agent_naive"]
        assert len(naive_events) == 0, f"Naive has {len(naive_events)} events"
        print("  PASS: Naive has 0 events (isolated)")

        student_pull_count = len([e for e in pull_preview["events"]
                                  if e["user"] == "agent_pioneer"])
        print(f"  PASS: Student received {student_pull_count} event(s) from Pioneer")

        # ── Phase 5: Key Result ──
        print("\n" + "=" * 70)
        print("  Phase 5: KEY RESULT - start.sh attempts")
        print("=" * 70)

        p_runs = p_analysis["server_run_attempts"]
        s_runs = s_analysis["server_run_attempts"]
        n_runs = n_analysis["server_run_attempts"]

        print(f"\n  Pioneer: {p_runs} start.sh runs (baseline - discovering all stages)")
        print(f"  Student: {s_runs} start.sh runs (with Overmind)")
        print(f"  Naive:   {n_runs} start.sh runs (without Overmind)")

        if s_runs < n_runs:
            print(f"\n  >> Student needed {n_runs - s_runs} FEWER attempts than Naive")
            print(f"  >> Overmind lesson absorption confirmed")
        elif s_runs == n_runs:
            print(f"\n  >> Same attempt count (non-deterministic)")
        else:
            print(f"\n  >> Naive was better (non-deterministic)")

        p_cfg = check_config(repo_dirs["agent_pioneer"])
        s_cfg = check_config(repo_dirs["agent_student"])
        n_cfg = check_config(repo_dirs["agent_naive"])
        print(f"\n  Config status:")
        print(f"    Pioneer: {p_cfg}")
        print(f"    Student: {s_cfg}")
        print(f"    Naive:   {n_cfg}")

        # ── Save JSONL ──
        for name, evts in [("agent_pioneer", p_events),
                           ("agent_student", ab_events.get("agent_student", [])),
                           ("agent_naive", ab_events.get("agent_naive", []))]:
            jsonl_path = state_dir / f"conversation_{name}.jsonl"
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for e in evts:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

        print(f"\n  JSONL saved to: {state_dir}")
