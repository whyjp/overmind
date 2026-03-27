# server/tests/scenarios/test_live_agents_AB_complex.py
"""A/B Test - Complex 8-Stage Failure Cascade.

A Node.js microservice with 8 independent subsystems, each reading a different
config.toml section. Errors are raw JS exceptions with NO helpful hints.
Some stages have subtle traps:

  Stage 1: [server] missing          -> TypeError in src/boot/network.js
  Stage 2: [server].port is string   -> RangeError (port must be integer in TOML)
  Stage 3: auth.key_file wrong path  -> ENOENT in src/boot/auth.js (file is at ./hmac.key, not ./keys/hmac.key)
  Stage 4: [security] missing        -> TypeError in src/boot/security.js
  Stage 5: [security].secret < 32ch  -> AssertionError in src/boot/security.js
  Stage 6: [cache] missing           -> TypeError in src/boot/cache.js
  Stage 7: [cache].url not redis://  -> ValueError in src/boot/cache.js
  Stage 8: [session] missing         -> TypeError in src/boot/session.js
  Stage 9: [cors] missing            -> TypeError in src/middleware/cors.js
  Stage 10: [cors].origins not array -> TypeError in src/middleware/cors.js
  Stage 11: [ratelimit] missing      -> TypeError in src/middleware/ratelimit.js
  Stage 12: [logging] missing        -> TypeError in src/observability/logging.js
  Stage 13: [metrics] missing        -> TypeError in src/observability/metrics.js
  Stage 14: [metrics].port == server.port -> Error "metrics port must differ"
  ALL OK -> server starts

Pioneer: 8-14 start.sh runs (each error reveals one issue)
Student: 1-3 start.sh runs (reads all boot/* middleware/* observability/* first)
Naive:   8-14 start.sh runs (same as Pioneer)

EXCLUDED from normal test runs. Run with:
  AGENT_MODEL=haiku uv run pytest tests/scenarios/test_live_agents_AB_complex.py -m e2e_live -s
"""

import json
import os
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
OVERMIND_PORT = 17995
REPO_ID = "github.com/test/hive-complex"

# Model selection: AGENT_MODEL=haiku|sonnet|opus
AGENT_MODEL = os.environ.get("AGENT_MODEL", "")

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Microservice

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT modify any .js or .json file.
- Do NOT create new files (except config.toml edits).
""",
    # ---- Config: only [database] and [auth] present, everything else missing ----
    "config.toml": """# Hive Microservice Configuration

[database]
url = "postgres://localhost:5432/hive"

[auth]
key_file = "./keys/hmac.key"
algorithm = "HS256"
""",
    # The actual key file is at project root, NOT in ./keys/
    "hmac.key": "4a7f3c9e1b2d8a0f5e6c7d3b9a1f0e2c4d5b6a8f7e3c1d9b0a2f4e6c8d7b5a3f",
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "[start.sh] Installing dependencies..."
npm install --silent 2>&1
echo "[start.sh] Starting Hive microservice..."
node src/server.js 2>&1
""",
    "package.json": """{
  "name": "hive-microservice",
  "version": "2.0.0",
  "private": true,
  "scripts": { "start": "node src/server.js" },
  "dependencies": { "@iarna/toml": "2.2.5" }
}
""",
    # ==== MAIN ENTRY: loads config, boots each subsystem sequentially ====
    "src/server.js": """'use strict';
const fs = require('fs');
const toml = require('@iarna/toml');

const raw = fs.readFileSync('config.toml', 'utf8');
const config = toml.parse(raw);

// Boot subsystems in order - each may throw
require('./boot/network').init(config);
require('./boot/auth').init(config);
require('./boot/security').init(config);
require('./boot/cache').init(config);
require('./boot/session').init(config);

// Middleware
require('./middleware/cors').init(config);
require('./middleware/ratelimit').init(config);

// Observability
require('./observability/logging').init(config);
require('./observability/metrics').init(config);

// All passed
const { host, port } = config.server;
console.log('[Hive] All 8 subsystems initialized');
console.log(`[Hive] Server running on http://${host}:${port}`);
process.exit(0);
""",
    # ==== BOOT: network ====
    "src/boot/network.js": """'use strict';
// Binds to host:port from [server] section
function init(config) {
  const host = config.server.host;
  const port = config.server.port;
  if (typeof port !== 'number' || !Number.isInteger(port)) {
    throw new RangeError(
      'server.port must be an integer, got ' + typeof port + ': ' + JSON.stringify(port)
    );
  }
  if (port < 1024 || port > 49151) {
    throw new RangeError('server.port must be between 1024-49151, got ' + port);
  }
  if (typeof host !== 'string' || !host) {
    throw new TypeError('server.host must be a non-empty string');
  }
}
module.exports = { init };
""",
    # ==== BOOT: auth (key_file path trap) ====
    "src/boot/auth.js": """'use strict';
const fs = require('fs');
const path = require('path');
// Loads HMAC key from config.auth.key_file
// Key must be exactly 64 hex characters
function init(config) {
  const keyPath = path.resolve(config.auth.key_file);
  const raw = fs.readFileSync(keyPath, 'utf8').trim();
  if (raw.length !== 64) {
    throw new RangeError('Auth key must be 64 hex chars, got ' + raw.length);
  }
  if (!/^[0-9a-fA-F]+$/.test(raw)) {
    throw new TypeError('Auth key must be hexadecimal');
  }
}
module.exports = { init };
""",
    # ==== BOOT: security (api_secret >= 32 chars) ====
    "src/boot/security.js": """'use strict';
const assert = require('assert');
// Reads [security].api_secret - must be >= 32 characters
function init(config) {
  const sec = config.security;
  assert.ok(sec && sec.api_secret, 'security.api_secret is required');
  assert.ok(
    sec.api_secret.length >= 32,
    'security.api_secret must be >= 32 chars, got ' + sec.api_secret.length
  );
  // encryption_algo must be aes-256-gcm or chacha20
  const algo = sec.encryption_algo;
  const valid = ['aes-256-gcm', 'chacha20-poly1305'];
  if (!valid.includes(algo)) {
    throw new RangeError(
      'security.encryption_algo must be one of: ' + valid.join(', ') + ', got: ' + algo
    );
  }
}
module.exports = { init };
""",
    # ==== BOOT: cache (redis URL + ttl) ====
    "src/boot/cache.js": """'use strict';
// Reads [cache] section: url (redis://...) and ttl_seconds (int, 60-86400)
function init(config) {
  const c = config.cache;
  if (!c || !c.url) {
    throw new TypeError('cache.url is required');
  }
  if (!c.url.startsWith('redis://')) {
    throw new TypeError('cache.url must start with redis://, got: ' + c.url);
  }
  const ttl = c.ttl_seconds;
  if (typeof ttl !== 'number' || !Number.isInteger(ttl)) {
    throw new TypeError('cache.ttl_seconds must be an integer');
  }
  if (ttl < 60 || ttl > 86400) {
    throw new RangeError('cache.ttl_seconds must be 60-86400, got ' + ttl);
  }
}
module.exports = { init };
""",
    # ==== BOOT: session (store type + ttl) ====
    "src/boot/session.js": """'use strict';
// Reads [session]: store (memory|redis|file), ttl_seconds (int > 0), secret (string)
function init(config) {
  const s = config.session;
  if (!s) throw new TypeError('Missing [session] configuration section');
  const validStores = ['memory', 'redis', 'file'];
  if (!validStores.includes(s.store)) {
    throw new RangeError('session.store must be: ' + validStores.join(', ') + ', got: ' + s.store);
  }
  if (typeof s.ttl_seconds !== 'number' || s.ttl_seconds <= 0) {
    throw new RangeError('session.ttl_seconds must be positive integer');
  }
  if (!s.secret || typeof s.secret !== 'string' || s.secret.length < 16) {
    throw new TypeError('session.secret must be a string >= 16 chars');
  }
}
module.exports = { init };
""",
    # ==== MIDDLEWARE: cors ====
    "src/middleware/cors.js": """'use strict';
// Reads [cors]: origins (array of URLs), credentials (bool)
function init(config) {
  const c = config.cors;
  if (!c) throw new TypeError('Missing [cors] configuration section');
  if (!Array.isArray(c.origins)) {
    throw new TypeError('cors.origins must be an array, got: ' + typeof c.origins);
  }
  if (c.origins.length === 0) {
    throw new RangeError('cors.origins must not be empty');
  }
  for (const o of c.origins) {
    if (!o.startsWith('http://') && !o.startsWith('https://')) {
      throw new TypeError('cors.origins entries must be URLs, got: ' + o);
    }
  }
  if (typeof c.credentials !== 'boolean') {
    throw new TypeError('cors.credentials must be boolean');
  }
}
module.exports = { init };
""",
    # ==== MIDDLEWARE: ratelimit ====
    "src/middleware/ratelimit.js": """'use strict';
// Reads [ratelimit]: window_ms (int), max_requests (int)
function init(config) {
  const r = config.ratelimit;
  if (!r) throw new TypeError('Missing [ratelimit] configuration section');
  if (typeof r.window_ms !== 'number' || r.window_ms <= 0) {
    throw new RangeError('ratelimit.window_ms must be positive integer');
  }
  if (typeof r.max_requests !== 'number' || r.max_requests <= 0) {
    throw new RangeError('ratelimit.max_requests must be positive integer');
  }
}
module.exports = { init };
""",
    # ==== OBSERVABILITY: logging ====
    "src/observability/logging.js": """'use strict';
// Reads [logging]: level (DEBUG|INFO|WARN|ERROR), format (json|text)
function init(config) {
  const l = config.logging;
  if (!l) throw new TypeError('Missing [logging] configuration section');
  const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
  if (!levels.includes(l.level)) {
    throw new RangeError('logging.level must be: ' + levels.join(', '));
  }
  const formats = ['json', 'text'];
  if (!formats.includes(l.format)) {
    throw new RangeError('logging.format must be: ' + formats.join(', '));
  }
}
module.exports = { init };
""",
    # ==== OBSERVABILITY: metrics (port must differ from server.port) ====
    "src/observability/metrics.js": """'use strict';
// Reads [metrics]: enabled (bool), port (int, must differ from server.port)
function init(config) {
  const m = config.metrics;
  if (!m) throw new TypeError('Missing [metrics] configuration section');
  if (typeof m.enabled !== 'boolean') {
    throw new TypeError('metrics.enabled must be boolean');
  }
  if (m.enabled) {
    if (typeof m.port !== 'number' || !Number.isInteger(m.port)) {
      throw new TypeError('metrics.port must be an integer');
    }
    if (m.port === config.server.port) {
      throw new Error(
        'metrics.port (' + m.port + ') must differ from server.port (' + config.server.port + ')'
      );
    }
  }
}
module.exports = { init };
""",
}

SHARED_PROMPT = (
    "Get the Hive microservice running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)


# ============================================================
# Infra + runner + analysis (reused from multistage test)
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


def _run_agent(
    prompt: str, cwd: Path, user: str, state_file: Path,
    base_url: str | None, max_turns: int = 35, with_overmind: bool = True,
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
        if not line.strip():
            continue
        try:
            evt = json.loads(line.strip())
            events.append(evt)
            if evt.get("type") == "result":
                result_event = evt
        except json.JSONDecodeError:
            pass

    return result_event, events


def analyze_conversation(events: list[dict]) -> dict:
    tool_uses = []
    edited_files = []
    read_files = []
    server_runs = 0
    saw_error = False
    saw_server_running = False

    for evt in events:
        if evt.get("type") == "assistant":
            for block in evt.get("message", {}).get("content", []):
                if block.get("type") != "tool_use":
                    continue
                tool = block["name"]
                inp = block.get("input", {})
                tool_uses.append((tool, inp))

                if tool == "Bash":
                    cmd = inp.get("command", "")
                    if "start.sh" in cmd or ("server.js" in cmd and "node" in cmd) or "npm start" in cmd:
                        server_runs += 1
                elif tool in ("Edit", "Write"):
                    edited_files.append(inp.get("file_path", "").replace("\\", "/"))
                elif tool == "Read":
                    read_files.append(inp.get("file_path", "").replace("\\", "/"))

        elif evt.get("type") == "user":
            result = evt.get("tool_use_result")
            if result:
                txt = result if isinstance(result, str) else str(result.get("stdout", "")) + str(result.get("stderr", ""))
                if "Error" in txt or "assert" in txt.lower():
                    saw_error = True
                if "[Hive] Server running" in txt:
                    saw_server_running = True
            for block in evt.get("message", {}).get("content", []) if isinstance(evt.get("message"), dict) else []:
                if isinstance(block, dict):
                    c = str(block.get("content", ""))
                    if "Error" in c or "assert" in c.lower():
                        saw_error = True
                    if "[Hive] Server running" in c:
                        saw_server_running = True

    src_reads = [f for f in read_files if "/src/" in f or "/boot/" in f or "/middleware/" in f or "/observability/" in f]
    src_read_names = list(dict.fromkeys(f.rsplit("/", 1)[-1] for f in src_reads))

    return {
        "total_tool_uses": len(tool_uses),
        "server_run_attempts": server_runs,
        "saw_error": saw_error,
        "saw_server_running": saw_server_running,
        "config_toml_edits": len([f for f in edited_files if "config.toml" in f]),
        "src_file_reads": len(src_reads),
        "src_files_read": src_read_names,
        "src_file_edits": len([f for f in edited_files if "/src/" in f]),
        "edited_files": [f.rsplit("/", 1)[-1] for f in edited_files],
    }


def create_scaffold(base_dir: Path) -> Path:
    repo_dir = base_dir / "hive-complex"
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
        ["git", "commit", "-m", "initial: Hive complex scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-complex.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def claude_cli():
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found")

@pytest.fixture(scope="module")
def server(tmp_path_factory):
    app = create_app(data_dir=tmp_path_factory.mktemp("ab_complex_data"))
    srv = ServerThread(app, port=OVERMIND_PORT)
    srv.start()
    yield srv
    srv.stop()

@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{OVERMIND_PORT}"

@pytest.fixture(scope="module")
def repo_dirs(tmp_path_factory):
    base = tmp_path_factory.mktemp("ab_complex_repos")
    return {n: create_scaffold(base / n) for n in ("agent_pioneer", "agent_student", "agent_naive")}

@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("ab_complex_states")


# ============================================================
# Test
# ============================================================

@pytest.mark.e2e_live
class TestComplexAB:

    def test_complex_ab(self, claude_cli, server, base_url, repo_dirs, state_dir):

        # == Phase 1: Pioneer ==
        print("\n" + "=" * 70)
        print("  Phase 1: Pioneer (8-subsystem discovery)")
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

        p_server = _api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "limit": "100"})
        p_pushed = [e for e in p_server["events"] if e["user"] == "agent_pioneer"]
        assert len(p_pushed) >= 1, "Pioneer must push events"
        print(f"  Overmind events: {len(p_pushed)}")

        # == Phase 2: Student vs Naive ==
        print("\n" + "=" * 70)
        print("  Phase 2: Student (+Overmind) vs Naive (Control)")
        print("=" * 70)

        pull_preview = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "30",
        })
        print(f"\n  Events for Student's pull: {pull_preview['count']}")
        print(f"  Events for Naive: 0\n")

        ab_results = {}
        ab_events = {}
        ab_times = {}

        def run_ab(name, overmind):
            t = time.time()
            ab_results[name], ab_events[name] = _run_agent(
                SHARED_PROMPT, repo_dirs[name], name,
                state_dir / f"state_{name}.json", base_url, with_overmind=overmind,
            )
            ab_times[name] = time.time() - t

        ta = threading.Thread(target=run_ab, args=("agent_student", True))
        tb = threading.Thread(target=run_ab, args=("agent_naive", False))
        ta.start(); tb.start()
        ta.join(timeout=600); tb.join(timeout=600)

        assert "agent_student" in ab_results, "Student didn't complete"
        assert "agent_naive" in ab_results, "Naive didn't complete"

        s = analyze_conversation(ab_events["agent_student"])
        n = analyze_conversation(ab_events["agent_naive"])

        # == Phase 3: Comparison ==
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison")
        print("=" * 70)

        metrics = ["server_run_attempts", "config_toml_edits", "src_file_reads",
                    "src_file_edits", "saw_error", "saw_server_running", "total_tool_uses"]

        print(f"\n  {'Metric':<25} {'Pioneer':>10} {'Student':>10} {'Naive':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for m in metrics:
            print(f"  {m:<25} {str(p_analysis[m]):>10} {str(s[m]):>10} {str(n[m]):>10}")
        print(f"  {'time (s)':<25} {p_time:>10.1f} {ab_times['agent_student']:>10.1f} {ab_times['agent_naive']:>10.1f}")
        print(f"  {'turns':<25} {str(p_result.get('num_turns','?')):>10} "
              f"{str(ab_results['agent_student'].get('num_turns','?')):>10} "
              f"{str(ab_results['agent_naive'].get('num_turns','?')):>10}")

        print(f"\n  src/ files read:")
        print(f"    Pioneer: {p_analysis['src_files_read']}")
        print(f"    Student: {s['src_files_read']}")
        print(f"    Naive:   {n['src_files_read']}")

        # == Phase 4: Pull Impact ==
        print("\n" + "=" * 70)
        print("  Phase 4: Pull Impact")
        print("=" * 70)

        pull_all = _api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "limit": "200"})
        all_users = {e["user"] for e in pull_all["events"]}

        assert "agent_pioneer" in all_users
        print("  PASS: Pioneer pushed events")
        assert "agent_student" in all_users
        print("  PASS: Student pushed events (Overmind active)")
        assert len([e for e in pull_all["events"] if e["user"] == "agent_naive"]) == 0
        print("  PASS: Naive has 0 events (isolated)")
        print(f"  PASS: Student received {pull_preview['count']} event(s) from Pioneer")

        # == Phase 5: Key Result ==
        print("\n" + "=" * 70)
        print("  Phase 5: KEY RESULT")
        print("=" * 70)

        pr = p_analysis["server_run_attempts"]
        sr = s["server_run_attempts"]
        nr = n["server_run_attempts"]

        print(f"\n  Pioneer: {pr} start.sh runs")
        print(f"  Student: {sr} start.sh runs")
        print(f"  Naive:   {nr} start.sh runs")

        if sr < nr:
            pct = (nr - sr) / nr * 100
            print(f"\n  >> Student needed {nr - sr} FEWER attempts ({pct:.0f}% reduction)")
            print(f"  >> config edits: Student={s['config_toml_edits']} vs Naive={n['config_toml_edits']}")
        elif sr == nr:
            print(f"\n  >> Same attempt count")
        else:
            print(f"\n  >> Naive was better (non-deterministic)")

        # Save JSONL
        for name, evts in [("agent_pioneer", p_events),
                           ("agent_student", ab_events.get("agent_student", [])),
                           ("agent_naive", ab_events.get("agent_naive", []))]:
            with open(state_dir / f"conversation_{name}.jsonl", "w", encoding="utf-8") as f:
                for e in evts:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"\n  JSONL saved to: {state_dir}")
