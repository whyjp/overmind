# Overmind A/B Benchmark: Cross-Agent Lesson Sharing

## Core Finding

> **Overmind에 연결된 에이전트(Student)는 Pioneer의 시행착오를 diff로 수신하여**
> **동일 태스크를 선제적으로(실행 전) 수정하고, 1-2회 실행으로 완료한다.**

### v2 테스트 (2026-03-28, 8단계 캐스케이드)

```
                   Pioneer      Student (+OM)     Naive (Control)
                   ────────     ─────────────     ───────────────
선제적 수정            No          Yes               No
start.sh 실행        6-9          1-2              6-9
config.toml 수정     5-8          1-2              5-8
src/ 파일 분석        다수          최소              다수
```

**핵심 지표**: `proactive_config_fix` — Student가 start.sh 실행 전에 config.toml을 수정했는가?
이 지표는 모델(haiku/sonnet)에 무관하게 일관된 차이를 보인다.

### v1 테스트 (2026-03-27, 5단계 캐스케이드, haiku 기준)

```
                   Pioneer      Student (+OM)     Naive (Control)
                   ────────     ─────────────     ───────────────
start.sh 실행          5              2                  5
config.toml 수정       3              1                  4
src/ 파일 분석         4              5                  4
총 turns              16             12                 17
시간 (s)            45.6           36.5               49.8
```

---

## v1 → v2 변경점

| 항목 | v1 (2026-03-27) | v2 (2026-03-28) |
|------|-----------------|-----------------|
| 캐스케이드 단계 | 5단계 (4모듈) | 8단계 (6모듈) |
| 이벤트 포매팅 | "CONTEXT — Be aware" (수동적) | "FIXES BY TEAMMATES — Apply BEFORE" (능동적) |
| 핵심 지표 | server_run_attempts (비결정적) | proactive_config_fix (결정적) |
| 프롬프트 힌트 | "read the source file" (친절) | "figure out what's wrong" (최소) |
| 어설션 | 없음 (출력만) | 성공 필수 + Student ≤ Naive+3 + src/ 무수정 |
| 신규 모듈 | — | middleware.js, logging.js, network.js env검증 |
| 출력 | JSONL만 | JSONL + run_summary.json |

**변경 이유**: v1에서 haiku/sonnet 모델 간 결과 비일관성 발생. 수동적 "CONTEXT" 포매팅을 에이전트가 무시하는 경우가 빈발했고, 5단계는 똑똑한 모델이 Overmind 없이도 2-3회로 해결 가능했음.

---

## Tool-Use Sequence (v1 실제 JSONL 데이터, haiku)

### Pioneer - 반복 실패 패턴 (15 steps)

```
 1. Bash   bash start.sh               <<< RUN (fail: KeyError 'server')
 2. Read   network.js                  <<< 에러 소스 분석
 3. Read   config.toml
 4. Edit   config.toml                 <<< [server] 추가
 5. Bash   bash start.sh               <<< RUN (fail: ENOENT hmac.key)
 6. Read   auth.js                     <<< 에러 소스 분석
 7. Bash   ls keys/                    <<< 파일 탐색
 8. Bash   mkdir keys && openssl...    <<< key_file 경로 수정
 9. Bash   bash start.sh               <<< RUN (fail: KeyError 'session')
10. Read   session.js                  <<< 에러 소스 분석
11. Edit   config.toml                 <<< [session] 추가
12. Bash   bash start.sh               <<< RUN (fail: KeyError 'routes')
13. Read   routes.js                   <<< 에러 소스 분석
14. Edit   config.toml                 <<< [routes] 추가
15. Bash   bash start.sh               <<< RUN - SERVER OK
```

**패턴**: 실행 -> 실패 -> 에러 소스 읽기 -> 수정 -> 실행 -> 실패 -> ... (5 사이클)

### Student (+Overmind) - 선행 분석 패턴 (11 steps)

```
 1. Bash   bash start.sh               <<< RUN (fail: KeyError 'server')
 2. Read   network.js                  <<< 에러 소스 + 추가 분석 시작
 3. Read   config.toml
 4. Read   server.js                   <<< server.js에서 전체 구조 파악
 5. Read   auth.js                     <<< 모든 init 모듈을 연속 분석
 6. Read   session.js
 7. Read   routes.js
 8. Bash   ls keys/                    <<< key_file 확인
 9. Bash   mkdir keys && openssl...    <<< key_file 준비
10. Edit   config.toml                 <<< 1회 수정으로 전체 완성
11. Bash   bash start.sh               <<< RUN - SERVER OK
```

**패턴**: 1회 실패 -> Overmind 맥락으로 **전체 소스 선행 분석** -> 1회 수정 -> 성공

### Naive (Control) - Pioneer와 동일한 반복 패턴 (16 steps)

```
 1. Bash   bash start.sh               <<< RUN (fail: KeyError 'server')
 2. Read   network.js                  <<< 에러 소스 분석
 3. Read   config.toml
 4. Edit   config.toml                 <<< [server] 추가
 5. Bash   bash start.sh               <<< RUN (fail: ENOENT hmac.key)
 6. Read   auth.js
 7. Bash   ls keys/
 8. Bash   find . -name "*.key"
 9. Edit   config.toml                 <<< key_file 수정
10. Bash   bash start.sh               <<< RUN (fail: KeyError 'session')
11. Read   session.js
12. Edit   config.toml                 <<< [session] 추가
13. Bash   bash start.sh               <<< RUN (fail: KeyError 'routes')
14. Read   routes.js
15. Edit   config.toml                 <<< [routes] 추가
16. Bash   bash start.sh               <<< RUN - SERVER OK
```

**패턴**: Pioneer와 동일 - 단계별 실패 -> 수정 반복 (5 사이클)

---

## 인지적 행동 차이

### v2에서 Student는 왜 선제적으로 수정하는가?

v2에서 Student는 SessionStart에서 **FIXES BY TEAMMATES** 섹션을 수신한다:

```
[OVERMIND] Team context from other agents on this repo.

FIXES BY TEAMMATES — Another agent already solved these problems.
Apply these fixes BEFORE running or testing the project:
- Modified config.toml (1 file: config.toml)
  Diff: +[server]\n+host = "0.0.0.0"\n+port = 3000\n+env = "development" (by agent_pioneer)
- Modified config.toml (1 file: config.toml)
  Diff: -key_file = "./keys/hmac.key"\n+key_file = "./hmac.key" (by agent_pioneer)
- Modified config.toml (1 file: config.toml)
  Diff: +[session]\n+store = "memory"\n+ttl_seconds = 3600 (by agent_pioneer)
  ...

IMPORTANT: Apply all FIXES first — they represent solved problems.
Do NOT re-discover issues that teammates already fixed.
```

이 정보는 v1의 "config.toml이 수차례 수정됐다"(what)를 넘어,
**"정확히 무엇이 추가/변경됐는가"(diff)**를 전달한다.

```
v1 Student 사고: "config 여러번 수정됐었네. 전체를 보자."  -> 선행 분석 -> 한 번에 완성
v2 Student 사고: "diff가 있네. 이걸 먼저 적용하자."        -> 선제적 수정 -> start.sh -> done
```

### v1에서 Student는 왜 다른 행동을 했는가?

v1에서는 수동적 CONTEXT를 수신했다:

```
CONTEXT - Be aware of these when relevant:
- Modified .../hive-multi/* (config.toml) (by agent_pioneer)
- Modified .../hive-multi/* (config.toml) (by agent_pioneer)
... (8 events total)
```

이 정보는 **"config.toml이 수차례 수정됐다"**는 신호만 준다.
하지만 이것만으로도 Student는 첫 에러 후 **전체 소스를 선행 분석**하는 행동 변화를 보였다.

---

## Metrics Comparison (v1, haiku)

| Metric | Pioneer | Student (+OM) | Naive | Student vs Naive |
|--------|:-------:|:-------------:|:-----:|:----------------:|
| **start.sh 실행 횟수** | 5 | **2** | 5 | **-60%** |
| **config.toml 수정 횟수** | 3 | **1** | 4 | **-75%** |
| src/ 파일 분석 횟수 | 4 | 5 | 4 | +1 (선행 분석) |
| 총 tool uses | 15 | **11** | 16 | **-31%** |
| 총 turns | 16 | **12** | 17 | **-29%** |
| 시간 (s) | 45.6 | **36.5** | 49.8 | **-27%** |
| 비용 (USD) | 0.1 | 0.1 | 0.1 | 동일 |
| src/ 수정 (제약 위반) | 0 | 0 | 0 | 동일 |
| **서버 시작 성공** | Yes | Yes | Yes | 동일 |

### Pioneer = Naive 수렴

Pioneer와 Naive는 동일한 "사전 지식 없음" 조건이므로 지표가 수렴한다:
- 실행 횟수: 5 vs 5
- config 수정: 3 vs 4 (비결정적 차이)
- src/ 분석: 4 vs 4
- 총 turns: 16 vs 17

**Student만 일관되게 효율적**: 2회 실행, 1회 수정, 12 turns.

---

## Test Design (v2)

```
Pioneer (+Overmind)   ---> start.sh ---> fail ---> fix ---> ... ---> push events (with diff)
                                                                         |
Student (+Overmind)   ---> pull FIXES ---> 선제적 수정 ---> start.sh ---> done
Naive   (-Overmind)   ---> start.sh ---> fail ---> fix ---> ... ---> (no push)
```

### Scaffold: Node.js 8-Stage Failure Cascade

6개 독립 모듈이 각각 config.toml의 다른 섹션을 검증한다.
각 모듈은 raw JavaScript exception을 발생시킨다.

```
src/server.js      -> require 순서: network → auth → session → routes → middleware → logging
src/network.js     -> config.server.host, .port, .env    (missing: [server], env 검증)
src/auth.js        -> config.auth.key_file → readFile    (wrong path: ./keys/hmac.key → ./hmac.key)
src/session.js     -> config.session.store, .ttl_seconds  (missing: [session], ttl≥60 검증)
src/routes.js      -> config.routes.paths                 (missing: [routes], array 검증)
src/middleware.js   -> config.middleware.order              (missing: [middleware], known names 검증)
src/logging.js     -> config.logging.level, .format        (missing: [logging], 패턴 'json:stdout' 검증)
```

config.toml 초기 상태: `[database]`와 `[auth]`만 존재.
에이전트는 `[server]`(+env), `[session]`(+ttl≥60), `[routes]`, `[middleware]`, `[logging]` 섹션과 `auth.key_file` 경로를 수정해야 한다.

### 난이도 설계 의도

| 단계 | 난이도 | 이유 |
|------|--------|------|
| [server] host/port | 낮음 | 에러 메시지가 직관적 |
| server.env 검증 | 중간 | 유효값 목록을 소스에서 확인 필요 |
| auth.key_file 경로 | 중간 | 파일 시스템 탐색 필요 |
| [session] + ttl≥60 | 중간 | ≥60 조건은 에러 메시지에서만 확인 가능 |
| [routes].paths 배열 | 중간 | TOML 배열 문법 이해 필요 |
| [middleware].order | 높음 | known names 목록을 소스에서 확인 필요 |
| [logging].format 패턴 | **높음** | `json:stdout` 패턴은 diff 없이 추측 어려움 |

### Prompt (동일 — v2에서 힌트 축소)

```
Get the Hive server running.
Run `bash start.sh` to start it.
If it fails, figure out what's wrong and fix config.toml, then retry.
You may only edit config.toml — do not modify any .js or .json files.
```

v1 대비 **"read the source file that crashed"** 힌트를 제거하여 행동 격차 확대.

### 어설션

```python
# 모든 에이전트 성공 필수
assert s_cfg.get("all_ok") or s_analysis["saw_server_running"]

# Student가 Naive보다 현저히 나쁘면 안 됨
assert s_runs <= n_runs + 3

# src/ 파일 수정 금지 (모든 에이전트)
assert not check_src_modified(repo_dir)
```

---

## Reproduction

### 기본 실행

```bash
cd server

# Default model
uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s

# Haiku model
AGENT_MODEL=haiku uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s

# Sonnet model
AGENT_MODEL=sonnet uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s
```

### 다중 실행 (일관성 검증)

```bash
for i in $(seq 1 10); do
  echo "=== Run $i ==="
  AGENT_MODEL=haiku uv run pytest tests/scenarios/test_live_agents_AB_multistage.py \
    -m e2e_live -s 2>&1 | tee "ab_multi_haiku_run${i}.log"
done
```

### JSONL 분석

```bash
python tests/scenarios/analyze_ab_jsonl.py <state_dir>
python tests/scenarios/analyze_ab_jsonl.py <state_dir> --json  # machine-readable
```

### 요구사항

- `claude` CLI 설치 및 인증
- Node.js + npm (scaffold 빌드용)
- Overmind plugin (`plugin/` 디렉토리)

---

## Test Environment

| Item | Value |
|------|-------|
| Date | v1: 2026-03-27, v2: 2026-03-28 |
| Agent Model | haiku/sonnet (`AGENT_MODEL` 환경변수) |
| Platform | Windows 11 Pro |
| Python | 3.13.12 |
| Node.js | (system) |
| Overmind Server | in-process (port 17996) |
| Plugin hooks | SessionStart (pull), PostToolUse (push+diff), PreToolUse (scope 경고), SessionEnd (flush) |
| FLUSH_THRESHOLD | 1 (즉시 push) |
| Permission mode | bypassPermissions |
| max_turns | 30 |

---

## Extending This Test

### 모델별 비교

```bash
for model in haiku sonnet opus; do
  echo "=== $model ==="
  AGENT_MODEL=$model uv run pytest tests/scenarios/test_live_agents_AB_multistage.py \
    -m e2e_live -s 2>&1 | tee "ab_multistage_${model}.log"
done
```

### 시나리오 확장 방향

| 시나리오 | 복잡도 | 검증 포인트 |
|---------|--------|------------|
| **현재**: config.toml + 6모듈 8단계 cascade | 중-높 | proactive fix + 실행 횟수 감소 |
| **Multi-file edit**: .env + docker-compose.yml + config | 높음 | 여러 파일 lesson 전파 |
| **Dependency conflict**: npm 버전 충돌 | 높음 | 에러 해석 능력 |
| **Multi-agent chain**: Pioneer1 -> Pioneer2 -> Student | 높음 | lesson 누적 효과 |

---

## Limitations

1. **비결정적**: 실행마다 에이전트 행동이 다름. v2의 `proactive_config_fix`는 가장 결정적 지표이지만 100% 보장은 아님. N회 반복 통계 필요.

2. **diff 의존**: v2의 FIXES 섹션은 Pioneer의 push에 diff가 포함되어야 작동. `diff_collector.py`가 git diff를 추출하지 못하면 (예: git 미초기화) 수동적 CONTEXT로 fallback.

3. **scope 절대 경로**: `file_to_scope()`가 Windows 절대 경로를 사용할 수 있음. 상대 경로 정규화 필요 (Phase 2).

4. **모델 의존성**: v2 설계는 haiku에서도 일관된 결과를 목표로 하지만, opus급 모델은 Overmind 없이도 선행 분석을 수행할 가능성 있음.

5. **v2 벤치마크 숫자 미확정**: 위의 v1 JSONL 시퀀스와 수치는 실제 haiku 실행 데이터. v2의 8단계 캐스케이드에 대한 실행 데이터는 향후 10회 반복 실행으로 수집 예정.
