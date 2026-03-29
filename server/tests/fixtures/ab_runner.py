"""ab_runner.py - Shared utilities for all A/B live-agent tests.

Provides reusable agent running, analysis, statistics, and reporting
functions extracted from the AB test scenarios.
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


# ============================================================
# Data classes
# ============================================================


@dataclass
class AgentSpec:
    name: str
    cwd: Path
    user: str
    state_file: Path
    with_overmind: bool


@dataclass
class AgentResult:
    name: str
    result_event: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    elapsed: float = 0.0


# ============================================================
# Utilities
# ============================================================


def require_claude_cli() -> None:
    """Skip the current pytest test if `claude` CLI is not found."""
    import pytest
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found")


def api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    """GET from Overmind server, return parsed JSON."""
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(Request(url, method="GET"), timeout=10) as resp:
        return json.loads(resp.read())


def api_post(base_url: str, path: str, body: dict) -> dict:
    """POST JSON to Overmind server, return parsed JSON."""
    data = json.dumps(body).encode("utf-8")
    req = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def seed_pioneer_events(base_url: str, source_repo_id: str, target_repo_id: str) -> int:
    """Copy Pioneer's events from source_repo_id to target_repo_id.

    This isolates each Student so they only see Pioneer's events,
    preventing cross-contamination between parallel Students.
    Returns the number of events seeded.
    """
    pull = api_get(base_url, "/api/memory/pull", {
        "repo_id": source_repo_id, "limit": "200",
    })
    events = [e for e in pull.get("events", []) if e.get("user") == "pioneer"]
    if not events:
        return 0
    api_post(base_url, "/api/memory/push", {
        "repo_id": target_repo_id,
        "user": "pioneer",
        "events": events,
    })
    return len(events)


# ============================================================
# Agent runner
# ============================================================


def run_agent(
    prompt: str,
    cwd: Path,
    user: str,
    state_file: Path,
    base_url: str,
    repo_id: str,
    max_turns: int = 20,
    with_overmind: bool = True,
    model: str = "",
) -> AgentResult:
    """Run `claude -p` with stream-json output and return an AgentResult.

    Captures JSONL events from stdout, parses them, pre-computes analysis,
    and records elapsed time.
    """
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
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    elapsed = time.time() - t0

    events: list[dict] = []
    result_event: dict = {}
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
        name=user,
        result_event=result_event,
        events=events,
        analysis=analysis,
        elapsed=elapsed,
    )


# ============================================================
# Parallel agent runner
# ============================================================


def run_parallel_agents(
    agents: list[AgentSpec],
    prompt: str,
    base_url: str,
    repo_id: str,
    max_turns: int = 20,
    model: str = "",
) -> dict[str, AgentResult]:
    """Run multiple agents in parallel via ThreadPoolExecutor.

    Returns a dict mapping agent name to AgentResult.
    """
    results: dict[str, AgentResult] = {}

    def _run(spec: AgentSpec) -> AgentResult:
        return run_agent(
            prompt=prompt,
            cwd=spec.cwd,
            user=spec.user,
            state_file=spec.state_file,
            base_url=base_url,
            repo_id=repo_id,
            max_turns=max_turns,
            with_overmind=spec.with_overmind,
            model=model,
        )

    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        future_to_spec = {executor.submit(_run, spec): spec for spec in agents}
        for future in as_completed(future_to_spec):
            spec = future_to_spec[future]
            result = future.result()
            results[spec.name] = result

    return results


# ============================================================
# Conversation analysis
# ============================================================


def analyze_conversation(events: list[dict]) -> dict:
    """Extract behavioral metrics from stream-json events.

    Covers both Python (server.py/start.sh) and Node.js (server.js/node)
    scaffolds. Returns a unified dict of metrics.
    """
    tool_uses: list[tuple[str, dict]] = []
    bash_commands: list[str] = []
    edited_files: list[str] = []
    read_files: list[str] = []
    server_runs = 0
    saw_error = False
    saw_server_running = False

    # Step tracking for proactive fix detection
    step = 0
    first_config_edit_step: int | None = None
    first_server_run_step: int | None = None

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
                    # Server run detection: Python and Node.js variants
                    if (
                        "start.sh" in cmd
                        or ("server.py" in cmd and ("python" in cmd or "python3" in cmd))
                        or ("server.js" in cmd and "node" in cmd)
                        or "npm start" in cmd
                        or "npm run" in cmd
                    ):
                        server_runs += 1
                        if first_server_run_step is None:
                            first_server_run_step = step

                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    edited_files.append(fp)
                    # Track config file edits (config.toml, .env, secrets/, registry.json,
                    # services/*.toml, env_mapping.json — microservices scaffold)
                    is_config_file = (
                        "config.toml" in fp
                        or fp.endswith("/.env")
                        or fp.endswith(".env")
                        or "/secrets/" in fp
                        or "registry.json" in fp
                        or "/services/" in fp
                        or "env_mapping.json" in fp
                    )
                    if is_config_file and first_config_edit_step is None:
                        first_config_edit_step = step

                elif tool == "Read":
                    fp = inp.get("file_path", "").replace("\\", "/")
                    read_files.append(fp)

        elif evt.get("type") == "user":
            result = evt.get("tool_use_result")
            if result:
                txt = (
                    result
                    if isinstance(result, str)
                    else str(result.get("stdout", "")) + str(result.get("stderr", ""))
                )
                if "Error" in txt or "Traceback" in txt or "STARTUP FAILED" in txt or "assert" in txt.lower():
                    saw_error = True
                if "[Hive] Server running" in txt or "[Hive] Server ready" in txt or "All services running" in txt:
                    saw_server_running = True

            msg = evt.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if not isinstance(block, dict):
                        continue
                    content = block.get("content", "")
                    if isinstance(content, str):
                        if "Error" in content or "Traceback" in content or "STARTUP FAILED" in content or "assert" in content.lower():
                            saw_error = True
                        if "[Hive] Server running" in content or "[Hive] Server ready" in content or "All services running" in content:
                            saw_server_running = True

    config_edits = [f for f in edited_files if "config.toml" in f]
    config_file_edits = [
        f for f in edited_files
        if "config.toml" in f
        or f.endswith("/.env")
        or f.endswith(".env")
        or "/secrets/" in f
        or "registry.json" in f
        or "/services/" in f
        or "env_mapping.json" in f
    ]
    src_edits = [
        f for f in edited_files
        if "/src/" in f or "/boot/" in f or "/middleware/" in f or "/observability/" in f
    ]
    src_reads = [
        f for f in read_files
        if "/src/" in f or "/boot/" in f or "/middleware/" in f or "/observability/" in f
    ]
    src_read_names = list(dict.fromkeys(f.rsplit("/", 1)[-1] for f in src_reads))

    # Proactive config fix: agent edits config.toml BEFORE first server run
    proactive_config_fix = (
        first_config_edit_step is not None
        and first_server_run_step is not None
        and first_config_edit_step < first_server_run_step
    )

    # Branch-conflict specific metrics
    port_conflict_count = 0
    for evt in events:
        if evt.get("type") == "user":
            # Check tool_use_result
            result = evt.get("tool_use_result")
            if result and isinstance(result, str):
                if "AddressError" in result or "port conflict" in result:
                    port_conflict_count += 1
            # Check message content blocks
            msg = evt.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        content = str(block.get("content", ""))
                        if "AddressError" in content or "port conflict" in content:
                            port_conflict_count += 1

    return {
        "total_tool_uses": len(tool_uses),
        "bash_commands": len(bash_commands),
        "server_run_attempts": server_runs,
        "saw_error": saw_error,
        "saw_server_running": saw_server_running,
        "config_toml_edits": len(config_edits),
        "config_file_edits": len(config_file_edits),
        "src_file_reads": len(src_reads),
        "src_files_read": src_read_names,
        "src_file_edits": len(src_edits),
        "edited_files": [f.rsplit("/", 1)[-1] for f in edited_files],
        "tools_used": list({t for t, _ in tool_uses}),
        "proactive_config_fix": proactive_config_fix,
        "first_config_edit_step": first_config_edit_step,
        "first_server_run_step": first_server_run_step,
        "port_conflict_count": port_conflict_count,
    }


# ============================================================
# Git helpers
# ============================================================


def check_src_modified(repo_dir: Path) -> list[str]:
    """Return list of modified src/ files via git diff HEAD."""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only", "--", "src/"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        timeout=5,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


# ============================================================
# Statistics
# ============================================================

NUMERIC_METRICS = [
    "total_tool_uses",
    "bash_commands",
    "server_run_attempts",
    "config_toml_edits",
    "config_file_edits",
    "src_file_reads",
    "src_file_edits",
    "first_config_edit_step",
    "first_server_run_step",
    "port_conflict_count",
]

BOOLEAN_METRICS = [
    "saw_error",
    "saw_server_running",
    "proactive_config_fix",
]


def compute_statistics(analyses: list[dict]) -> dict:
    """Compute per-metric statistics across a list of analysis dicts.

    For NUMERIC_METRICS: mean/median/stddev/min/max/values.
    For BOOLEAN_METRICS: count_true/count_false/pct_true.
    None values in numeric metrics are filtered out before computation.
    """
    stats: dict[str, dict] = {}

    for metric in NUMERIC_METRICS:
        values = [a[metric] for a in analyses if a.get(metric) is not None]
        if not values:
            stats[metric] = {
                "mean": None,
                "median": None,
                "stddev": None,
                "min": None,
                "max": None,
                "values": [],
            }
        elif len(values) == 1:
            stats[metric] = {
                "mean": values[0],
                "median": values[0],
                "stddev": None,
                "min": values[0],
                "max": values[0],
                "values": values,
            }
        else:
            stats[metric] = {
                "mean": mean(values),
                "median": median(values),
                "stddev": stdev(values),
                "min": min(values),
                "max": max(values),
                "values": values,
            }

    for metric in BOOLEAN_METRICS:
        true_count = sum(1 for a in analyses if a.get(metric))
        false_count = len(analyses) - true_count
        pct_true = (true_count / len(analyses) * 100) if analyses else 0.0
        stats[metric] = {
            "count_true": true_count,
            "count_false": false_count,
            "pct_true": pct_true,
        }

    return stats


def compute_elapsed_stats(results: list[AgentResult]) -> dict:
    """Compute elapsed time statistics across a list of AgentResults."""
    times = [r.elapsed for r in results]
    if not times:
        return {"mean": None, "median": None, "stddev": None, "min": None, "max": None}
    if len(times) == 1:
        return {
            "mean": times[0],
            "median": times[0],
            "stddev": None,
            "min": times[0],
            "max": times[0],
        }
    return {
        "mean": mean(times),
        "median": median(times),
        "stddev": stdev(times),
        "min": min(times),
        "max": max(times),
    }


# ============================================================
# Reporting
# ============================================================


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
    pioneer_elapsed: float = 0.0,
) -> None:
    """Print a formatted terminal comparison table of pioneer vs student vs naive."""
    header = "  A/B Comparison"
    if scaffold_name:
        header += f" - {scaffold_name}"
    if model:
        header += f" [{model}]"
    print(f"\n{'=' * 70}")
    print(header)
    print(f"  Pioneer: 1 run | Students (+Overmind): n={n} | Naives (control): m={m}")
    print(f"{'=' * 70}")

    p_analysis = pioneer

    # Numeric metrics
    print(f"\n  {'Metric':<28} {'Pioneer':>10} {'Student(avg)':>13} {'Naive(avg)':>12}")
    print(f"  {'-'*28} {'-'*10} {'-'*13} {'-'*12}")
    for metric in NUMERIC_METRICS:
        pv = p_analysis.get(metric)
        sv = student_stats.get(metric, {}).get("mean")
        nv = naive_stats.get(metric, {}).get("mean")

        pv_str = "N/A" if pv is None else f"{pv}"
        sv_str = "N/A" if sv is None else f"{sv:.1f}"
        nv_str = "N/A" if nv is None else f"{nv:.1f}"
        print(f"  {metric:<28} {pv_str:>10} {sv_str:>13} {nv_str:>12}")

    # Elapsed time
    s_elapsed_mean = student_elapsed.get("mean")
    n_elapsed_mean = naive_elapsed.get("mean")
    s_elapsed_str = "N/A" if s_elapsed_mean is None else f"{s_elapsed_mean:.1f}s"
    n_elapsed_str = "N/A" if n_elapsed_mean is None else f"{n_elapsed_mean:.1f}s"
    print(f"  {'elapsed (s)':<28} {pioneer_elapsed:>9.1f}s {s_elapsed_str:>13} {n_elapsed_str:>12}")

    # Boolean metrics
    print(f"\n  {'Boolean Metric':<28} {'Pioneer':>10} {'Student (%)':>13} {'Naive (%)':>12}")
    print(f"  {'-'*28} {'-'*10} {'-'*13} {'-'*12}")
    for metric in BOOLEAN_METRICS:
        pv = p_analysis.get(metric)
        s_pct = student_stats.get(metric, {}).get("pct_true")
        n_pct = naive_stats.get(metric, {}).get("pct_true")

        pv_str = str(pv)
        sv_str = "N/A" if s_pct is None else f"{s_pct:.0f}%"
        nv_str = "N/A" if n_pct is None else f"{n_pct:.0f}%"
        print(f"  {metric:<28} {pv_str:>10} {sv_str:>13} {nv_str:>12}")

    print()


def generate_report(
    scaffold_name: str,
    model: str,
    pioneer: AgentResult,
    students: list[AgentResult],
    naives: list[AgentResult],
    n: int,
    m: int,
) -> dict:
    """Generate a JSON-serializable report dict with full stats and comparison."""
    student_stats = compute_statistics([r.analysis for r in students])
    naive_stats = compute_statistics([r.analysis for r in naives])
    student_elapsed = compute_elapsed_stats(students)
    naive_elapsed = compute_elapsed_stats(naives)

    return {
        "scaffold": scaffold_name,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"pioneer": 1, "students": n, "naives": m},
        "pioneer": {
            "name": pioneer.name,
            "elapsed": pioneer.elapsed,
            "analysis": pioneer.analysis,
            "turns": pioneer.result_event.get("num_turns"),
        },
        "student_stats": student_stats,
        "naive_stats": naive_stats,
        "student_elapsed": student_elapsed,
        "naive_elapsed": naive_elapsed,
        "students": [
            {
                "name": r.name,
                "elapsed": r.elapsed,
                "analysis": r.analysis,
                "turns": r.result_event.get("num_turns"),
            }
            for r in students
        ],
        "naives": [
            {
                "name": r.name,
                "elapsed": r.elapsed,
                "analysis": r.analysis,
                "turns": r.result_event.get("num_turns"),
            }
            for r in naives
        ],
    }


# ============================================================
# I/O helpers
# ============================================================


def save_jsonl(events: list[dict], path: Path) -> None:
    """Write events as JSONL, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")


def save_report(report: dict, path: Path) -> None:
    """Write report dict as indented JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
