# server/tests/scenarios/test_live_agents_AB_multistage.py
"""A/B Test - Multi-Stage Failure Cascade (Node.js scaffold).

A Node.js app with npm install + config.toml parsing across 6 source files.
Each module reads a different config section and throws a raw JS exception
(TypeError, ReferenceError, assertion) when the section is missing/malformed.

Failure cascade (9 stages — 6 missing sections + 3 value traps):
  Stage 1: npm install (succeeds but adds realistic delay/noise)
  Stage 2: start.sh → TypeError: Cannot read properties of undefined ('host')
            (in src/network.js — config.server is undefined)
  Stage 3: fix [server] → RangeError: server.env must be one of: production, staging, development
            (in src/network.js — env field validation)
  Stage 4: fix env → ENOENT: no such file './keys/hmac.key'
            (in src/auth.js — config.auth.key_file points to wrong path)
  Stage 5: fix key_file → TypeError: Cannot read properties of undefined ('store')
            (in src/session.js — config.session is undefined)
  Stage 6: fix [session] → AssertionError: ttl must be a positive integer
            (in src/session.js — ttl_seconds must be positive int, ≥60)
  Stage 7: fix ttl → TypeError: handler.paths is not iterable
            (in src/routes.js — config.routes is undefined)
  Stage 8: fix [routes] with paths array → Error: middleware_order must be non-empty array of strings
            (in src/middleware.js — config.middleware is undefined)
  Stage 9: fix [middleware] → Error: log format must match '<level>:<target>' pattern
            (in src/logging.js — config.logging with format validation)
  Stage 10: fix [logging] → server starts OK

Pioneer must iterate: run → fail → read source → fix → run → fail → ...
Student sees Pioneer's events (many config edits + diffs) → applies all fixes proactively.
Naive repeats Pioneer's path.

Key metrics:
  proactive_config_fix: Student edits config BEFORE first start.sh run
  server_run_attempts: Pioneer ~6-9, Student 1-2, Naive ~6-9
  src_file_reads: Student should need fewer source reads
"""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from overmind.api import create_app
from tests.fixtures.ab_runner import (
    AgentResult,
    api_get,
    check_src_modified,
    require_claude_cli,
    run_agent,
    save_jsonl,
)
from tests.fixtures.ab_scaffolds.multistage import (
    MAX_TURNS,
    REPO_ID,
    SHARED_PROMPT,
    check_config,
    create_scaffold,
)
from tests.fixtures.server_helpers import ServerThread

OVERMIND_PORT = int(os.environ.get("TEST_OVERMIND_PORT", "17996"))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def claude_cli():
    require_claude_cli()


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
        self, request, claude_cli, server, base_url, repo_dirs, state_dir,
    ):
        model = request.config.getoption("--agent-model")

        # ── Phase 1: Pioneer ──
        print("\n" + "=" * 70)
        print("  Phase 1: Pioneer (multi-stage discovery)")
        print("=" * 70)

        pioneer = run_agent(
            SHARED_PROMPT, repo_dirs["agent_pioneer"], "agent_pioneer",
            state_dir / "state_pioneer.json", base_url,
            repo_id=REPO_ID, max_turns=MAX_TURNS, model=model,
            with_overmind=True,
        )
        p_analysis = pioneer.analysis
        p_result = pioneer.result_event

        print(f"  Time: {pioneer.elapsed:.1f}s  Turns: {p_result.get('num_turns', '?')}")
        print(f"  start.sh runs: {p_analysis['server_run_attempts']}")
        print(f"  config edits:  {p_analysis['config_toml_edits']}")
        print(f"  src/ reads:    {p_analysis['src_file_reads']} ({p_analysis['src_files_read']})")
        print(f"  src/ edits:    {p_analysis['src_file_edits']}")
        print(f"  proactive fix: {p_analysis['proactive_config_fix']}")
        print(f"  1st edit step: {p_analysis['first_config_edit_step']}")
        print(f"  1st run step:  {p_analysis['first_server_run_step']}")
        print(f"  saw error:     {p_analysis['saw_error']}")
        print(f"  server OK:     {p_analysis['saw_server_running']}")
        print(f"  config state:  {check_config(repo_dirs['agent_pioneer'])}")

        # Verify Pioneer pushed events
        p_server = api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "limit": "50",
        })
        p_pushed = [e for e in p_server["events"] if e["user"] == "agent_pioneer"]
        assert len(p_pushed) >= 1, "Pioneer must push events"
        print(f"  Overmind events: {len(p_pushed)}")

        # Show pushed event content (for debugging enrichment quality)
        print(f"\n  Pioneer's pushed events:")
        for e in p_pushed[:5]:
            result_preview = e["result"][:120].replace("\n", "\\n")
            print(f"    [{e.get('scope', '?')}] {result_preview}")

        # ── Phase 2: Student vs Naive ──
        print("\n" + "=" * 70)
        print("  Phase 2: Student (+Overmind) vs Naive (Control)")
        print("=" * 70)

        # Show what Student will receive
        pull_preview = api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "20",
        })
        print(f"\n  Events for Student's pull: {pull_preview['count']}")
        for e in pull_preview["events"][:5]:
            print(f"    [{e['user']}] {e['result'][:80]}")
        print(f"  Events for Naive: 0\n")

        ab_results: dict[str, AgentResult] = {}

        def run_ab(name: str, overmind: bool):
            ab_results[name] = run_agent(
                SHARED_PROMPT, repo_dirs[name], name,
                state_dir / f"state_{name}.json", base_url,
                repo_id=REPO_ID, max_turns=MAX_TURNS, model=model,
                with_overmind=overmind,
            )

        ta = threading.Thread(target=run_ab, args=("agent_student", True))
        tb = threading.Thread(target=run_ab, args=("agent_naive", False))
        ta.start(); tb.start()
        ta.join(timeout=600); tb.join(timeout=600)

        assert "agent_student" in ab_results, "Student didn't complete"
        assert "agent_naive" in ab_results, "Naive didn't complete"

        student = ab_results["agent_student"]
        naive = ab_results["agent_naive"]
        s_analysis = student.analysis
        n_analysis = naive.analysis

        # ── Phase 3: Behavioral Comparison ──
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison")
        print("=" * 70)

        metrics = [
            "proactive_config_fix",
            "first_config_edit_step", "first_server_run_step",
            "server_run_attempts", "config_toml_edits",
            "src_file_reads", "src_file_edits",
            "saw_error", "saw_server_running", "total_tool_uses",
        ]

        print(f"\n  {'Metric':<25} {'Pioneer':>10} {'Student':>10} {'Naive':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for m in metrics:
            print(f"  {m:<25} {str(p_analysis[m]):>10} {str(s_analysis[m]):>10} {str(n_analysis[m]):>10}")
        print(f"  {'time (s)':<25} {pioneer.elapsed:>10.1f} {student.elapsed:>10.1f} {naive.elapsed:>10.1f}")
        print(f"  {'turns':<25} {str(p_result.get('num_turns','?')):>10} "
              f"{str(student.result_event.get('num_turns','?')):>10} "
              f"{str(naive.result_event.get('num_turns','?')):>10}")

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

        pull_all = api_get(base_url, "/api/memory/pull", {
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

        # ── Phase 5: Key Results + Assertions ──
        print("\n" + "=" * 70)
        print("  Phase 5: KEY RESULTS + ASSERTIONS")
        print("=" * 70)

        p_runs = p_analysis["server_run_attempts"]
        s_runs = s_analysis["server_run_attempts"]
        n_runs = n_analysis["server_run_attempts"]

        print(f"\n  Pioneer: {p_runs} start.sh runs (baseline)")
        print(f"  Student: {s_runs} start.sh runs (with Overmind)")
        print(f"  Naive:   {n_runs} start.sh runs (without Overmind)")

        s_proactive = s_analysis["proactive_config_fix"]
        n_proactive = n_analysis["proactive_config_fix"]
        print(f"\n  Student proactive fix: {s_proactive}")
        print(f"  Naive proactive fix:   {n_proactive}")

        # ── Assertion 1: All agents must succeed ──
        p_cfg = check_config(repo_dirs["agent_pioneer"])
        s_cfg = check_config(repo_dirs["agent_student"])
        n_cfg = check_config(repo_dirs["agent_naive"])

        print(f"\n  Config status:")
        print(f"    Pioneer: {p_cfg}")
        print(f"    Student: {s_cfg}")
        print(f"    Naive:   {n_cfg}")

        assert p_cfg.get("all_ok") or p_analysis["saw_server_running"], \
            "Pioneer must solve all stages"
        print("  ASSERT PASS: Pioneer solved all stages")

        assert s_cfg.get("all_ok") or s_analysis["saw_server_running"], \
            "Student must solve all stages"
        print("  ASSERT PASS: Student solved all stages")

        assert n_cfg.get("all_ok") or n_analysis["saw_server_running"], \
            "Naive must solve all stages"
        print("  ASSERT PASS: Naive solved all stages")

        # ── Assertion 2: Student should show Overmind advantage ──
        # Core metric: fewer server runs (fixes all at once after first failure)
        # Secondary: fewer total tool uses, fewer turns
        overmind_advantage = (
            s_runs < n_runs
            or s_analysis["total_tool_uses"] < n_analysis["total_tool_uses"]
            or s_proactive
        )

        advantage_reasons = []
        if s_runs < n_runs:
            advantage_reasons.append(f"{n_runs - s_runs} fewer server runs")
        if s_analysis["total_tool_uses"] < n_analysis["total_tool_uses"]:
            advantage_reasons.append(
                f"{n_analysis['total_tool_uses'] - s_analysis['total_tool_uses']} fewer tool uses"
            )
        if s_proactive:
            advantage_reasons.append("proactive config fix before first run")

        if overmind_advantage:
            print(f"\n  >> OVERMIND ADVANTAGE CONFIRMED:")
            for reason in advantage_reasons:
                print(f"     - {reason}")
        else:
            print(f"\n  >> WARNING: No measurable advantage this run (non-deterministic)")
            print(f"     Student: runs={s_runs}, proactive={s_proactive}, src_reads={s_analysis['src_file_reads']}")
            print(f"     Naive:   runs={n_runs}, proactive={n_proactive}, src_reads={n_analysis['src_file_reads']}")

        # Soft assertion: log warning but don't fail (LLM non-determinism)
        # Hard assertion: Student must not be WORSE than Naive by a large margin
        assert s_runs <= n_runs + 3, (
            f"Student ({s_runs} runs) should not be significantly worse "
            f"than Naive ({n_runs} runs)"
        )
        print("  ASSERT PASS: Student not significantly worse than Naive")

        # ── Assertion 3: No src/ modifications ──
        for name, repo_dir in repo_dirs.items():
            modified = check_src_modified(repo_dir)
            assert not modified, f"{name} modified src/ files: {modified}"
        print("  ASSERT PASS: No agents modified src/ files")

        # ── Save JSONL ──
        save_jsonl(pioneer.events, state_dir / "conversation_agent_pioneer.jsonl")
        save_jsonl(student.events, state_dir / "conversation_agent_student.jsonl")
        save_jsonl(naive.events, state_dir / "conversation_agent_naive.jsonl")

        # ── Save summary JSON for multi-run analysis ──
        summary = {
            "model": model or "default",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pioneer": {
                "server_runs": p_runs,
                "config_edits": p_analysis["config_toml_edits"],
                "src_reads": p_analysis["src_file_reads"],
                "proactive": p_analysis["proactive_config_fix"],
                "success": p_analysis["saw_server_running"],
                "time_s": round(pioneer.elapsed, 1),
                "turns": p_result.get("num_turns"),
            },
            "student": {
                "server_runs": s_runs,
                "config_edits": s_analysis["config_toml_edits"],
                "src_reads": s_analysis["src_file_reads"],
                "proactive": s_proactive,
                "success": s_analysis["saw_server_running"],
                "time_s": round(student.elapsed, 1),
                "turns": student.result_event.get("num_turns"),
            },
            "naive": {
                "server_runs": n_runs,
                "config_edits": n_analysis["config_toml_edits"],
                "src_reads": n_analysis["src_file_reads"],
                "proactive": n_proactive,
                "success": n_analysis["saw_server_running"],
                "time_s": round(naive.elapsed, 1),
                "turns": naive.result_event.get("num_turns"),
            },
            "overmind_advantage": overmind_advantage,
            "advantage_reasons": advantage_reasons,
        }
        summary_path = state_dir / "run_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"\n  JSONL saved to: {state_dir}")
        print(f"  Summary saved to: {summary_path}")
