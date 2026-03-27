#!/usr/bin/env bash
# Run A/B tests in parallel with separate ports and log files.
#
# Usage:
#   bash tests/scenarios/run_ab_parallel.sh              # 5x multistage (default)
#   bash tests/scenarios/run_ab_parallel.sh 10            # 10x multistage
#   bash tests/scenarios/run_ab_parallel.sh 5 complex     # 5x complex
#   bash tests/scenarios/run_ab_parallel.sh 5 all         # 5x each of all 3 tests
#
# Each run gets a unique port (18000+N) so they don't conflict.
# Results are saved to tests/scenarios/parallel_results/

set -euo pipefail
cd "$(dirname "$0")/../.."  # cd to server/

N="${1:-5}"
TEST_TYPE="${2:-multistage}"
MODEL="${AGENT_MODEL:-haiku}"
RESULTS_DIR="tests/scenarios/parallel_results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

echo "========================================"
echo "  Parallel A/B Test Runner"
echo "========================================"
echo "  Runs:    $N"
echo "  Test:    $TEST_TYPE"
echo "  Model:   $MODEL"
echo "  Results: $RESULTS_DIR"
echo "========================================"
echo ""

# Map test type to file
declare -A TEST_FILES
TEST_FILES[single]="tests/scenarios/test_live_agents_AB.py"
TEST_FILES[multistage]="tests/scenarios/test_live_agents_AB_multistage.py"
TEST_FILES[complex]="tests/scenarios/test_live_agents_AB_complex.py"

run_test() {
    local idx=$1
    local test_file=$2
    local test_name=$3
    local port=$((18000 + idx))
    local log_file="$RESULTS_DIR/${test_name}_run${idx}.log"

    echo "  [${test_name}#${idx}] Starting on port ${port}..."
    TEST_OVERMIND_PORT=$port AGENT_MODEL=$MODEL \
        uv run pytest "$test_file" -m e2e_live -s \
        > "$log_file" 2>&1
    local rc=$?

    # Extract key metrics from log (Phase 5 output)
    local pioneer_runs=$(grep 'Pioneer:' "$log_file" | grep 'start.sh' | tail -1 | sed 's/.*Pioneer: \([0-9]*\).*/\1/' 2>/dev/null || echo "?")
    local student_runs=$(grep 'Student:' "$log_file" | grep 'start.sh' | tail -1 | sed 's/.*Student: \([0-9]*\).*/\1/' 2>/dev/null || echo "?")
    local naive_runs=$(grep 'Naive:' "$log_file" | grep 'start.sh' | tail -1 | sed 's/.*Naive: *\([0-9]*\).*/\1/' 2>/dev/null || echo "?")
    local status="PASS"
    if [ $rc -ne 0 ]; then status="FAIL"; fi

    echo "  [${test_name}#${idx}] ${status}  Pioneer=${pioneer_runs} Student=${student_runs} Naive=${naive_runs}"

    # Write summary line for aggregation
    echo "${test_name},${idx},${status},${pioneer_runs},${student_runs},${naive_runs}" \
        >> "$RESULTS_DIR/summary.csv"
}

# CSV header
echo "test,run,status,pioneer_runs,student_runs,naive_runs" > "$RESULTS_DIR/summary.csv"

# Launch parallel runs
PIDS=()

if [ "$TEST_TYPE" = "all" ]; then
    for test_name in single multistage complex; do
        test_file="${TEST_FILES[$test_name]}"
        for i in $(seq 1 "$N"); do
            idx=$(( ($(echo "$test_name" | cksum | cut -d' ' -f1) % 1000) * 100 + i ))
            run_test "$idx" "$test_file" "$test_name" &
            PIDS+=($!)
        done
    done
else
    test_file="${TEST_FILES[$TEST_TYPE]}"
    if [ -z "$test_file" ]; then
        echo "Unknown test type: $TEST_TYPE"
        echo "Valid: single, multistage, complex, all"
        exit 1
    fi
    for i in $(seq 1 "$N"); do
        run_test "$i" "$test_file" "$TEST_TYPE" &
        PIDS+=($!)
    done
fi

echo ""
echo "  Waiting for ${#PIDS[@]} parallel runs..."
echo ""

# Wait for all
FAILURES=0
for pid in "${PIDS[@]}"; do
    wait "$pid" || ((FAILURES++))
done

echo ""
echo "========================================"
echo "  Results Summary"
echo "========================================"

# Parse CSV and show aggregated results
python3 -c "
import csv, sys
from pathlib import Path
from collections import defaultdict

csv_path = Path('$RESULTS_DIR/summary.csv')
rows = list(csv.DictReader(csv_path.open()))

by_test = defaultdict(list)
for r in rows:
    by_test[r['test']].append(r)

for test_name, runs in sorted(by_test.items()):
    print(f'\n  {test_name} ({len(runs)} runs):')
    print(f'  {\"Run\":>5} {\"Status\":>8} {\"Pioneer\":>10} {\"Student\":>10} {\"Naive\":>10} {\"Diff\":>8}')
    print(f'  {\"-\"*5:>5} {\"-\"*8:>8} {\"-\"*10:>10} {\"-\"*10:>10} {\"-\"*10:>10} {\"-\"*8:>8}')

    p_total = s_total = n_total = 0
    valid = 0
    wins = 0
    for r in runs:
        p, s, n = r['pioneer_runs'], r['student_runs'], r['naive_runs']
        diff = ''
        if p.isdigit() and s.isdigit() and n.isdigit():
            pi, si, ni = int(p), int(s), int(n)
            p_total += pi; s_total += si; n_total += ni
            valid += 1
            delta = ni - si
            diff = f'{delta:+d}' if delta != 0 else '0'
            if si < ni: wins += 1
        print(f'  {r[\"run\"]:>5} {r[\"status\"]:>8} {p:>10} {s:>10} {n:>10} {diff:>8}')

    if valid > 0:
        print(f'  {\"AVG\":>5} {\"\":>8} {p_total/valid:>10.1f} {s_total/valid:>10.1f} {n_total/valid:>10.1f}')
        print(f'  Student < Naive: {wins}/{valid} runs ({wins/valid*100:.0f}%)')
"

echo ""
echo "  CSV: $RESULTS_DIR/summary.csv"
echo "  Logs: $RESULTS_DIR/"
echo "  Failures: $FAILURES"
echo "========================================"
