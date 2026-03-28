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
from pathlib import Path

import pytest

from overmind.api import create_app
from tests.fixtures.ab_runner import (
    AgentSpec, api_get, compute_elapsed_stats, compute_statistics,
    generate_report, print_comparison_table, require_claude_cli,
    run_agent, run_parallel_agents, save_jsonl, save_report,
)
from tests.fixtures.ab_scaffolds import SCAFFOLDS
from tests.fixtures.server_helpers import ServerThread

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
def test_statistical_ab(scaffold_name, claude_cli, server, base_url, tmp_path, request):
    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    scaffold = SCAFFOLDS[scaffold_name]
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    print(f"\n{'=' * 70}")
    print(f"  Statistical A/B: {scaffold_name} (N={N}, M={M}, model={model or 'default'})")
    print(f"{'=' * 70}")

    # Create scaffolds: 1 pioneer + N students + M naives (each independent git repo)
    repos = {"pioneer": scaffold.create_scaffold(tmp_path / "pioneer")}
    for i in range(N):
        repos[f"student_{i}"] = scaffold.create_scaffold(tmp_path / f"student_{i}")
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(tmp_path / f"naive_{i}")
    print(f"  Created {1 + N + M} scaffold repos")

    # Phase 1: Pioneer (sequential)
    print(f"\n  Phase 1: Pioneer")
    pioneer = run_agent(
        prompt=scaffold.SHARED_PROMPT, cwd=repos["pioneer"],
        user="pioneer", state_file=state_dir / "state_pioneer.json",
        base_url=base_url, repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS, with_overmind=True, model=model,
    )
    print(f"  Pioneer: {pioneer.elapsed:.1f}s, runs={pioneer.analysis['server_run_attempts']}, "
          f"success={pioneer.analysis['saw_server_running']}")

    pull = api_get(base_url, "/api/memory/pull", {"repo_id": scaffold.REPO_ID, "limit": "100"})
    p_events = [e for e in pull["events"] if e["user"] == "pioneer"]
    assert len(p_events) >= 1, "Pioneer must push at least 1 event"
    print(f"  Pioneer pushed {len(p_events)} events")

    # Phase 2: Student x N + Naive x M (parallel)
    print(f"\n  Phase 2: {N} students + {M} naives in parallel...")
    agents = []
    for i in range(N):
        agents.append(AgentSpec(
            name=f"student_{i}", cwd=repos[f"student_{i}"],
            user=f"student_{i}", state_file=state_dir / f"state_student_{i}.json",
            with_overmind=True,
        ))
    for i in range(M):
        agents.append(AgentSpec(
            name=f"naive_{i}", cwd=repos[f"naive_{i}"],
            user=f"naive_{i}", state_file=state_dir / f"state_naive_{i}.json",
            with_overmind=False,
        ))

    results = run_parallel_agents(
        agents=agents, prompt=scaffold.SHARED_PROMPT,
        base_url=base_url, repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS, model=model,
    )

    # Phase 3: Analyze
    students = [results[f"student_{i}"] for i in range(N)]
    naives = [results[f"naive_{i}"] for i in range(M)]
    student_stats = compute_statistics([s.analysis for s in students])
    naive_stats = compute_statistics([n.analysis for n in naives])
    student_elapsed = compute_elapsed_stats(students)
    naive_elapsed = compute_elapsed_stats(naives)

    # Phase 4: Print comparison
    print_comparison_table(
        pioneer=pioneer.analysis, student_stats=student_stats,
        naive_stats=naive_stats, student_elapsed=student_elapsed,
        naive_elapsed=naive_elapsed, n=N, m=M,
        scaffold_name=scaffold_name, model=model,
        pioneer_elapsed=pioneer.elapsed,
    )

    # Phase 5: Save reports + JSONL
    report = generate_report(
        scaffold_name=scaffold_name, model=model,
        pioneer=pioneer, students=students, naives=naives, n=N, m=M,
    )
    save_report(report, report_dir / f"{scaffold_name}_report.json")
    save_jsonl(pioneer.events, report_dir / "pioneer.jsonl")
    for i in range(N):
        save_jsonl(results[f"student_{i}"].events, report_dir / f"student_{i}.jsonl")
    for i in range(M):
        save_jsonl(results[f"naive_{i}"].events, report_dir / f"naive_{i}.jsonl")
    print(f"\n  Reports saved to: {report_dir}")

    # Assertions
    for i in range(N):
        assert f"student_{i}" in results, f"student_{i} didn't complete"
    for i in range(M):
        assert f"naive_{i}" in results, f"naive_{i} didn't complete"

    s_mean = student_stats.get("server_run_attempts", {}).get("mean", 0)
    n_mean = naive_stats.get("server_run_attempts", {}).get("mean", 0)
    if s_mean and n_mean and s_mean > n_mean:
        print(f"\n  WARNING: Students averaged MORE attempts ({s_mean}) than naives ({n_mean})")
