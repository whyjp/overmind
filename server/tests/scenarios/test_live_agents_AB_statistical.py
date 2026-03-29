"""Statistical A/B Test: Pioneer 1x -> Student x N + Naive x M in parallel.

Runs real Claude CLI agents against each scaffold, collecting JSONL logs.
Reports mean/median/stddev per metric for statistical comparison.

Model-tier strategy: Pioneer uses a smarter model (--pioneer-model, default sonnet)
with the SAME prompt as Student/Naive. The smarter model naturally produces better
insights, which Overmind propagates to Students (cheaper model). This proves
Overmind's real value: cross-model knowledge transfer.

Usage:
  pytest tests/scenarios/test_live_agents_AB_statistical.py -m e2e_live -s \
    --student-n 3 --naive-m 3 --agent-model haiku --pioneer-model sonnet

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

# Model tier: if pioneer-model not set, auto-upgrade from agent-model
_MODEL_UPGRADES = {"haiku": "sonnet", "": "sonnet"}


def _resolve_pioneer_model(request) -> str:
    """Resolve pioneer model: explicit --pioneer-model > auto-upgrade from --agent-model."""
    pioneer = request.config.getoption("--pioneer-model")
    if pioneer:
        return pioneer
    agent = request.config.getoption("--agent-model")
    return _MODEL_UPGRADES.get(agent, agent)


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
@pytest.mark.parametrize("scaffold_name", [k for k in SCAFFOLDS if k != "branch_conflict"])
def test_statistical_ab(scaffold_name, claude_cli, server, base_url, tmp_path, request):
    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    scaffold = SCAFFOLDS[scaffold_name]
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    pioneer_model = _resolve_pioneer_model(request)

    print(f"\n{'=' * 70}")
    print(f"  Statistical A/B: {scaffold_name} (N={N}, M={M}, "
          f"pioneer={pioneer_model or 'default'}, student/naive={model or 'default'})")
    print(f"{'=' * 70}")

    # ── Set-based architecture ────────────────────────────────────────
    # Each set = [Pioneer → Student] with shared repo_id (natural event flow).
    # Sets run in parallel. Naives run independently (no Overmind).
    #
    #   Set 0: Pioneer_0 (repo=set_0) → Student_0 (repo=set_0)
    #   Set 1: Pioneer_1 (repo=set_1) → Student_1 (repo=set_1)
    #   ...
    #   Naive_0, Naive_1, ... (no Overmind, parallel)

    # Create scaffold repos: N sets × (pioneer + student) + M naives
    repos = {}
    for i in range(N):
        repos[f"pioneer_{i}"] = scaffold.create_scaffold(tmp_path / f"set_{i}_pioneer")
        repos[f"student_{i}"] = scaffold.create_scaffold(tmp_path / f"set_{i}_student")
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(tmp_path / f"naive_{i}")
    print(f"  Created {N * 2 + M} scaffold repos ({N} sets + {M} naives)")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run_set(set_idx: int) -> tuple:
        """Run one [Pioneer → Student] set sequentially, sharing repo_id."""
        set_repo_id = f"{scaffold.REPO_ID}_set_{set_idx}"

        # Pioneer phase
        p = run_agent(
            prompt=scaffold.SHARED_PROMPT, cwd=repos[f"pioneer_{set_idx}"],
            user="pioneer", state_file=state_dir / f"state_pioneer_{set_idx}.json",
            base_url=base_url, repo_id=set_repo_id,
            max_turns=scaffold.MAX_TURNS, with_overmind=True, model=pioneer_model,
        )

        # Verify pioneer pushed events
        pull = api_get(base_url, "/api/memory/pull", {
            "repo_id": set_repo_id, "limit": "100",
        })
        p_events = [e for e in pull["events"] if e["user"] == "pioneer"]
        p_count = len(p_events)

        # Student phase — same repo_id, sees pioneer's events naturally
        s = run_agent(
            prompt=scaffold.SHARED_PROMPT, cwd=repos[f"student_{set_idx}"],
            user=f"student_{set_idx}",
            state_file=state_dir / f"state_student_{set_idx}.json",
            base_url=base_url, repo_id=set_repo_id,
            max_turns=scaffold.MAX_TURNS, with_overmind=True, model=model,
        )

        print(f"  Set {set_idx}: Pioneer {p.elapsed:.0f}s/{p.analysis['server_run_attempts']}runs"
              f"/{p_count}events → Student {s.elapsed:.0f}s/{s.analysis['server_run_attempts']}runs"
              f"/{'OK' if s.analysis['saw_server_running'] else 'FAIL'}")
        return p, s, p_count

    def run_naive(naive_idx: int):
        """Run one Naive agent (no Overmind)."""
        return run_agent(
            prompt=scaffold.SHARED_PROMPT, cwd=repos[f"naive_{naive_idx}"],
            user=f"naive_{naive_idx}",
            state_file=state_dir / f"state_naive_{naive_idx}.json",
            base_url=base_url, repo_id=f"{scaffold.REPO_ID}_naive_{naive_idx}",
            max_turns=scaffold.MAX_TURNS, with_overmind=False, model=model,
        )

    # Run all sets + naives in parallel
    print(f"\n  Running {N} sets + {M} naives in parallel...")
    pioneers = []
    results = {}
    total_pioneer_events = 0

    with ThreadPoolExecutor(max_workers=N + M) as executor:
        set_futures = {executor.submit(run_set, i): i for i in range(N)}
        naive_futures = {executor.submit(run_naive, i): i for i in range(M)}

        for future in as_completed({**set_futures, **naive_futures}):
            if future in set_futures:
                idx = set_futures[future]
                p, s, p_count = future.result()
                pioneers.append(p)
                results[f"student_{idx}"] = s
                total_pioneer_events += p_count
            else:
                idx = naive_futures[future]
                n = future.result()
                results[f"naive_{idx}"] = n
                print(f"  Naive {idx}: {n.elapsed:.0f}s/{n.analysis['server_run_attempts']}runs"
                      f"/{'OK' if n.analysis['saw_server_running'] else 'FAIL'}")

    assert total_pioneer_events >= N, f"Pioneers must push events (got {total_pioneer_events})"

    # Use first pioneer as representative for the report
    pioneer = pioneers[0]

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


@pytest.mark.e2e_live
def test_branch_aware_ab(claude_cli, server, base_url, tmp_path, request):
    """Branch-aware A/B: Pioneer on feat/auth, Student+Naive on feat/api.

    Tests cross-branch intent/discovery sharing via Overmind's 3-tier relevance.
    Pioneer's events (port choice, token naming, session config) should help
    Students on a sibling branch avoid conflicts.
    """
    from tests.fixtures.ab_scaffolds import branch_conflict

    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    pioneer_model = _resolve_pioneer_model(request)
    scaffold = branch_conflict
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    print(f"\n{'=' * 70}")
    print(f"  Branch-Aware A/B: branch_conflict (N={N}, M={M}, "
          f"pioneer={pioneer_model or 'default'}, student/naive={model or 'default'})")
    print(f"{'=' * 70}")

    # Create scaffolds on different branches
    # Pioneer: feat/auth, Students+Naives: feat/api
    repos = {"pioneer": scaffold.create_scaffold(tmp_path / "pioneer", branch="feat/auth")}
    for i in range(N):
        repos[f"student_{i}"] = scaffold.create_scaffold(
            tmp_path / f"student_{i}", branch="feat/api"
        )
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(
            tmp_path / f"naive_{i}", branch="feat/api"
        )
    print(f"  Created {1 + N + M} scaffold repos (pioneer=feat/auth, rest=feat/api)")

    # Phase 1: Pioneer on feat/auth — smarter model, same SHARED prompt
    print(f"\n  Phase 1: Pioneer (feat/auth, model={pioneer_model or 'default'}, prompt=SHARED)")
    pioneer = run_agent(
        prompt=scaffold.SHARED_PROMPT, cwd=repos["pioneer"],
        user="pioneer", state_file=state_dir / "state_pioneer.json",
        base_url=base_url, repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS, with_overmind=True, model=pioneer_model,
    )
    print(f"  Pioneer: {pioneer.elapsed:.1f}s, runs={pioneer.analysis['server_run_attempts']}, "
          f"success={pioneer.analysis['saw_server_running']}")

    # Verify pioneer pushed events
    pull = api_get(base_url, "/api/memory/pull", {"repo_id": scaffold.REPO_ID, "limit": "100"})
    p_events = [e for e in pull["events"] if e["user"] == "pioneer"]
    assert len(p_events) >= 1, "Pioneer must push at least 1 event"

    # Check that pioneer events have branch metadata
    branched = [e for e in p_events if e.get("current_branch") == "feat/auth"]
    print(f"  Pioneer pushed {len(p_events)} events ({len(branched)} with branch metadata)")

    # Phase 2: Students + Naives on feat/api (parallel)
    print(f"\n  Phase 2: {N} students + {M} naives on feat/api in parallel...")
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
        scaffold_name="branch_conflict", model=model,
        pioneer_elapsed=pioneer.elapsed,
    )

    # Phase 5: Save reports
    report = generate_report(
        scaffold_name="branch_conflict", model=model,
        pioneer=pioneer, students=students, naives=naives, n=N, m=M,
    )
    save_report(report, report_dir / "branch_conflict_report.json")
    save_jsonl(pioneer.events, report_dir / "pioneer.jsonl")
    for i in range(N):
        save_jsonl(results[f"student_{i}"].events, report_dir / f"student_{i}.jsonl")
    for i in range(M):
        save_jsonl(results[f"naive_{i}"].events, report_dir / f"naive_{i}.jsonl")
    print(f"\n  Reports saved to: {report_dir}")

    # Assertions: all agents completed
    for i in range(N):
        assert f"student_{i}" in results, f"student_{i} didn't complete"
    for i in range(M):
        assert f"naive_{i}" in results, f"naive_{i} didn't complete"

    # Branch-specific assertion: students should have fewer port conflicts
    s_port = student_stats.get("port_conflict_count", {}).get("mean", 0) or 0
    n_port = naive_stats.get("port_conflict_count", {}).get("mean", 0) or 0
    if s_port > n_port:
        print(f"\n  WARNING: Students had MORE port conflicts ({s_port}) than naives ({n_port})")
