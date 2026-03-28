# Statistical A/B Test Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor AB test infrastructure into shared modules, extract scaffolds, and add a new statistical test that runs Pioneer 1× then Student×N + Naive×M in parallel with aggregate reporting.

**Architecture:** Extract duplicated code from 3 existing AB test files into `ab_scaffolds/` (scaffold definitions) and `ab_runner.py` (agent runner + analysis + statistics). Add pytest CLI options via conftest. New `test_live_agents_AB_statistical.py` parametrizes over all scaffolds and runs N+M parallel Claude CLI agents with `ThreadPoolExecutor`.

**Tech Stack:** Python, pytest, ThreadPoolExecutor, Claude CLI (`claude -p`), uvicorn thread server, JSONL stream parsing.

**Spec:** `docs/superpowers/specs/2026-03-28-statistical-ab-test-framework-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `tests/fixtures/ab_scaffolds/__init__.py` | Scaffold registry |
| Create | `tests/fixtures/ab_scaffolds/simple.py` | Simple scaffold (from test_live_agents_AB.py) |
| Create | `tests/fixtures/ab_scaffolds/multistage.py` | Multistage scaffold (from test_live_agents_AB_multistage.py) |
| Create | `tests/fixtures/ab_scaffolds/complex.py` | Complex scaffold (from test_live_agents_AB_complex.py) |
| Create | `tests/fixtures/ab_runner.py` | Shared agent runner, analysis, statistics, reporting |
| Modify | `tests/conftest.py` | Add --student-n, --naive-m, --agent-model options |
| Rewrite | `tests/scenarios/test_live_agents_AB.py` | Use ab_runner + simple scaffold |
| Rewrite | `tests/scenarios/test_live_agents_AB_multistage.py` | Use ab_runner + multistage scaffold |
| Rewrite | `tests/scenarios/test_live_agents_AB_complex.py` | Use ab_runner + complex scaffold |
| Create | `tests/scenarios/test_live_agents_AB_statistical.py` | Parametrized N/M parallel test |

All paths relative to `server/`.

---

### Task 1: Create ab_scaffolds/simple.py

Extract `SCAFFOLD_FILES`, `create_scaffold`, `SHARED_PROMPT`, `REPO_ID`, `MAX_TURNS` from `test_live_agents_AB.py`.

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/__init__.py`
- Create: `server/tests/fixtures/ab_scaffolds/simple.py`

- [ ] **Step 1: Create `ab_scaffolds/__init__.py`**

```python
"""Scaffold registry for A/B tests.

Each scaffold module exposes:
  SCAFFOLD_FILES: dict[str, str]  — file contents
  SHARED_PROMPT: str              — agent instruction
  REPO_NAME: str                  — git repo directory name
  REPO_ID: str                    — Overmind repo_id
  MAX_TURNS: int                  — claude --max-turns
  create_scaffold(base_dir: Path) -> Path  — creates git repo, returns repo_dir
"""
from . import simple

SCAFFOLDS: dict = {
    "simple": simple,
}
```

- [ ] **Step 2: Create `ab_scaffolds/simple.py`**

Copy the following from `test_live_agents_AB.py`:
- `SCAFFOLD_FILES` dict (lines 69-248, entire dict including CLAUDE.md, config.toml, docs/config-schema.md, start.sh, src/server.py)
- `create_scaffold` function (lines 251-276)
- Add module-level constants

```python
"""Simple scaffold: Python HTTP server with 3 config.toml traps.

Traps:
  1. [server] section with port + host
  2. [security] section with api_secret (>= 32 chars)
  3. [app] section with env ("development" or "production")
"""
import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-ab"
REPO_ID = "github.com/test/hive-ab"
MAX_TURNS = 20
SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)

SCAFFOLD_FILES: dict[str, str] = {
    # <<< Copy entire SCAFFOLD_FILES dict from test_live_agents_AB.py lines 69-248 >>>
    # Keys: "CLAUDE.md", "config.toml", "docs/config-schema.md", "start.sh", "src/server.py"
}


def create_scaffold(base_dir: Path) -> Path:
    """Create config.toml-based scaffold as a git repo."""
    repo_dir = base_dir / REPO_NAME
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
        ["git", "commit", "-m", "initial: Hive simple scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/test/{REPO_NAME}.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir
```

The SCAFFOLD_FILES dict is copied verbatim from the existing file — every key/value pair. Do NOT abbreviate.

- [ ] **Step 3: Verify scaffold module imports**

```bash
cd server && uv run python -c "from tests.fixtures.ab_scaffolds.simple import SCAFFOLD_FILES, create_scaffold, SHARED_PROMPT, REPO_ID, MAX_TURNS; print(f'OK: {len(SCAFFOLD_FILES)} files, REPO_ID={REPO_ID}')"
```

Expected: `OK: 5 files, REPO_ID=github.com/test/hive-ab`

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/__init__.py server/tests/fixtures/ab_scaffolds/simple.py
git commit -m "refactor: extract simple scaffold to ab_scaffolds/simple.py"
```

---

### Task 2: Create ab_scaffolds/multistage.py

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/multistage.py`
- Modify: `server/tests/fixtures/ab_scaffolds/__init__.py`

- [ ] **Step 1: Create `ab_scaffolds/multistage.py`**

Copy from `test_live_agents_AB_multistage.py`:
- `SCAFFOLD_FILES` (lines 63-291, all keys: CLAUDE.md, config.toml, hmac.key, start.sh, package.json, src/server.js, src/network.js, src/auth.js, src/session.js, src/routes.js, src/middleware.js, src/logging.js)
- `create_scaffold` (lines 294-318)
- `check_config` (lines 527-587) — scaffold-specific config validator
- `SHARED_PROMPT`, `REPO_ID`, `MAX_TURNS`

```python
"""Multistage scaffold: Node.js app with 9-stage failure cascade.

Stages: network → auth → session → routes → middleware → logging
"""
import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-multi"
REPO_ID = "github.com/test/hive-multistage"
MAX_TURNS = 30
SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, figure out what's wrong and fix config.toml, then retry. "
    "You may only edit config.toml — do not modify any .js or .json files."
)

SCAFFOLD_FILES: dict[str, str] = {
    # <<< Copy entire SCAFFOLD_FILES dict from test_live_agents_AB_multistage.py lines 63-291 >>>
}


def create_scaffold(base_dir: Path) -> Path:
    repo_dir = base_dir / REPO_NAME
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
        ["git", "remote", "add", "origin", f"https://github.com/test/{REPO_NAME}.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


def check_config(repo_dir: Path) -> dict:
    # <<< Copy check_config from test_live_agents_AB_multistage.py lines 527-587 verbatim >>>
    pass
```

Copy every function and dict verbatim. Do NOT abbreviate.

- [ ] **Step 2: Update `__init__.py` to add multistage**

```python
from . import simple, multistage

SCAFFOLDS: dict = {
    "simple": simple,
    "multistage": multistage,
}
```

- [ ] **Step 3: Verify**

```bash
cd server && uv run python -c "from tests.fixtures.ab_scaffolds.multistage import SCAFFOLD_FILES, create_scaffold, SHARED_PROMPT, REPO_ID, MAX_TURNS; print(f'OK: {len(SCAFFOLD_FILES)} files, REPO_ID={REPO_ID}')"
```

Expected: `OK: 12 files, REPO_ID=github.com/test/hive-multistage`

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/multistage.py server/tests/fixtures/ab_scaffolds/__init__.py
git commit -m "refactor: extract multistage scaffold to ab_scaffolds/multistage.py"
```

---

### Task 3: Create ab_scaffolds/complex.py

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/complex.py`
- Modify: `server/tests/fixtures/ab_scaffolds/__init__.py`

- [ ] **Step 1: Create `ab_scaffolds/complex.py`**

Copy from `test_live_agents_AB_complex.py`:
- `SCAFFOLD_FILES` (lines 55-300, all keys: CLAUDE.md, config.toml, hmac.key, start.sh, package.json, src/server.js, src/boot/network.js, src/boot/auth.js, src/boot/security.js, src/boot/cache.js, src/boot/session.js, src/middleware/cors.js, src/middleware/ratelimit.js, src/observability/logging.js, src/observability/metrics.js)
- `create_scaffold` (lines 449-471)
- `SHARED_PROMPT` (lines 302-307), `REPO_ID`, `MAX_TURNS`

```python
"""Complex scaffold: Node.js microservice with 14 config subsystems.

Subsystems: network, auth, security, cache, session, cors, ratelimit, logging, metrics
"""
import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-complex"
REPO_ID = "github.com/test/hive-complex"
MAX_TURNS = 35
SHARED_PROMPT = (
    "Get the Hive microservice running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)

SCAFFOLD_FILES: dict[str, str] = {
    # <<< Copy entire SCAFFOLD_FILES dict from test_live_agents_AB_complex.py lines 55-300 >>>
}


def create_scaffold(base_dir: Path) -> Path:
    repo_dir = base_dir / REPO_NAME
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
        ["git", "remote", "add", "origin", f"https://github.com/test/{REPO_NAME}.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir
```

- [ ] **Step 2: Update `__init__.py`**

```python
from . import simple, multistage
from . import complex as complex_

SCAFFOLDS: dict = {
    "simple": simple,
    "multistage": multistage,
    "complex": complex_,
}
```

- [ ] **Step 3: Verify**

```bash
cd server && uv run python -c "from tests.fixtures.ab_scaffolds import SCAFFOLDS; print({k: len(v.SCAFFOLD_FILES) for k, v in SCAFFOLDS.items()})"
```

Expected: `{'simple': 5, 'multistage': 12, 'complex': 15}`

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/complex.py server/tests/fixtures/ab_scaffolds/__init__.py
git commit -m "refactor: extract complex scaffold to ab_scaffolds/complex.py"
```

---

### Task 4: Create ab_runner.py

Extract shared infrastructure from all 3 test files into one module.

**Files:**
- Create: `server/tests/fixtures/ab_runner.py`

- [ ] **Step 1: Create `ab_runner.py` with data classes and run_agent**

```python
"""Shared A/B test runner: agent execution, JSONL analysis, statistics, reporting.

Used by individual AB tests (simple/multistage/complex) and the statistical test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"


@dataclass
class AgentSpec:
    """Specification for a single agent run."""
    name: str
    cwd: Path
    user: str
    state_file: Path
    with_overmind: bool


@dataclass
class AgentResult:
    """Result from a single agent run."""
    name: str
    result_event: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    elapsed: float = 0.0


def require_claude_cli():
    """Skip test if claude CLI is not available."""
    import pytest
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found")


def api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    """GET from Overmind server."""
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(Request(url, method="GET"), timeout=10) as resp:
        return json.loads(resp.read())


def run_agent(
    prompt: str,
    cwd: Path,
    user: str,
    state_file: Path,
    base_url: str | None,
    repo_id: str,
    max_turns: int = 20,
    with_overmind: bool = True,
    model: str = "",
) -> AgentResult:
    """Run claude -p with JSONL capture. Returns AgentResult with parsed events."""
    env = {**os.environ}
    cmd = [
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    if model:
        cmd.extend(["--model", model])

    if with_overmind and base_url:
        env.update({
            "OVERMIND_URL": base_url,
            "OVERMIND_REPO_ID": repo_id,
            "OVERMIND_USER": user,
            "OVERMIND_STATE_FILE": str(state_file),
            "OVERMIND_FLUSH_THRESHOLD": "1",
        })
        cmd.extend(["--plugin-dir", str(PLUGIN_DIR)])

    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(cwd), env=env,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=600,
    )
    elapsed = time.time() - t0

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

    analysis = analyze_conversation(events)
    return AgentResult(
        name=user, result_event=result_event,
        events=events, analysis=analysis, elapsed=elapsed,
    )


def run_parallel_agents(
    agents: list[AgentSpec],
    prompt: str,
    base_url: str,
    repo_id: str,
    max_turns: int = 20,
    model: str = "",
) -> dict[str, AgentResult]:
    """Run multiple agents in parallel using ThreadPoolExecutor."""
    results: dict[str, AgentResult] = {}

    def _run(spec: AgentSpec) -> tuple[str, AgentResult]:
        r = run_agent(
            prompt=prompt, cwd=spec.cwd, user=spec.user,
            state_file=spec.state_file, base_url=base_url,
            repo_id=repo_id, max_turns=max_turns,
            with_overmind=spec.with_overmind, model=model,
        )
        return spec.name, r

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        futures = {pool.submit(_run, a): a.name for a in agents}
        for future in as_completed(futures):
            name, result = future.result()
            results[name] = result

    return results
```

- [ ] **Step 2: Add analyze_conversation (unified from all 3 files)**

Append to `ab_runner.py`:

```python
def analyze_conversation(events: list[dict]) -> dict:
    """Extract behavioral metrics from stream-json JSONL events.

    Unified analysis covering simple (server.py/start.sh) and
    complex (node src/server.js) scaffolds.
    """
    tool_uses = []
    bash_commands = []
    edited_files = []
    read_files = []
    server_runs = 0
    saw_error = False
    saw_server_running = False

    step = 0
    first_config_edit_step = None
    first_server_run_step = None

    for evt in events:
        if evt.get("type") == "assistant":
            msg = evt.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue
                tool = block.get("name", "")
                inp = block.get("input", {})
                tool_uses.append((tool, inp))
                step += 1

                if tool == "Bash":
                    cmd = inp.get("command", "")
                    bash_commands.append(cmd)
                    if ("start.sh" in cmd
                            or ("server.py" in cmd and "python" in cmd)
                            or ("server.js" in cmd and "node" in cmd)
                            or "npm start" in cmd
                            or "npm run" in cmd):
                        server_runs += 1
                        if first_server_run_step is None:
                            first_server_run_step = step
                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    edited_files.append(fp)
                    if "config.toml" in fp and first_config_edit_step is None:
                        first_config_edit_step = step
                elif tool == "Read":
                    fp = inp.get("file_path", "").replace("\\", "/")
                    read_files.append(fp)

        elif evt.get("type") == "user":
            result = evt.get("tool_use_result")
            if result:
                txt = result if isinstance(result, str) else (
                    str(result.get("stdout", "")) + str(result.get("stderr", ""))
                )
                if any(k in txt for k in ("Error", "Traceback", "STARTUP FAILED", "assert")):
                    saw_error = True
                if "[Hive] Server running" in txt or "[Hive] Server ready" in txt:
                    saw_server_running = True

            msg = evt.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        content = str(block.get("content", ""))
                        if any(k in content for k in ("Error", "Traceback", "STARTUP FAILED")):
                            saw_error = True
                        if "[Hive] Server running" in content or "[Hive] Server ready" in content:
                            saw_server_running = True

    config_edits = [f for f in edited_files if "config.toml" in f]
    src_reads = [f for f in read_files if "/src/" in f or "/boot/" in f
                 or "/middleware/" in f or "/observability/" in f]
    src_edits = [f for f in edited_files if "/src/" in f]
    src_read_names = list(dict.fromkeys(f.rsplit("/", 1)[-1] for f in src_reads))

    proactive_config_fix = (
        first_config_edit_step is not None
        and first_server_run_step is not None
        and first_config_edit_step < first_server_run_step
    )

    return {
        "total_tool_uses": len(tool_uses),
        "bash_commands": len(bash_commands),
        "server_run_attempts": server_runs,
        "saw_error": saw_error,
        "saw_server_running": saw_server_running,
        "config_toml_edits": len(config_edits),
        "src_file_reads": len(src_reads),
        "src_files_read": src_read_names,
        "src_file_edits": len(src_edits),
        "edited_files": [f.rsplit("/", 1)[-1] for f in edited_files],
        "tools_used": list({t for t, _ in tool_uses}),
        "proactive_config_fix": proactive_config_fix,
        "first_config_edit_step": first_config_edit_step,
        "first_server_run_step": first_server_run_step,
    }
```

- [ ] **Step 3: Add statistics + reporting functions**

Append to `ab_runner.py`:

```python
def check_src_modified(repo_dir: Path) -> list[str]:
    """Return list of modified src/ files via git diff."""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only", "--", "src/"],
        cwd=str(repo_dir), capture_output=True, text=True, timeout=5,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


# Metrics to compute statistics for (numeric only)
NUMERIC_METRICS = [
    "total_tool_uses", "bash_commands", "server_run_attempts",
    "config_toml_edits", "src_file_reads", "src_file_edits",
    "first_config_edit_step", "first_server_run_step",
]
BOOLEAN_METRICS = [
    "saw_error", "saw_server_running", "proactive_config_fix",
]


def compute_statistics(analyses: list[dict]) -> dict:
    """Compute mean/median/stddev/min/max per numeric metric, pct for booleans."""
    stats: dict = {}
    n = len(analyses)
    if n == 0:
        return stats

    for metric in NUMERIC_METRICS:
        values = [a[metric] for a in analyses if a.get(metric) is not None]
        if not values:
            stats[metric] = {"mean": None, "median": None, "stddev": None,
                             "min": None, "max": None, "values": []}
            continue
        s = {
            "mean": round(mean(values), 1),
            "median": round(median(values), 1),
            "stddev": round(stdev(values), 1) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "values": values,
        }
        stats[metric] = s

    for metric in BOOLEAN_METRICS:
        values = [a.get(metric, False) for a in analyses]
        count_true = sum(1 for v in values if v)
        stats[metric] = {
            "count_true": count_true,
            "count_false": n - count_true,
            "pct_true": round(count_true / n * 100, 1),
        }

    # Elapsed time stats from AgentResult
    stats["elapsed"] = {"mean": None, "median": None, "stddev": None,
                        "min": None, "max": None, "values": []}

    return stats


def compute_elapsed_stats(results: list[AgentResult]) -> dict:
    """Compute elapsed time statistics from AgentResult list."""
    values = [r.elapsed for r in results]
    if not values:
        return {"mean": None, "median": None, "stddev": None, "min": None, "max": None, "values": []}
    return {
        "mean": round(mean(values), 1),
        "median": round(median(values), 1),
        "stddev": round(stdev(values), 1) if len(values) > 1 else 0.0,
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "values": [round(v, 1) for v in values],
    }


def print_comparison_table(
    pioneer: dict,
    student_stats: dict,
    naive_stats: dict,
    student_elapsed: dict,
    naive_elapsed: dict,
    n: int,
    m: int,
    scaffold_name: str = "",
    model: str = "",
):
    """Print formatted comparison table to terminal."""
    header = f"Statistical A/B: {scaffold_name}" if scaffold_name else "Statistical A/B"
    if model:
        header += f" (model={model})"

    print(f"\n{'=' * 70}")
    print(f"  {header} (N={n} students, M={m} naives)")
    print(f"{'=' * 70}")

    def _fmt_stat(s: dict) -> str:
        if s.get("mean") is None:
            return "N/A"
        vals = ",".join(str(v) for v in s["values"])
        return f"{s['mean']:>5} +/-{s['stddev']:<4} [{vals}]"

    def _fmt_bool(s: dict) -> str:
        total = s["count_true"] + s["count_false"]
        return f"{s['count_true']}/{total} ({s['pct_true']}%)"

    print(f"\n  {'Metric':<25} {'Pioneer':>10}   {'Student':>28}   {'Naive':>28}")
    print(f"  {'-'*25} {'-'*10}   {'-'*28}   {'-'*28}")

    for metric in NUMERIC_METRICS:
        pv = pioneer.get(metric, "?")
        ss = student_stats.get(metric, {})
        ns = naive_stats.get(metric, {})
        print(f"  {metric:<25} {str(pv):>10}   {_fmt_stat(ss):>28}   {_fmt_stat(ns):>28}")

    for metric in BOOLEAN_METRICS:
        pv = pioneer.get(metric, "?")
        ss = student_stats.get(metric, {})
        ns = naive_stats.get(metric, {})
        print(f"  {metric:<25} {str(pv):>10}   {_fmt_bool(ss):>28}   {_fmt_bool(ns):>28}")

    print(f"  {'time (s)':<25} {'':>10}   {_fmt_stat(student_elapsed):>28}   {_fmt_stat(naive_elapsed):>28}")

    # Summary
    s_mean = student_stats.get("server_run_attempts", {}).get("mean")
    n_mean = naive_stats.get("server_run_attempts", {}).get("mean")
    if s_mean is not None and n_mean is not None and n_mean > 0:
        pct = (n_mean - s_mean) / n_mean * 100
        if pct > 0:
            print(f"\n  >> Student mean attempts {pct:.0f}% fewer than Naive ({s_mean} vs {n_mean})")
        else:
            print(f"\n  >> No advantage this run (Student {s_mean} vs Naive {n_mean})")


def generate_report(
    scaffold_name: str,
    model: str,
    pioneer: AgentResult,
    students: list[AgentResult],
    naives: list[AgentResult],
    n: int,
    m: int,
) -> dict:
    """Generate JSON report for post-analysis."""
    student_stats = compute_statistics([s.analysis for s in students])
    naive_stats = compute_statistics([n.analysis for n in naives])

    s_mean = student_stats.get("server_run_attempts", {}).get("mean", 0)
    n_mean = naive_stats.get("server_run_attempts", {}).get("mean", 0)
    s_time = mean([s.elapsed for s in students]) if students else 0
    n_time = mean([n.elapsed for n in naives]) if naives else 0

    return {
        "scaffold": scaffold_name,
        "model": model or "default",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {"student_n": n, "naive_m": m},
        "pioneer": {
            "analysis": pioneer.analysis,
            "elapsed": round(pioneer.elapsed, 1),
            "turns": pioneer.result_event.get("num_turns"),
        },
        "students": {
            "raw": [{"analysis": s.analysis, "elapsed": round(s.elapsed, 1),
                      "turns": s.result_event.get("num_turns")} for s in students],
            "stats": student_stats,
            "elapsed_stats": compute_elapsed_stats(students),
        },
        "naives": {
            "raw": [{"analysis": n.analysis, "elapsed": round(n.elapsed, 1),
                      "turns": n.result_event.get("num_turns")} for n in naives],
            "stats": naive_stats,
            "elapsed_stats": compute_elapsed_stats(naives),
        },
        "comparison": {
            "attempt_reduction_pct": round((n_mean - s_mean) / n_mean * 100, 1) if n_mean > 0 else 0,
            "time_reduction_pct": round((n_time - s_time) / n_time * 100, 1) if n_time > 0 else 0,
        },
    }


def save_jsonl(events: list[dict], path: Path):
    """Save events as JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def save_report(report: dict, path: Path):
    """Save JSON report file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: Verify import works**

```bash
cd server && uv run python -c "from tests.fixtures.ab_runner import run_agent, run_parallel_agents, analyze_conversation, compute_statistics, print_comparison_table, generate_report; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/ab_runner.py
git commit -m "refactor: create ab_runner.py with shared agent runner + analysis + statistics"
```

---

### Task 5: Add pytest options to conftest.py

**Files:**
- Modify: `server/tests/conftest.py`

- [ ] **Step 1: Add pytest_addoption to conftest.py**

Add to the existing file (keep the existing `data_dir` fixture):

```python
def pytest_addoption(parser):
    parser.addoption("--student-n", type=int, default=3,
                     help="Number of student (Overmind-enabled) iterations for statistical tests")
    parser.addoption("--naive-m", type=int, default=3,
                     help="Number of naive (no-Overmind) iterations for statistical tests")
    parser.addoption("--agent-model", type=str, default="",
                     help="Claude model for all agents (haiku/sonnet/opus)")
```

- [ ] **Step 2: Verify options are registered**

```bash
cd server && uv run pytest --help | grep -A1 "student-n"
```

Expected: shows `--student-n` with help text

- [ ] **Step 3: Commit**

```bash
git add server/tests/conftest.py
git commit -m "feat: add --student-n, --naive-m, --agent-model pytest options"
```

---

### Task 6: Refactor test_live_agents_AB.py

Replace inline infrastructure with `ab_runner` + `ab_scaffolds.simple` imports.

**Files:**
- Rewrite: `server/tests/scenarios/test_live_agents_AB.py`

- [ ] **Step 1: Rewrite the file**

The new file should:
1. Import `ab_scaffolds.simple` for scaffold
2. Import `ab_runner` for `run_agent`, `api_get`, `require_claude_cli`, `check_src_modified`, `AgentResult`
3. Keep the same test structure (Phase 1-5) and assertions
4. Keep `check_config_toml` locally since it's scaffold-specific (simple scaffold uses tomllib for its own validation)
5. Keep `@pytest.mark.e2e_live`
6. Use `ab_runner.PLUGIN_DIR` instead of local `PLUGIN_DIR`
7. Remove duplicated `ServerThread`, `_run_agent`, `_api_get`, `analyze_conversation`
8. Use `ServerThread` from `tests.fixtures.server_helpers` for server startup

The test function body should look similar to the original but call `ab_runner.run_agent()` and `result.analysis` for metrics. Threading for A vs B is kept as before (2 threads for N=1 M=1 baseline).

Keep `check_config_toml` and scoring inline since they are simple-scaffold-specific.

- [ ] **Step 2: Run existing tests to verify no regression**

```bash
cd server && uv run pytest tests/ -v --ignore=tests/scenarios/test_live_agents_AB.py --ignore=tests/scenarios/test_live_agents_AB_multistage.py --ignore=tests/scenarios/test_live_agents_AB_complex.py --ignore=tests/scenarios/test_live_agents_AB_statistical.py -k "not e2e_live"
```

Expected: all existing non-live tests pass (82+)

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_live_agents_AB.py
git commit -m "refactor: test_live_agents_AB.py uses ab_runner + ab_scaffolds.simple"
```

---

### Task 7: Refactor test_live_agents_AB_multistage.py

**Files:**
- Rewrite: `server/tests/scenarios/test_live_agents_AB_multistage.py`

- [ ] **Step 1: Rewrite**

Same pattern as Task 6:
1. Import `ab_scaffolds.multistage` for scaffold + `check_config`
2. Import `ab_runner` for `run_agent`, `api_get`, `check_src_modified`
3. Remove duplicated infrastructure
4. Keep test logic, phases, assertions

- [ ] **Step 2: Verify no regression**

```bash
cd server && uv run pytest tests/ -v -k "not e2e_live and not live_agents"
```

Expected: all non-live tests pass

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_live_agents_AB_multistage.py
git commit -m "refactor: test_live_agents_AB_multistage.py uses ab_runner + ab_scaffolds.multistage"
```

---

### Task 8: Refactor test_live_agents_AB_complex.py

**Files:**
- Rewrite: `server/tests/scenarios/test_live_agents_AB_complex.py`

- [ ] **Step 1: Rewrite**

Same pattern:
1. Import `ab_scaffolds.complex_` for scaffold
2. Import `ab_runner` for shared functions
3. Remove duplicated infrastructure

- [ ] **Step 2: Verify no regression**

```bash
cd server && uv run pytest tests/ -v -k "not e2e_live and not live_agents"
```

Expected: all non-live tests pass

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_live_agents_AB_complex.py
git commit -m "refactor: test_live_agents_AB_complex.py uses ab_runner + ab_scaffolds.complex"
```

---

### Task 9: Create test_live_agents_AB_statistical.py

The main new test file.

**Files:**
- Create: `server/tests/scenarios/test_live_agents_AB_statistical.py`

- [ ] **Step 1: Create the file**

```python
"""Statistical A/B Test: Pioneer 1x -> Student x N + Naive x M in parallel.

Runs real Claude CLI agents against each scaffold, collecting JSONL logs.
Reports mean/median/stddev per metric for statistical comparison.

Usage:
  pytest tests/scenarios/test_live_agents_AB_statistical.py -m e2e_live -s \
    --student-n 3 --naive-m 3 --agent-model haiku

  # Single scaffold:
  pytest ... -k simple --student-n 5 --naive-m 5

EXCLUDED from normal test runs via pyproject.toml addopts.
"""
import os
import shutil
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from overmind.api import create_app
from tests.fixtures.ab_runner import (
    AgentSpec,
    api_get,
    compute_elapsed_stats,
    compute_statistics,
    generate_report,
    print_comparison_table,
    require_claude_cli,
    run_agent,
    run_parallel_agents,
    save_jsonl,
    save_report,
)
from tests.fixtures.ab_scaffolds import SCAFFOLDS
from tests.fixtures.server_helpers import ServerThread

# Use high port range to avoid conflicts with other tests
OVERMIND_PORT = int(os.environ.get("TEST_OVERMIND_PORT", "17990"))


@pytest.fixture(scope="module")
def claude_cli():
    require_claude_cli()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("ab_stat_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=OVERMIND_PORT)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{OVERMIND_PORT}"


@pytest.mark.e2e_live
@pytest.mark.parametrize("scaffold_name", list(SCAFFOLDS.keys()))
def test_statistical_ab(
    scaffold_name: str,
    claude_cli,
    server,
    base_url,
    tmp_path,
    request,
):
    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    scaffold = SCAFFOLDS[scaffold_name]
    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    print(f"\n{'=' * 70}")
    print(f"  Statistical A/B: {scaffold_name} (N={N}, M={M}, model={model or 'default'})")
    print(f"{'=' * 70}")

    # ── Create scaffolds: 1 pioneer + N students + M naives ──
    repos = {"pioneer": scaffold.create_scaffold(tmp_path / "pioneer")}
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    for i in range(N):
        repos[f"student_{i}"] = scaffold.create_scaffold(tmp_path / f"student_{i}")
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(tmp_path / f"naive_{i}")

    print(f"  Created {1 + N + M} scaffold repos")

    # ── Phase 1: Pioneer (sequential) ──
    print(f"\n  Phase 1: Pioneer")
    pioneer = run_agent(
        prompt=scaffold.SHARED_PROMPT,
        cwd=repos["pioneer"],
        user="pioneer",
        state_file=state_dir / "state_pioneer.json",
        base_url=base_url,
        repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS,
        with_overmind=True,
        model=model,
    )
    print(f"  Pioneer done: {pioneer.elapsed:.1f}s, "
          f"runs={pioneer.analysis['server_run_attempts']}, "
          f"success={pioneer.analysis['saw_server_running']}")

    # Verify pioneer pushed events
    pull = api_get(base_url, "/api/memory/pull", {
        "repo_id": scaffold.REPO_ID, "limit": "100",
    })
    p_events = [e for e in pull["events"] if e["user"] == "pioneer"]
    assert len(p_events) >= 1, "Pioneer must push at least 1 event"
    print(f"  Pioneer pushed {len(p_events)} events to Overmind")

    # ── Phase 2: Student x N + Naive x M (parallel) ──
    print(f"\n  Phase 2: Running {N} students + {M} naives in parallel...")
    agents = []
    for i in range(N):
        agents.append(AgentSpec(
            name=f"student_{i}",
            cwd=repos[f"student_{i}"],
            user=f"student_{i}",
            state_file=state_dir / f"state_student_{i}.json",
            with_overmind=True,
        ))
    for i in range(M):
        agents.append(AgentSpec(
            name=f"naive_{i}",
            cwd=repos[f"naive_{i}"],
            user=f"naive_{i}",
            state_file=state_dir / f"state_naive_{i}.json",
            with_overmind=False,
        ))

    results = run_parallel_agents(
        agents=agents,
        prompt=scaffold.SHARED_PROMPT,
        base_url=base_url,
        repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS,
        model=model,
    )

    # ── Phase 3: Analyze ──
    students = [results[f"student_{i}"] for i in range(N)]
    naives = [results[f"naive_{i}"] for i in range(M)]

    student_stats = compute_statistics([s.analysis for s in students])
    naive_stats = compute_statistics([n.analysis for n in naives])
    student_elapsed = compute_elapsed_stats(students)
    naive_elapsed = compute_elapsed_stats(naives)

    # ── Phase 4: Print table ──
    print_comparison_table(
        pioneer=pioneer.analysis,
        student_stats=student_stats,
        naive_stats=naive_stats,
        student_elapsed=student_elapsed,
        naive_elapsed=naive_elapsed,
        n=N, m=M,
        scaffold_name=scaffold_name,
        model=model,
    )

    # ── Phase 5: Save reports + JSONL ──
    report = generate_report(
        scaffold_name=scaffold_name,
        model=model,
        pioneer=pioneer,
        students=students,
        naives=naives,
        n=N, m=M,
    )
    save_report(report, report_dir / f"{scaffold_name}_report.json")
    save_jsonl(pioneer.events, report_dir / "pioneer.jsonl")
    for i in range(N):
        save_jsonl(results[f"student_{i}"].events, report_dir / f"student_{i}.jsonl")
    for i in range(M):
        save_jsonl(results[f"naive_{i}"].events, report_dir / f"naive_{i}.jsonl")

    print(f"\n  Reports saved to: {report_dir}")

    # ── Assertions ──
    # All agents completed
    for i in range(N):
        assert f"student_{i}" in results, f"student_{i} didn't complete"
    for i in range(M):
        assert f"naive_{i}" in results, f"naive_{i} didn't complete"

    # Pioneer pushed events
    assert len(p_events) >= 1

    # Soft: student mean attempts <= naive mean attempts (log warning, don't fail)
    s_mean = student_stats.get("server_run_attempts", {}).get("mean", 0)
    n_mean = naive_stats.get("server_run_attempts", {}).get("mean", 0)
    if s_mean > n_mean:
        print(f"\n  WARNING: Students averaged MORE attempts ({s_mean}) than naives ({n_mean})")
        print(f"  This can happen due to LLM non-determinism. Check JSONL for details.")
```

- [ ] **Step 2: Verify the file parses correctly**

```bash
cd server && uv run python -c "import ast; ast.parse(open('tests/scenarios/test_live_agents_AB_statistical.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify pytest collects the test**

```bash
cd server && uv run pytest tests/scenarios/test_live_agents_AB_statistical.py --collect-only 2>&1 | head -20
```

Expected: shows 3 parametrized test items (simple, multistage, complex) with `e2e_live` marker (deselected by default)

- [ ] **Step 4: Commit**

```bash
git add server/tests/scenarios/test_live_agents_AB_statistical.py
git commit -m "feat: add statistical AB test with parametrized scaffolds and N/M parallel agents"
```

---

### Task 10: Final integration verification

- [ ] **Step 1: Run all non-live tests**

```bash
cd server && uv run pytest tests/ -v
```

Expected: all 82+ server tests pass, 4 live tests deselected

- [ ] **Step 2: Run all plugin tests**

```bash
cd server && uv run pytest ../plugin/tests/ -v
```

Expected: 103+ plugin tests pass (1 flaky Windows timing test may fail)

- [ ] **Step 3: Verify statistical test collection**

```bash
cd server && uv run pytest tests/scenarios/test_live_agents_AB_statistical.py --collect-only -m e2e_live 2>&1
```

Expected: 3 test items collected (simple, multistage, complex)

- [ ] **Step 4: Verify pytest options work**

```bash
cd server && uv run pytest --help | grep -E "student-n|naive-m|agent-model"
```

Expected: all 3 options shown

- [ ] **Step 5: Verify all ab_scaffolds import cleanly**

```bash
cd server && uv run python -c "
from tests.fixtures.ab_scaffolds import SCAFFOLDS
for name, mod in SCAFFOLDS.items():
    assert hasattr(mod, 'SCAFFOLD_FILES')
    assert hasattr(mod, 'create_scaffold')
    assert hasattr(mod, 'SHARED_PROMPT')
    assert hasattr(mod, 'REPO_ID')
    assert hasattr(mod, 'MAX_TURNS')
    print(f'{name}: {len(mod.SCAFFOLD_FILES)} files, MAX_TURNS={mod.MAX_TURNS}')
print('All scaffolds OK')
"
```

Expected:
```
simple: 5 files, MAX_TURNS=20
multistage: 12 files, MAX_TURNS=30
complex: 15 files, MAX_TURNS=35
All scaffolds OK
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete statistical AB test framework — scaffold extraction + ab_runner + N/M parallel agents"
```
