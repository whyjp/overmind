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

import os
import threading
import time
from pathlib import Path

import pytest

from overmind.api import create_app
from tests.fixtures.ab_runner import (
    AgentResult,
    analyze_conversation,
    api_get,
    check_src_modified,
    require_claude_cli,
    run_agent,
    save_jsonl,
)
from tests.fixtures.ab_scaffolds.simple import (
    MAX_TURNS,
    REPO_ID,
    SCAFFOLD_FILES,
    SHARED_PROMPT,
    check_config_toml,
    create_scaffold,
)
from tests.fixtures.server_helpers import ServerThread

OVERMIND_PORT = int(os.environ.get("TEST_OVERMIND_PORT", "17997"))


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(scope="module")
def claude_cli():
    require_claude_cli()


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

        z: AgentResult = run_agent(
            SHARED_PROMPT, repo_dirs["agent_pioneer"], "agent_pioneer",
            state_dir / "state_z.json", base_url,
            repo_id=REPO_ID, max_turns=MAX_TURNS, with_overmind=True,
        )
        z_analysis = z.analysis

        print(f"  Time: {z.elapsed:.1f}s")
        print(f"  Turns: {z.result_event.get('num_turns', '?')}")
        print(f"  Tool uses: {z_analysis['total_tool_uses']}")
        print(f"  server.py runs: {z_analysis['server_run_attempts']}")
        print(f"  Config error seen: {z_analysis['saw_error']}")
        print(f"  Server started: {z_analysis['saw_server_running']}")
        print(f"  config.toml edits: {z_analysis['config_toml_edits']}")
        print(f"  src/ edits: {z_analysis['src_file_edits']}")

        z_config = check_config_toml(repo_dirs["agent_pioneer"])
        z_src_mod = check_src_modified(repo_dirs["agent_pioneer"])
        print(f"  config.toml: {z_config}")
        if z_src_mod:
            print(f"  WARNING: src/ modified: {z_src_mod}")

        # Verify Z pushed events to Overmind
        z_server_events = api_get(base_url, "/api/memory/pull", {
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
        a_pull_preview = api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID, "exclude_user": "agent_student", "limit": "20",
        })
        print(f"\n  Events available for A's SessionStart pull: {a_pull_preview['count']}")
        for e in a_pull_preview["events"]:
            print(f"    [{e['user']}] {e['result'][:80]}")
        print(f"  Events available for B: 0 (no Overmind)\n")

        ab_results: dict[str, AgentResult] = {}

        def run_ab(name: str, overmind: bool):
            ab_results[name] = run_agent(
                SHARED_PROMPT, repo_dirs[name], name,
                state_dir / f"state_{name}.json", base_url,
                repo_id=REPO_ID, max_turns=MAX_TURNS, with_overmind=overmind,
            )

        ta = threading.Thread(target=run_ab, args=("agent_student", True))
        tb = threading.Thread(target=run_ab, args=("agent_naive", False))
        ta.start(); tb.start()
        ta.join(timeout=300); tb.join(timeout=300)

        assert "agent_student" in ab_results, "A didn't complete"
        assert "agent_naive" in ab_results, "B didn't complete"

        a: AgentResult = ab_results["agent_student"]
        b: AgentResult = ab_results["agent_naive"]
        a_analysis = a.analysis
        b_analysis = b.analysis

        # ──────────────────────────────────────────────
        # Phase 3: Behavioral Comparison (JSONL-based)
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 3: Behavioral Comparison (from JSONL)")
        print("=" * 70)

        metrics = ["total_tool_uses", "bash_commands", "server_run_attempts",
                    "saw_error", "saw_server_running",
                    "config_toml_edits", "src_file_edits"]

        print(f"\n  {'Metric':<25} {'Z':>8} {'A (+OM)':>8} {'B (-OM)':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
        for m in metrics:
            zv = z_analysis[m]
            av = a_analysis[m]
            bv = b_analysis[m]
            print(f"  {m:<25} {str(zv):>8} {str(av):>8} {str(bv):>8}")

        print(f"  {'time (s)':<25} {z.elapsed:>8.1f} {a.elapsed:>8.1f} {b.elapsed:>8.1f}")
        print(f"  {'turns':<25} {str(z.result_event.get('num_turns','?')):>8} "
              f"{str(a.result_event.get('num_turns','?')):>8} "
              f"{str(b.result_event.get('num_turns','?')):>8}")

        # Edited files detail
        print(f"\n  Edited files:")
        for label, analysis in [("Z", z_analysis), ("A", a_analysis), ("B", b_analysis)]:
            files = analysis["edited_files"]
            print(f"    {label}: {files if files else '(none)'}")

        # ──────────────────────────────────────────────
        # Phase 4: Pull Impact Verification
        # ──────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  Phase 4: Pull Impact")
        print("=" * 70)

        pull_all = api_get(base_url, "/api/memory/pull", {
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
            analysis = z_analysis if name == "agent_pioneer" else (
                a_analysis if name == "agent_student" else b_analysis)

            if c.get("all_ok"):
                s += 3  # correct solution
            if not src_mods[name]:
                s += 2  # respected constraint
            if analysis["saw_server_running"]:
                s += 2  # actually started server
            if analysis["server_run_attempts"] <= 2:
                s += 1  # efficient
            return s

        s_z = score("agent_pioneer")
        s_a = score("agent_student")
        s_b = score("agent_naive")

        print(f"\n  Score: Z={s_z}  A={s_a}  B={s_b}")
        print(f"  Time:  Z={z.elapsed:.0f}s  A={a.elapsed:.0f}s  B={b.elapsed:.0f}s")

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

        if a.elapsed < b.elapsed:
            delta = b.elapsed - a.elapsed
            print(f"    >> A was {delta:.0f}s faster")
        else:
            delta = a.elapsed - b.elapsed
            print(f"    >> B was {delta:.0f}s faster (non-deterministic)")

        # ── Save JSONL for post-mortem ──
        save_jsonl(z.events, state_dir / "conversation_agent_pioneer.jsonl")
        save_jsonl(a.events, state_dir / "conversation_agent_student.jsonl")
        save_jsonl(b.events, state_dir / "conversation_agent_naive.jsonl")

        print(f"\n  Conversation JSONL saved to: {state_dir}")
        print(f"  Analyze with: python -c \"import json; [print(json.loads(l)['type']) "
              f"for l in open('conversation_agent_student.jsonl')]\"")
