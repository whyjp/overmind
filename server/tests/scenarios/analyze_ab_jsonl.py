"""Analyze A/B test conversation JSONL — tool-use sequence + metrics extraction.

Usage:
  python analyze_ab_jsonl.py <state_dir>
  python analyze_ab_jsonl.py  # uses latest pytest temp dir

Outputs:
  - Tool-use sequence per agent (with markers)
  - Behavioral metrics comparison table
  - proactive_config_fix determination
  - Optional: --json flag for machine-readable output
"""

import json
import sys
from pathlib import Path


def extract_tool_sequence(jsonl_path: Path) -> list[dict]:
    """Extract ordered tool-use steps from conversation JSONL."""
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(l) for l in lines if l.strip()]
    sequence = []
    pending = None

    for evt in events:
        if evt.get("type") == "assistant":
            msg = evt.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue
                tool = block["name"]
                inp = block.get("input", {})
                step = {"tool": tool, "detail": "", "markers": []}

                if tool == "Bash":
                    cmd = inp.get("command", "")
                    step["detail"] = cmd[:120]
                    # Server run: bash start.sh OR python server.py
                    step["is_server_run"] = (
                        ("start.sh" in cmd)
                        or ("server.py" in cmd and ("python" in cmd or "python3" in cmd))
                    )
                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    fn = fp.rsplit("/", 1)[-1] if "/" in fp else fp
                    step["detail"] = fn
                    step["is_config_edit"] = "config.toml" in fn
                    step["is_src_edit"] = "/src/" in fp
                    if tool == "Edit":
                        step["old_string"] = inp.get("old_string", "")[:80]
                        step["new_string"] = inp.get("new_string", "")[:80]
                    elif tool == "Write":
                        step["content_preview"] = inp.get("content", "")[:80]
                elif tool == "Read":
                    fp = inp.get("file_path", "").replace("\\", "/")
                    step["detail"] = fp.rsplit("/", 1)[-1] if "/" in fp else fp
                else:
                    step["detail"] = tool

                pending = step
                sequence.append(step)

        elif evt.get("type") == "user" and pending:
            result = evt.get("tool_use_result")
            if result:
                txt = ""
                if isinstance(result, dict):
                    txt = str(result.get("stdout", "")) + str(result.get("stderr", ""))
                else:
                    txt = str(result)
                if "CONFIGURATION ERROR" in txt:
                    pending["markers"].append("CONFIG_ERROR")
                if "[Hive] Server running" in txt:
                    pending["markers"].append("SERVER_OK")
            pending = None

    return sequence


def extract_result_event(jsonl_path: Path) -> dict:
    """Extract the final result event from JSONL."""
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        evt = json.loads(line)
        if evt.get("type") == "result":
            return evt
    return {}


def compute_metrics(sequence: list[dict], result_evt: dict) -> dict:
    """Compute all benchmark metrics from tool sequence."""
    first_config_edit = None
    first_server_run = None
    server_runs = 0
    config_edits_raw = 0
    src_edits = 0
    saw_config_error = False
    saw_server_running = False

    # For logical edit dedup: track consecutive identical Edit old_strings
    prev_edit_old = None
    config_logical_edits = 0

    for i, step in enumerate(sequence):
        # Server run detection
        if step.get("is_server_run"):
            server_runs += 1
            if first_server_run is None:
                first_server_run = i + 1

        # Config edit detection
        if step.get("is_config_edit"):
            config_edits_raw += 1
            if first_config_edit is None:
                first_config_edit = i + 1

            # Logical edit: count consecutive same Edit as 1
            old = step.get("old_string", "")
            if step["tool"] == "Edit" and old == prev_edit_old:
                pass  # retry, don't count
            else:
                config_logical_edits += 1
            prev_edit_old = old if step["tool"] == "Edit" else None

        # Src edit detection
        if step.get("is_src_edit"):
            src_edits += 1

        # Error / success markers
        if "CONFIG_ERROR" in step.get("markers", []):
            saw_config_error = True
        if "SERVER_OK" in step.get("markers", []):
            saw_server_running = True

    # Primary metric
    proactive = False
    if first_config_edit is not None:
        if first_server_run is None:
            proactive = True  # edited config but never ran server (edge case)
        elif first_config_edit < first_server_run:
            proactive = True

    return {
        "proactive_config_fix": proactive,
        "first_config_edit_step": first_config_edit,
        "first_server_run_step": first_server_run,
        "server_run_attempts": server_runs,
        "config_logical_edits": config_logical_edits,
        "config_edits_raw": config_edits_raw,
        "src_file_edits": src_edits,
        "saw_config_error": saw_config_error,
        "saw_server_running": saw_server_running,
        "total_tool_uses": len(sequence),
        "total_turns": result_evt.get("num_turns", "?"),
        "duration_s": round(result_evt.get("duration_ms", 0) / 1000, 1),
        "total_cost_usd": result_evt.get("total_cost_usd", "?"),
    }


def print_sequence(name: str, sequence: list[dict]):
    """Print formatted tool-use sequence."""
    print(f"\n{'='*65}")
    print(f"  {name} - Tool Sequence ({len(sequence)} steps)")
    print(f"{'='*65}")

    for i, step in enumerate(sequence, 1):
        tool = step["tool"]
        detail = step.get("detail", "")
        tags = []

        if step.get("is_server_run"):
            tags.append("RUN")
        if step.get("is_config_edit"):
            tags.append("CONFIG")
        if step.get("is_src_edit"):
            tags.append("SRC!")
        for m in step.get("markers", []):
            tags.append(m)

        tag_str = f"  <<< {', '.join(tags)}" if tags else ""

        # Shorten absolute paths for readability
        if len(detail) > 60:
            parts = detail.replace("\\", "/").split("/")
            if len(parts) > 3:
                detail = ".../" + "/".join(parts[-3:])

        print(f"  {i:2d}. {tool:6s} {detail[:60]}{tag_str}")


def print_metrics_table(agents: dict[str, dict]):
    """Print comparison table of all agents' metrics."""
    names = list(agents.keys())
    metrics_order = [
        "proactive_config_fix",
        "first_config_edit_step",
        "first_server_run_step",
        "server_run_attempts",
        "config_logical_edits",
        "config_edits_raw",
        "src_file_edits",
        "saw_config_error",
        "saw_server_running",
        "total_tool_uses",
        "total_turns",
        "duration_s",
        "total_cost_usd",
    ]

    # Header
    header = f"  {'Metric':<28}"
    for n in names:
        header += f" {n:>14}"
    print(f"\n{'='*65}")
    print("  Metrics Comparison")
    print(f"{'='*65}")
    print(header)
    print(f"  {'-'*28}" + f" {'-'*14}" * len(names))

    for m in metrics_order:
        row = f"  {m:<28}"
        for n in names:
            val = agents[n].get(m, "?")
            if isinstance(val, bool):
                display = "YES" if val else "No"
            elif isinstance(val, float):
                display = f"{val:.1f}"
            else:
                display = str(val)

            # Highlight proactive_config_fix
            if m == "proactive_config_fix" and val is True:
                display = "** YES **"

            row += f" {display:>14}"
        print(row)


def main():
    # Find state directory
    if len(sys.argv) >= 2:
        base = Path(sys.argv[1])
    else:
        # Try to find latest pytest temp dir
        tmp_base = Path.home() / "AppData" / "Local" / "Temp" / "pytest-of-cxx"
        if not tmp_base.exists():
            tmp_base = Path("/tmp") / "pytest-of-cxx"
        if tmp_base.exists():
            # Find latest pytest-N directory
            dirs = sorted(tmp_base.glob("pytest-*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for d in dirs:
                candidates = list(d.glob("ab_states*"))
                if candidates:
                    base = candidates[0]
                    break
            else:
                print("No ab_states directory found. Provide path as argument.")
                sys.exit(1)
        else:
            print(f"Temp directory not found. Provide state_dir path as argument.")
            sys.exit(1)

    print(f"State directory: {base}")

    agent_configs = [
        ("Pioneer", "conversation_agent_pioneer.jsonl"),
        ("Student (+OM)", "conversation_agent_student.jsonl"),
        ("Naive (Control)", "conversation_agent_naive.jsonl"),
    ]

    all_metrics = {}

    for name, filename in agent_configs:
        path = base / filename
        if not path.exists():
            print(f"  {filename} not found, skipping")
            continue

        seq = extract_tool_sequence(path)
        result_evt = extract_result_event(path)
        metrics = compute_metrics(seq, result_evt)
        all_metrics[name] = metrics

        print_sequence(name, seq)

        print(f"\n  Summary:")
        print(f"    proactive_config_fix: {'YES' if metrics['proactive_config_fix'] else 'No'}")
        print(f"    first config edit: step {metrics['first_config_edit_step']}")
        print(f"    first server run:  step {metrics['first_server_run_step']}")
        print(f"    server runs: {metrics['server_run_attempts']}")
        print(f"    config edits: {metrics['config_logical_edits']} logical "
              f"({metrics['config_edits_raw']} raw)")

    if len(all_metrics) >= 2:
        print_metrics_table(all_metrics)

    # JSON output if requested
    if "--json" in sys.argv:
        json_path = base / "metrics.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(all_metrics, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Metrics JSON saved to: {json_path}")

    print()


if __name__ == "__main__":
    main()
