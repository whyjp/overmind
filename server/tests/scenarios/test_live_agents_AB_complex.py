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
from tests.fixtures.ab_scaffolds import complex as complex_scaffold
from tests.fixtures.ab_scaffolds.complex import (
    REPO_ID,
    MAX_TURNS,
    SHARED_PROMPT,
    create_scaffold,
)
from tests.fixtures.server_helpers import ServerThread

OVERMIND_PORT = int(os.environ.get("TEST_OVERMIND_PORT", "17995"))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def claude_cli():
    require_claude_cli()

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

    def test_complex_ab(self, claude_cli, server, base_url, repo_dirs, state_dir, request):

        # == Phase 1: Pioneer ==
        print("\n" + "=" * 70)
        print("  Phase 1: Pioneer (8-subsystem discovery)")
        print("=" * 70)

        p_result = run_agent(
            SHARED_PROMPT, repo_dirs["agent_pioneer"], "agent_pioneer",
            state_dir / "state_pioneer.json", base_url,
            repo_id=REPO_ID, max_turns=MAX_TURNS,
            model=request.config.getoption("--agent-model"),
            with_overmind=True,
        )

        print(f"  Time: {p_result.elapsed:.1f}s  Turns: {p_result.result_event.get('num_turns', '?')}")
        print(f"  start.sh runs: {p_result.analysis['server_run_attempts']}")
        print(f"  config edits:  {p_result.analysis['config_toml_edits']}")
        print(f"  src/ reads:    {p_result.analysis['src_file_reads']} ({p_result.analysis['src_files_read']})")
        print(f"  src/ edits:    {p_result.analysis['src_file_edits']}")
        print(f"  saw error:     {p_result.analysis['saw_error']}")
        print(f"  server OK:     {p_result.analysis['saw_server_running']}")

        p_server = api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "limit": "100"})
        p_pushed = [e for e in p_server["events"] if e["user"] == "agent_pioneer"]
        assert len(p_pushed) >= 1, "Pioneer must push events"
        print(f"  Overmind events: {len(p_pushed)}")

        # == Phase 2: Student vs Naive ==
        print("\n" + "=" * 70)
        print("  Phase 2: Student (+Overmind) vs Naive (Control)")
        print("=" * 70)

        pull_preview = api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "30",
        })
        print(f"\n  Events for Student's pull: {pull_preview['count']}")
        print(f"  Events for Naive: 0\n")

        ab_results: dict[str, AgentResult] = {}

        def run_ab(name, overmind):
            ab_results[name] = run_agent(
                SHARED_PROMPT, repo_dirs[name], name,
                state_dir / f"state_{name}.json", base_url,
                repo_id=REPO_ID, max_turns=MAX_TURNS,
                model=request.config.getoption("--agent-model"),
                with_overmind=overmind,
            )

        ta = threading.Thread(target=run_ab, args=("agent_student", True))
        tb = threading.Thread(target=run_ab, args=("agent_naive", False))
        ta.start(); tb.start()
        ta.join(timeout=600); tb.join(timeout=600)

        assert "agent_student" in ab_results, "Student didn't complete"
        assert "agent_naive" in ab_results, "Naive didn't complete"

        s = ab_results["agent_student"].analysis
        n = ab_results["agent_naive"].analysis

        # == Phase 3: Comparison ==
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison")
        print("=" * 70)

        metrics = ["server_run_attempts", "config_toml_edits", "src_file_reads",
                    "src_file_edits", "saw_error", "saw_server_running", "total_tool_uses"]

        print(f"\n  {'Metric':<25} {'Pioneer':>10} {'Student':>10} {'Naive':>10}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for m in metrics:
            print(f"  {m:<25} {str(p_result.analysis[m]):>10} {str(s[m]):>10} {str(n[m]):>10}")
        print(f"  {'time (s)':<25} {p_result.elapsed:>10.1f} {ab_results['agent_student'].elapsed:>10.1f} {ab_results['agent_naive'].elapsed:>10.1f}")
        print(f"  {'turns':<25} {str(p_result.result_event.get('num_turns','?')):>10} "
              f"{str(ab_results['agent_student'].result_event.get('num_turns','?')):>10} "
              f"{str(ab_results['agent_naive'].result_event.get('num_turns','?')):>10}")

        print(f"\n  src/ files read:")
        print(f"    Pioneer: {p_result.analysis['src_files_read']}")
        print(f"    Student: {s['src_files_read']}")
        print(f"    Naive:   {n['src_files_read']}")

        # == Phase 4: Pull Impact ==
        print("\n" + "=" * 70)
        print("  Phase 4: Pull Impact")
        print("=" * 70)

        pull_all = api_get(base_url, "/api/memory/pull", {"repo_id": REPO_ID, "limit": "200"})
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

        pr = p_result.analysis["server_run_attempts"]
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
        for name, result in [("agent_pioneer", p_result),
                              ("agent_student", ab_results.get("agent_student")),
                              ("agent_naive", ab_results.get("agent_naive"))]:
            if result is not None:
                save_jsonl(result.events, state_dir / f"conversation_{name}.jsonl")
        print(f"\n  JSONL saved to: {state_dir}")
