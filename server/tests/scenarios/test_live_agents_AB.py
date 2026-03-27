# server/tests/scenarios/test_live_agents_AB.py
"""A/B Test: Overmind lesson sharing vs no-Overmind baseline.

Scenario:
  A Python HTTP server reads config.toml for startup configuration.
  config.toml is deliberately incomplete — missing required fields.
  The server prints PRESCRIPTIVE error messages telling exactly what to fix:

    === CONFIGURATION ERROR ===
    Missing [server] section in config.toml. Add:

    [server]
    port = 3000
    host = "0.0.0.0"

    Fix config.toml and retry: python src/server.py
    ===========================

  Config traps (not in config.toml):
    1. [server] section with port + host
    2. [security] section with api_secret (>= 32 chars)
    3. [app] section with env ("development" or "production")

  Agents:
    Z (pioneer, +Overmind): runs first, discovers traps via error logs, fixes config.toml
    A (beneficiary, +Overmind): runs after Z, pulls Z's events at session start
    B (control, -Overmind): runs after Z, zero context from Z

  Behavioral analysis via --output-format stream-json --verbose:
    - Parse JSONL for tool_use events (Bash commands, Edit/Write targets)
    - Count server.py execution attempts per agent
    - Track which files were edited and when
    - Compare A vs B tool-use patterns as proxy for Overmind impact

Requires:
  - `claude` CLI installed and authenticated
  - Overmind plugin at plugin/ directory
  - Run: pytest tests/scenarios/test_live_agents_AB.py -m e2e_live -s

EXCLUDED from normal test runs via pyproject.toml addopts.
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
OVERMIND_PORT = 17997
REPO_ID = "github.com/test/hive-ab"


# ============================================================
# Scaffold: Python server + config.toml with prescriptive errors
# ============================================================

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT modify files under src/ or docs/.
""",
    "config.toml": """# Hive Server Configuration
# Start the server with: bash start.sh

[database]
url = "postgres://localhost:5432/hive"

[auth]
jwt_secret = "my-jwt-secret-key-here"
""",
    "docs/config-schema.md": """# Hive Server Configuration Schema

All configuration is in `config.toml` at the project root.

## Required Sections

### [server]
| Key  | Type    | Required | Description              |
|------|---------|----------|--------------------------|
| port | integer | yes      | HTTP listen port         |
| host | string  | yes      | Bind address             |

### [security]
| Key        | Type   | Required | Constraints     | Description        |
|------------|--------|----------|-----------------|--------------------|
| api_secret | string | yes      | min 32 chars    | API signing secret |

### [app]
| Key | Type   | Required | Valid values                  | Description     |
|-----|--------|----------|-------------------------------|-----------------|
| env | string | yes      | "development", "production"   | Runtime mode    |

## Example

```toml
[database]
url = "postgres://localhost:5432/hive"

[auth]
jwt_secret = "my-jwt-secret"

[server]
port = 3000
host = "0.0.0.0"

[security]
api_secret = "a-very-long-secret-string-that-is-at-least-32-characters"

[app]
env = "development"
```
""",
    "start.sh": """#!/usr/bin/env bash
# Hive Server startup script
# Usage: bash start.sh
set -e
cd "$(dirname "$0")"
echo "[start.sh] Starting Hive server..."
python src/server.py 2>&1
""",
    "src/server.py": r'''#!/usr/bin/env python3
"""Hive API Server — validates config.toml then starts HTTP server."""

import http.server
import json
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11 fallback


def load_config() -> dict:
    config_path = Path("config.toml")
    if not config_path.exists():
        print("=== CONFIGURATION ERROR ===", file=sys.stderr)
        print("config.toml not found.", file=sys.stderr)
        print("Create config.toml in the project root.", file=sys.stderr)
        print("===========================", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def validate_config(config: dict) -> list[str]:
    """Validate config — errors show SYMPTOMS only, not solutions."""
    errors = []

    # --- Check 1: [server] section ---
    if "server" not in config:
        errors.append('Missing required configuration section: [server]')
    else:
        server = config["server"]
        if "port" not in server:
            errors.append('Missing required key "port" in [server]')
        elif not isinstance(server["port"], int):
            errors.append(f'Invalid type for [server].port: expected integer, got {type(server["port"]).__name__}')
        if "host" not in server:
            errors.append('Missing required key "host" in [server]')

    # --- Check 2: [security] section ---
    if "security" not in config:
        errors.append('Missing required configuration section: [security]')
    else:
        sec = config["security"]
        secret = sec.get("api_secret", "")
        if not secret:
            errors.append('Missing required key "api_secret" in [security]')
        elif len(str(secret)) < 32:
            errors.append(f'Validation failed: [security].api_secret is too short (length {len(str(secret))}, minimum 32)')

    # --- Check 3: [app] section ---
    if "app" not in config:
        errors.append('Missing required configuration section: [app]')
    else:
        env = config["app"].get("env", "")
        if env not in ("development", "production"):
            errors.append(f'Invalid value for [app].env: "{env}" (must be "development" or "production")')

    return errors


def main():
    config = load_config()
    errors = validate_config(config)

    if errors:
        # Only show the FIRST error — forces iterative discovery
        print("", file=sys.stderr)
        print("=== STARTUP FAILED ===", file=sys.stderr)
        print(f"  ERROR: {errors[0]}", file=sys.stderr)
        if len(errors) > 1:
            print(f"  ({len(errors) - 1} more error(s) may appear after fixing this one)", file=sys.stderr)
        print("======================", file=sys.stderr)
        sys.exit(1)

    # All checks passed — start server
    port = config["server"]["port"]
    host = config["server"].get("host", "0.0.0.0")
    env = config["app"]["env"]

    print(f"[Hive] Configuration OK")
    print(f"[Hive] port={port}, host={host}, env={env}")
    print(f"[Hive] api_secret length={len(config['security']['api_secret'])}")
    print(f"[Hive] Server starting on {host}:{port}...")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok", "port": port, "env": env,
            }).encode())

        def log_message(self, format, *args):
            pass  # suppress request logs

    server = http.server.HTTPServer((host, port), Handler)
    print(f"[Hive] Server running on http://{host}:{port}")
    # For testing: print success and exit immediately (don't actually serve)
    print(f"[Hive] Server ready. Exiting (test mode).")


if __name__ == "__main__":
    main()
''',
}


def create_scaffold(base_dir: Path) -> Path:
    """Create config.toml-based scaffold as a git repo."""
    repo_dir = base_dir / "hive-ab"
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
        ["git", "commit", "-m", "initial: Hive server scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-ab.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


# ============================================================
# Infrastructure
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

SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)


def _run_agent(
    prompt: str, cwd: Path, user: str, state_file: Path,
    base_url: str | None, max_turns: int = 20, with_overmind: bool = True,
) -> tuple[dict, list[dict]]:
    """Run claude -p with JSONL capture. Returns (result_event, all_events)."""
    env = {**os.environ}
    cmd = [
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
    ]

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

    # Parse JSONL events
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
# JSONL analysis
# ============================================================


def analyze_conversation(events: list[dict]) -> dict:
    """Extract behavioral metrics from stream-json events."""
    tool_uses = []      # (tool_name, input_summary)
    bash_commands = []   # raw commands
    edited_files = []    # files edited/written
    server_runs = 0      # how many times python src/server.py was run
    saw_config_error = False
    saw_server_running = False

    for evt in events:
        if evt.get("type") != "assistant":
            continue
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
                if ("start.sh" in cmd) or ("server.py" in cmd and ("python" in cmd or "python3" in cmd)):
                    server_runs += 1

            elif tool in ("Edit", "Write"):
                fp = inp.get("file_path", "")
                edited_files.append(fp)

    # Check tool results for config error / success
    for evt in events:
        if evt.get("type") != "user":
            continue

        # tool_use_result field (top-level on user events)
        result = evt.get("tool_use_result")
        if result:
            if isinstance(result, str):
                combined = result
            elif isinstance(result, dict):
                combined = str(result.get("stdout", "")) + str(result.get("stderr", ""))
            else:
                combined = str(result)
            if "STARTUP FAILED" in combined:
                saw_config_error = True
            if "[Hive] Server running" in combined:
                saw_server_running = True

        # Also check message.content for tool_result blocks
        msg = evt.get("message", {})
        if isinstance(msg, dict):
            for block in msg.get("content", []):
                if not isinstance(block, dict):
                    continue
                content = block.get("content", "")
                if isinstance(content, str):
                    if "STARTUP FAILED" in content:
                        saw_config_error = True
                    if "[Hive] Server running" in content:
                        saw_server_running = True

    # Which files were edited
    config_edits = [f for f in edited_files if "config.toml" in f]
    src_edits = [f for f in edited_files if "/src/" in f.replace("\\", "/")]

    return {
        "total_tool_uses": len(tool_uses),
        "bash_commands": len(bash_commands),
        "server_run_attempts": server_runs,
        "saw_config_error": saw_config_error,
        "saw_server_running": saw_server_running,
        "config_toml_edits": len(config_edits),
        "src_file_edits": len(src_edits),
        "edited_files": edited_files,
        "tools_used": list({t for t, _ in tool_uses}),
    }


def check_config_toml(repo_dir: Path) -> dict:
    """Validate final config.toml state."""
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

    server = config.get("server", {})
    security = config.get("security", {})
    app = config.get("app", {})

    port_ok = isinstance(server.get("port"), int)
    host_ok = "host" in server
    secret = str(security.get("api_secret", ""))
    secret_ok = len(secret) >= 32
    env_val = app.get("env", "")
    env_ok = env_val in ("development", "production")

    return {
        "exists": True,
        "has_server_section": "server" in config,
        "port_ok": port_ok,
        "port_value": server.get("port"),
        "host_ok": host_ok,
        "has_security_section": "security" in config,
        "api_secret_ok": secret_ok,
        "api_secret_len": len(secret),
        "has_app_section": "app" in config,
        "env_ok": env_ok,
        "env_value": env_val,
        "all_ok": all([port_ok, host_ok, secret_ok, env_ok]),
    }


def check_src_modified(repo_dir: Path) -> list[str]:
    """Return list of modified src/ files via git diff."""
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
    data_dir = tmp_path_factory.mktemp("ab_data")
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
    base = tmp_path_factory.mktemp("ab_repos")
    return {
        name: create_scaffold(base / name)
        for name in ("agent_pioneer", "agent_student", "agent_naive")
    }


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("ab_states")


# ============================================================
# Test
# ============================================================


@pytest.mark.e2e_live
class TestLiveAgentsAB:

    def test_ab_lesson_sharing(
        self, claude_cli, server, base_url, repo_dirs, state_dir,
    ):
        # ──────────────────────────────────────────────
        # Phase 1: Z discovers config traps
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 1: Agent Z (Pioneer)")
        print("=" * 70)

        t0 = time.time()
        z_result, z_events = _run_agent(
            SHARED_PROMPT, repo_dirs["agent_pioneer"], "agent_pioneer",
            state_dir / "state_z.json", base_url, with_overmind=True,
        )
        z_time = time.time() - t0
        z_analysis = analyze_conversation(z_events)

        print(f"  Time: {z_time:.1f}s")
        print(f"  Turns: {z_result.get('num_turns', '?')}")
        print(f"  Tool uses: {z_analysis['total_tool_uses']}")
        print(f"  server.py runs: {z_analysis['server_run_attempts']}")
        print(f"  Config error seen: {z_analysis['saw_config_error']}")
        print(f"  Server started: {z_analysis['saw_server_running']}")
        print(f"  config.toml edits: {z_analysis['config_toml_edits']}")
        print(f"  src/ edits: {z_analysis['src_file_edits']}")

        z_config = check_config_toml(repo_dirs["agent_pioneer"])
        z_src_mod = check_src_modified(repo_dirs["agent_pioneer"])
        print(f"  config.toml: {z_config}")
        if z_src_mod:
            print(f"  WARNING: src/ modified: {z_src_mod}")

        # Verify Z pushed events to Overmind
        z_server_events = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "limit": "50",
        })
        z_pushed = [e for e in z_server_events["events"] if e["user"] == "agent_pioneer"]
        assert len(z_pushed) >= 1, f"Z must push events. Got 0."
        print(f"  Overmind events: {len(z_pushed)}")
        for e in z_pushed:
            print(f"    {e['result'][:90]}")

        # ──────────────────────────────────────────────
        # Phase 2: A (+Overmind) vs B (-Overmind)
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 2: A (Overmind) vs B (Control)")
        print("=" * 70)

        # Show what A will receive from Overmind pull
        a_pull_preview = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "20",
        })
        print(f"\n  Events available for A's SessionStart pull: {a_pull_preview['count']}")
        for e in a_pull_preview["events"]:
            print(f"    [{e['user']}] {e['result'][:80]}")
        print(f"  Events available for B: 0 (no Overmind)\n")

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
        ta.join(timeout=300); tb.join(timeout=300)

        assert "agent_student" in ab_results, "A didn't complete"
        assert "agent_naive" in ab_results, "B didn't complete"

        a_analysis = analyze_conversation(ab_events["agent_student"])
        b_analysis = analyze_conversation(ab_events["agent_naive"])

        # ──────────────────────────────────────────────
        # Phase 3: Behavioral Comparison (JSONL-based)
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison (from JSONL)")
        print("=" * 70)

        metrics = ["total_tool_uses", "bash_commands", "server_run_attempts",
                    "saw_config_error", "saw_server_running",
                    "config_toml_edits", "src_file_edits"]

        print(f"\n  {'Metric':<25} {'Z':>8} {'A (+OM)':>8} {'B (-OM)':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
        for m in metrics:
            zv = z_analysis[m]
            av = a_analysis[m]
            bv = b_analysis[m]
            print(f"  {m:<25} {str(zv):>8} {str(av):>8} {str(bv):>8}")

        print(f"  {'time (s)':<25} {z_time:>8.1f} {ab_times['agent_student']:>8.1f} {ab_times['agent_naive']:>8.1f}")
        print(f"  {'turns':<25} {str(z_result.get('num_turns','?')):>8} "
              f"{str(ab_results['agent_student'].get('num_turns','?')):>8} "
              f"{str(ab_results['agent_naive'].get('num_turns','?')):>8}")

        # Edited files detail
        print(f"\n  Edited files:")
        for name, analysis in [("Z", z_analysis), ("A", a_analysis), ("B", b_analysis)]:
            files = [f.replace("\\", "/").split("/")[-1] for f in analysis["edited_files"]]
            print(f"    {name}: {files if files else '(none)'}")

        # ──────────────────────────────────────────────
        # Phase 4: Pull Impact Verification
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 4: Pull Impact")
        print("=" * 70)

        pull_all = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "limit": "100",
        })
        all_users = {e["user"] for e in pull_all["events"]}

        # Hard: infrastructure assertions
        assert "agent_pioneer" in all_users, "Z events missing"
        print("  PASS: Z pushed events")

        assert "agent_student" in all_users, "A events missing (Overmind didn't fire)"
        print("  PASS: A pushed events (Overmind active)")

        b_on_server = [e for e in pull_all["events"] if e["user"] == "agent_naive"]
        assert len(b_on_server) == 0, f"B has {len(b_on_server)} events (should be 0)"
        print("  PASS: B has 0 events (correctly isolated)")

        a_received = len([e for e in a_pull_preview["events"]
                          if e["user"] == "agent_pioneer"])
        print(f"  PASS: A received {a_received} event(s) from Z via pull")
        print(f"  PASS: B received 0 events (no Overmind)")

        # ──────────────────────────────────────────────
        # Phase 5: Solution & Score
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 5: Solution & Score")
        print("=" * 70)

        configs = {}
        src_mods = {}
        for name in ("agent_pioneer", "agent_student", "agent_naive"):
            configs[name] = check_config_toml(repo_dirs[name])
            src_mods[name] = check_src_modified(repo_dirs[name])
            c = configs[name]
            label = "OK" if c.get("all_ok") else "INCOMPLETE"
            print(f"\n  [{name}] config.toml: {label}")
            print(f"    port={c.get('port_value','?')} "
                  f"secret_len={c.get('api_secret_len',0)} "
                  f"env={c.get('env_value','?')}")
            if src_mods[name]:
                print(f"    WARNING src/ modified: {src_mods[name]}")
            else:
                print(f"    src/ untouched (good)")

        # Scoring
        def score(name: str) -> int:
            s = 0
            c = configs[name]
            a = z_analysis if name == "agent_pioneer" else (
                a_analysis if name == "agent_student" else b_analysis)

            if c.get("all_ok"):
                s += 3  # correct solution
            if not src_mods[name]:
                s += 2  # respected constraint
            if a["saw_server_running"]:
                s += 2  # actually started server
            if a["server_run_attempts"] <= 2:
                s += 1  # efficient
            return s

        s_z = score("agent_pioneer")
        s_a = score("agent_student")
        s_b = score("agent_naive")

        print(f"\n  Score: Z={s_z}  A={s_a}  B={s_b}")
        print(f"  Time:  Z={z_time:.0f}s  A={ab_times['agent_student']:.0f}s  B={ab_times['agent_naive']:.0f}s")

        # Key A/B comparison
        print(f"\n  A/B Key Metrics:")
        print(f"    server.py attempts:  A={a_analysis['server_run_attempts']}  "
              f"B={b_analysis['server_run_attempts']}")
        print(f"    config.toml edits:   A={a_analysis['config_toml_edits']}  "
              f"B={b_analysis['config_toml_edits']}")
        print(f"    src/ edits:          A={a_analysis['src_file_edits']}  "
              f"B={b_analysis['src_file_edits']}")

        if a_analysis["server_run_attempts"] < b_analysis["server_run_attempts"]:
            print("    >> A needed fewer attempts (Overmind advantage)")
        elif a_analysis["server_run_attempts"] == b_analysis["server_run_attempts"]:
            print("    >> Same attempt count")
        else:
            print("    >> B needed fewer attempts (non-deterministic)")

        if ab_times["agent_student"] < ab_times["agent_naive"]:
            delta = ab_times["agent_naive"] - ab_times["agent_student"]
            print(f"    >> A was {delta:.0f}s faster")
        else:
            delta = ab_times["agent_student"] - ab_times["agent_naive"]
            print(f"    >> B was {delta:.0f}s faster (non-deterministic)")

        # ── Save JSONL for post-mortem ──
        for name, evts in [("agent_pioneer", z_events),
                           ("agent_student", ab_events.get("agent_student", [])),
                           ("agent_naive", ab_events.get("agent_naive", []))]:
            jsonl_path = state_dir / f"conversation_{name}.jsonl"
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for e in evts:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

        print(f"\n  Conversation JSONL saved to: {state_dir}")
        print(f"  Analyze with: python -c \"import json; [print(json.loads(l)['type']) "
              f"for l in open('conversation_agent_student.jsonl')]\"")
