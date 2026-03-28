# Statistical A/B Test Framework Design

**Date**: 2026-03-28
**Status**: Approved
**Goal**: Pioneer 1회 실행 후 Student×N, Naive×M을 병렬로 실제 Claude CLI 에이전트로 반복 실행하여 Overmind의 효과를 통계적으로 검증

## Problem

기존 AB 테스트는 Student 1 + Naive 1로 단일 측정만 수행한다. LLM의 비결정성 때문에 단일 결과로는 Overmind의 실제 효과를 판단하기 어렵다. N/M회 반복하여 mean/median/stddev로 비교해야 신뢰할 수 있는 결과를 얻을 수 있다.

## Architecture

### File Structure

```
tests/fixtures/
  server_helpers.py          # 기존 (변경 없음)
  scaffold_hive.py           # 기존 (변경 없음)
  ab_runner.py               # 신규: 공통 agent runner + 분석 + 통계 + 리포트
  ab_scaffolds/
    __init__.py              # scaffold registry
    simple.py                # test_live_agents_AB.py에서 추출
    multistage.py            # test_live_agents_AB_multistage.py에서 추출
    complex.py               # test_live_agents_AB_complex.py에서 추출

tests/scenarios/
  conftest.py                # --student-n, --naive-m, --agent-model pytest 옵션
  test_live_agents_AB.py            # 리팩토링: ab_runner + simple scaffold
  test_live_agents_AB_multistage.py # 리팩토링: ab_runner + multistage scaffold
  test_live_agents_AB_complex.py    # 리팩토링: ab_runner + complex scaffold
  test_live_agents_AB_statistical.py # 신규: parametrize × scaffold, N/M 병렬 반복
```

### Runtime Directory Layout (per scaffold)

각 agent 인스턴스가 독립된 git repo에서 실행:

```
tmp/
  ab_stat_{scaffold}/
    pioneer/hive-{scaffold}/      # git repo
    student_0/hive-{scaffold}/    # 독립 git repo
    student_1/hive-{scaffold}/
    ...student_{N-1}/
    naive_0/hive-{scaffold}/
    naive_1/hive-{scaffold}/
    ...naive_{M-1}/
    states/                       # OVERMIND_STATE_FILE per agent
    reports/                      # JSON report + JSONL conversation logs
```

## Components

### 1. ab_scaffolds/ — Scaffold Registry

각 scaffold 모듈이 동일 인터페이스:

```python
SCAFFOLD_FILES: dict[str, str]   # 파일 내용
SHARED_PROMPT: str               # agent에게 줄 프롬프트
REPO_NAME: str                   # git repo 디렉토리명
REPO_ID: str                     # Overmind repo_id
MAX_TURNS: int                   # claude --max-turns

def create_scaffold(base_dir: Path) -> Path:
    """git init + files + remote, returns repo_dir"""
```

`__init__.py`에서 registry:
```python
from . import simple, multistage, complex as complex_
SCAFFOLDS: dict[str, ScaffoldModule] = {
    "simple": simple,
    "multistage": multistage,
    "complex": complex_,
}
```

### 2. ab_runner.py — Common Module

기존 3개 파일에서 중복 추출:

```python
@dataclass
class AgentSpec:
    name: str
    cwd: Path
    user: str
    state_file: Path
    with_overmind: bool

@dataclass
class AgentResult:
    result_event: dict
    events: list[dict]
    analysis: dict
    elapsed: float

def run_agent(
    prompt: str, cwd: Path, user: str, state_file: Path,
    base_url: str | None, max_turns: int = 20,
    with_overmind: bool = True, model: str = "",
) -> AgentResult

def run_parallel_agents(
    agents: list[AgentSpec],
    prompt: str, base_url: str, max_turns: int,
    model: str = "", plugin_dir: Path,
) -> dict[str, AgentResult]
    # ThreadPoolExecutor(max_workers=len(agents))

def analyze_conversation(events: list[dict]) -> dict
    # 통합 분석: simple + complex 메트릭 합침
    # server_run_attempts, config_toml_edits, src_file_edits,
    # src_file_reads, src_files_read, saw_error, saw_server_running,
    # total_tool_uses, edited_files, tools_used

def check_config_toml(repo_dir: Path) -> dict
def check_src_modified(repo_dir: Path) -> list[str]

def compute_statistics(analyses: list[dict]) -> dict
    # per numeric metric: mean, median, stddev, min, max, values
    # per boolean metric: count_true, count_false, pct_true

def generate_report(
    scaffold_name: str, model: str,
    pioneer: AgentResult,
    students: list[AgentResult],
    naives: list[AgentResult],
) -> dict

def print_comparison_table(
    pioneer_analysis: dict,
    student_stats: dict,
    naive_stats: dict,
    n: int, m: int,
)

def save_jsonl(events: list[dict], path: Path)
def save_report(report: dict, path: Path)
```

### 3. conftest.py — pytest Options

```python
def pytest_addoption(parser):
    parser.addoption("--student-n", type=int, default=3,
                     help="Number of student (Overmind-enabled) iterations")
    parser.addoption("--naive-m", type=int, default=3,
                     help="Number of naive (no-Overmind) iterations")
    parser.addoption("--agent-model", type=str, default="",
                     help="Claude model for all agents (haiku/sonnet/opus)")
```

### 4. test_live_agents_AB_statistical.py — New Test

```python
@pytest.mark.e2e_live
@pytest.mark.parametrize("scaffold_name", ["simple", "multistage", "complex"])
def test_statistical_ab(scaffold_name, overmind_server, tmp_path, request):
    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    scaffold = SCAFFOLDS[scaffold_name]

    # --- Scaffold creation ---
    repos = {"pioneer": scaffold.create_scaffold(tmp_path / "pioneer")}
    for i in range(N):
        repos[f"student_{i}"] = scaffold.create_scaffold(tmp_path / f"student_{i}")
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(tmp_path / f"naive_{i}")

    # --- Phase 1: Pioneer (sequential) ---
    pioneer_result = run_agent(...)
    # assert pioneer pushed events to Overmind

    # --- Phase 2: Student×N + Naive×M (parallel) ---
    agents = [
        *[AgentSpec(f"student_{i}", ..., with_overmind=True) for i in range(N)],
        *[AgentSpec(f"naive_{i}", ..., with_overmind=False) for i in range(M)],
    ]
    results = run_parallel_agents(agents, ...)

    # --- Phase 3: Analyze + Report ---
    student_analyses = [results[f"student_{i}"].analysis for i in range(N)]
    naive_analyses = [results[f"naive_{i}"].analysis for i in range(M)]
    student_stats = compute_statistics(student_analyses)
    naive_stats = compute_statistics(naive_analyses)

    print_comparison_table(pioneer_result.analysis, student_stats, naive_stats, N, M)

    report = generate_report(scaffold_name, model, pioneer_result,
                             [results[f"student_{i}"] for i in range(N)],
                             [results[f"naive_{i}"] for i in range(M)])
    save_report(report, tmp_path / "reports" / f"{scaffold_name}_report.json")

    # --- Save JSONL ---
    for name, result in results.items():
        save_jsonl(result.events, tmp_path / "reports" / f"{name}.jsonl")

    # --- Assertions ---
    # Pioneer pushed events
    # All students completed
    # All naives completed
    # (soft) student mean attempts < naive mean attempts
```

### 5. Existing File Refactoring

기존 3개 테스트 파일:
- SCAFFOLD_FILES, create_scaffold → `ab_scaffolds/*.py`로 이동
- ServerThread, _run_agent, _api_get, analyze_conversation → `ab_runner.py` import
- 테스트 함수 본체 유지, 공통 함수 호출로 교체
- 기존 동작(N=1, M=1, 병렬 thread) 완전 보존
- `@pytest.mark.e2e_live` 마커 유지

### 6. Report Formats

**Terminal Output:**
```
══════════════════════════════════════════════════
  Statistical A/B: complex (N=3, M=3, model=haiku)
══════════════════════════════════════════════════

  Metric                  Pioneer   Student (N=3)         Naive (M=3)
  ───────────────────── ───────── ───────────────────── ─────────────────
  server_run_attempts         12   2.3 ±0.6 [2,2,3]     10.7 ±1.5 [9,11,12]
  config_toml_edits            9   2.7 ±0.6 [2,3,3]      8.3 ±1.2 [7,8,10]
  time (s)                  142   38.7 ±5.2              128.3 ±12.1
  saw_server_running        True   3/3 (100%)             2/3 (67%)

  >> Student mean attempts 78% fewer than Naive (2.3 vs 10.7)
```

**JSON Report:**
```json
{
  "scaffold": "complex",
  "model": "haiku",
  "timestamp": "2026-03-28T15:00:00Z",
  "config": {"student_n": 3, "naive_m": 3, "max_turns": 35},
  "pioneer": {"server_run_attempts": 12, "config_toml_edits": 9, ...},
  "students": {
    "raw": [{"server_run_attempts": 2, ...}, ...],
    "stats": {"server_run_attempts": {"mean": 2.3, "median": 2, "stddev": 0.6, "min": 2, "max": 3}}
  },
  "naives": {
    "raw": [...],
    "stats": {...}
  },
  "comparison": {
    "attempt_reduction_pct": 78.5,
    "time_reduction_pct": 69.8
  }
}
```

**JSONL Logs:** 각 agent의 전체 대화 로그 (기존과 동일 형식)

### 7. Usage

```bash
# Simple scaffold, 5 students, 3 naives, haiku model
pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k simple \
  --student-n 5 --naive-m 3 --agent-model haiku

# All scaffolds with defaults (N=3, M=3)
pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s --agent-model haiku

# Single scaffold (complex only)
pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k complex \
  --student-n 2 --naive-m 2 --agent-model sonnet

# Existing tests still work unchanged
pytest tests/scenarios/test_live_agents_AB.py -m e2e_live -s
```
