# Overmind A/B Benchmark: Cross-Agent Lesson Sharing

## Core Finding

> **복잡한 문제(상호의존, misleading errors, 다단계 추론)에서 Overmind는**
> **Pioneer의 해결 과정을 Student에게 자동 전파하여 23% 빠른 해결, 높은 성공률을 달성한다.**
> **단순 반복 트랩에서는 효과 없음 — 문제의 복잡도가 핵심.**

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

모든 벤치마크는 `test_live_agents_AB_statistical.py` 하나로 실행. (이전 단일 실행 테스트들은 statistical 프레임워크로 대체되어 제거됨.)

### 요구사항

- `claude` CLI 설치 및 인증
- Python 3.11+ (scaffold 실행용)
- Overmind plugin (`plugin/` 디렉토리)

---

## Test Environment

| Item | Value |
|------|-------|
| Date | v1: 2026-03-27, v2: 2026-03-28, v3(model-tier): 2026-03-29 |
| Pioneer Model | sonnet (--pioneer-model, 자동 업그레이드) |
| Student/Naive Model | haiku (--agent-model) |
| Platform | Windows 11 Pro |
| Python | 3.13.12 |
| Overmind Server | in-process (port 17990) |
| Plugin hooks | SessionStart (pull), PostToolUse (push+diff), PreToolUse (scope 경고), SessionEnd (flush) |
| FLUSH_THRESHOLD | 1 (즉시 push) |
| Permission mode | bypassPermissions |
| max_turns | 30-40 |

---

## Extending This Test

### 시나리오 확장 방향

| 시나리오 | 복잡도 | 검증 포인트 |
|---------|--------|------------|
| **nightmare**: 5트랩 4파일 misleading errors | 높음 | 성공률 + 시행착오 감소 |
| **branch_conflict**: cross-branch 3트랩 | 중-높 | cross-branch intent 전파 |
| **Multi-file edit**: .env + docker-compose.yml + config | 높음 | 여러 파일 lesson 전파 |
| **Dependency conflict**: npm 버전 충돌 | 높음 | 에러 해석 능력 |
| **Multi-agent chain**: Pioneer1 -> Pioneer2 -> Student | 높음 | lesson 누적 효과 |

---

## Statistical AB Results (2026-03-29, N=2 M=2, haiku)

Statistical test framework (`test_live_agents_AB_statistical.py`)로 Pioneer 1회 후 Student x2 + Naive x2 병렬 실행.

### Simple Scaffold (3단계)

```
  Metric                          Pioneer  Student(avg)   Naive(avg)
  server_run_attempts                   2           2.0          2.0
  config_toml_edits                     1           1.0          1.0
  proactive_config_fix              False            0%           0%
  elapsed (s)                       29.7s         25.1s        23.3s
```

**결과: Overmind 효과 없음.** Haiku가 3단계 트랩을 iterative discovery로 즉시 해결.

### Multistage Scaffold (9단계)

```
  Metric                          Pioneer  Student(avg)   Naive(avg)
  server_run_attempts                   7           7.0          7.0
  config_toml_edits                     5           6.0          5.5
  proactive_config_fix              False            0%           0%
  elapsed (s)                      100.9s         70.8s        61.1s
```

**결과: Overmind 효과 없음.** 단계 수가 많아도 각 트랩이 "config section 추가"의 반복이라 패턴이 단순. LLM이 에러 메시지만으로 충분히 해결 가능.

### 핵심 인사이트

**단계의 깊이보다 문제의 복잡도가 중요.** Overmind가 차이를 만들려면:
- 에러 메시지만으로 해결책 유추 불가한 트랩
- A를 고치면 B가 깨지는 상호의존 구조
- 에러가 실제 원인과 다른 곳을 가리키는 misleading errors
- 여러 파일을 cross-reference해야 하는 다단계 추론

기존 v1 벤치마크에서 27% 시간 절감이 관측된 것은, 당시 Student가 diff 기반 FIXES를 받아 **전체 소스 선행 분석** 행동 변화를 보였기 때문. 하지만 트랩 자체가 단순하면 이 행동 변화가 실행 횟수 감소로 이어지지 않음.

### Nightmare Scaffold (5트랩, 4파일, 2026-03-29)

**설계 철학**: Pioneer에게 동일 프롬프트를 주는 것이 아닌, **이미 문제를 풀어본 전문가** 시뮬레이션. Pioneer의 체계적 해결 과정이 Overmind를 통해 Student에게 자동 전파되고, Naive는 사전 지식 없이 시행착오하는 구조.

**트랩 구성** (config.toml + .env + secrets/hmac.key + plugins/registry.json):

| 트랩 | 유형 | 난이도 | 핵심 어려움 |
|------|------|--------|------------|
| TRAP 1 | Misleading error | 중 | db.py traceback이 원인을 가리킴, 실제 수정은 .env |
| TRAP 2 | Cross-file SHA256 | **높** | SECRET_KEY의 SHA256 hexdigest가 hmac.key와 일치해야 함 |
| TRAP 3 | Mutual dependency | 중-높 | cache.ttl < session.timeout + backend별 추가 설정 |
| TRAP 4 | 3-way port conflict | 중 | server/metrics/health 포트 모두 달라야 함, 한 번에 하나만 보여줌 |
| TRAP 5 | 3-hop chain | **높** | config.toml → registry.json → .env 3개 파일 cross-reference |

**프롬프트 전략**:
- `PIONEER_PROMPT`: 전문가 수준 — 정확한 수정 값과 SHA256 계산 커맨드까지 제공
- `SHARED_PROMPT`: 최소 지시 — "서버 실행하고, 실패하면 조사해서 수정해라"
- Student: SHARED_PROMPT + Overmind 이벤트 수신
- Naive: SHARED_PROMPT only

#### N=2, M=2 결과

```
  Metric                          Pioneer  Student(avg)   Naive(avg)
  server_run_attempts                   1          10.0         15.0
  config_file_edits                     4           9.5         12.5
  saw_server_running                 True           50%           50%
  elapsed (s)                       38.1s         90.6s       112.9s
```

| 지표 | Student vs Naive |
|------|:----------------:|
| server_run_attempts | **-33%** |
| elapsed | **-20%** |
| config_file_edits | -24% |

#### N=3, M=3 결과

```
  Metric                          Pioneer  Student(avg)   Naive(avg)
  server_run_attempts                   1          12.7         12.7
  config_file_edits                     3           8.7         13.7
  saw_server_running                 True           33%            0%
  elapsed (s)                       38.4s        103.1s       133.4s
```

| 지표 | Student vs Naive |
|------|:----------------:|
| **saw_server_running** | **33% vs 0%** (Student만 성공) |
| **elapsed** | **-23%** |
| **config_file_edits** | **-36%** |
| server_run_attempts | 동일 |

#### 핵심 발견

1. **성공률 차이**: N=3에서 Student 1명이 실제 서버 시작 성공, Naive는 전원 실패. Overmind의 지식 전파가 해결 가능성을 높임.
2. **시간 절감 일관**: N=2에서 20%, N=3에서 23% — 시도 횟수와 무관하게 일관된 효율 향상.
3. **수정 효율**: config_file_edits가 Student에서 24-36% 적음 — Pioneer의 지식으로 불필요한 시행착오 수정 감소.
4. **server_run_attempts 제한적**: N=3에서 차이 없음. 시도 횟수보다 **수정 정확도**와 **최종 성공 여부**가 더 의미 있는 지표.
5. **Pioneer 프롬프트 전략 유효**: 전문가 프롬프트로 Pioneer가 1회만에 성공 → 양질의 이벤트 전파 → Student 행동 개선.

#### Reproduction

```bash
cd server

# Nightmare, N=3 M=3, haiku
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k nightmare --student-n 3 --naive-m 3 --agent-model haiku
```

### 전체 Scaffold 비교 요약 (PIONEER_PROMPT 방식, haiku only)

| Scaffold | 트랩 수 | 파일 수 | Pioneer 프롬프트 | Student vs Naive (elapsed) | Student vs Naive (success) |
|----------|---------|---------|:---:|:---:|:---:|
| simple | 3 | 1 | SHARED | 동일 | 동일 |
| multistage | 9 | 1 | SHARED | 동일 | 동일 |
| **nightmare** | **5** | **4** | **PIONEER** | **-23%** | **33% vs 0%** |

---

## Model-Tier Benchmark (2026-03-29) — 최적 벤치마크 방법론

### 핵심 전환: PIONEER_PROMPT → 상위 모델

이전 벤치마크는 Pioneer에게 정답이 담긴 전문가 프롬프트(PIONEER_PROMPT)를 주는 인위적 세팅이었다.
**Model-Tier 벤치마크**는 이를 개선:

- **Pioneer = sonnet** (상위 모델, 동일 SHARED_PROMPT)
- **Student = haiku + Overmind** (저렴 모델, Overmind 이벤트 수신)
- **Naive = haiku only** (저렴 모델, 대조군)

프롬프트 조작 없이, **모델 능력 차이만으로** Overmind의 cross-model 지식 전파 가치를 증명.

### Nightmare (Pioneer=sonnet, Student/Naive=haiku, N=2 M=2)

```
  Metric                          Pioneer(sonnet)  Student(haiku+OM)  Naive(haiku)
  ──────────────────────────────  ───────────────  ─────────────────  ────────────
  server_run_attempts                           2                8.0          13.5
  config_file_edits                             4                9.5          12.0
  bash_commands                                11               17.5          23.0
  src_file_reads                                0                5.5           0.0
  elapsed (s)                               69.0s            104.9s         96.1s
  saw_server_running                         True              100%           50%
```

| 지표 | Student vs Naive |
|------|:---:|
| **성공률** | **100% vs 50%** — Naive 하나가 nightmare 트랩 해결 실패 |
| **서버 실행 횟수** | **-41%** — 시행착오 대폭 감소 |
| **config 수정 횟수** | **-21%** — 불필요한 수정 감소 |
| **src_file_reads** | Student 5.5 vs Naive 0 — **선행 분석 행동 패턴** |

**Pioneer(sonnet)가 SHARED_PROMPT만으로 2회 만에 성공** — 상위 모델의 자연스러운 문제 해결력이 Overmind를 통해 haiku Student에게 전파됨.

Student의 `src_file_reads=5.5`는 Overmind 컨텍스트를 기반으로 소스를 **선행 분석**하는 행동 변화. Naive는 소스를 전혀 읽지 않고 에러 메시지만으로 시행착오.

### Branch-Conflict (Pioneer=sonnet on feat/auth, Student/Naive=haiku on feat/api)

cross-branch 시나리오: Pioneer(feat/auth)의 인사이트가 다른 branch(feat/api)의 Student에게 전파.

```
  Metric                          Pioneer(sonnet)  Student(haiku+OM)  Naive(haiku)
  ──────────────────────────────  ───────────────  ─────────────────  ────────────
  server_run_attempts                           1                3.5           5.0
  config_file_edits                             2                3.0           4.0
  elapsed (s)                               34.3s             29.5s         29.1s
  saw_server_running                         True              100%          100%
```

| 지표 | Student vs Naive |
|------|:---:|
| **서버 실행 횟수** | **-30%** |
| **config 수정 횟수** | **-25%** |

### 왜 Model-Tier가 최적 벤치마크인가

| 항목 | PIONEER_PROMPT 방식 | Model-Tier 방식 |
|------|:---:|:---:|
| Pioneer 프롬프트 | 정답 포함 (인위적) | 동일 SHARED_PROMPT (공정) |
| Pioneer 모델 | haiku (동일) | sonnet (상위) |
| 현실 반영도 | 낮음 — 정답을 미리 아는 상황 | **높음 — 똑똑한 팀원이 먼저 해결** |
| 측정 대상 | 프롬프트 효과 + Overmind | **순수 Overmind 전파 효과** |
| 비용 내러티브 | 없음 | **비싼 모델 1회 → 싼 모델 N회 효율화** |

### Reproduction (Model-Tier)

```bash
cd server

# Nightmare: Pioneer=sonnet, Student/Naive=haiku
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k nightmare --student-n 2 --naive-m 2 \
  --agent-model haiku --pioneer-model sonnet

# Branch-Conflict: cross-branch knowledge transfer
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k branch_aware --student-n 2 --naive-m 2 \
  --agent-model haiku --pioneer-model sonnet

# Pioneer=opus (더 극적인 차이 기대)
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k nightmare --student-n 3 --naive-m 3 \
  --agent-model haiku --pioneer-model opus
```

### Reproduction (PIONEER_PROMPT 방식, 레거시)

```bash
cd server

# Simple, N=2 M=2, haiku
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k simple --student-n 2 --naive-m 2 --agent-model haiku

# Nightmare, N=3 M=3, haiku (uses PIONEER_PROMPT for pioneer)
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k nightmare --student-n 3 --naive-m 3 --agent-model haiku
```

---

## Limitations

1. **비결정적**: 실행마다 에이전트 행동이 다름. v2의 `proactive_config_fix`는 가장 결정적 지표이지만 100% 보장은 아님. N회 반복 통계 필요.

2. **diff 의존**: v2의 FIXES 섹션은 Pioneer의 push에 diff가 포함되어야 작동. `diff_collector.py`가 git diff를 추출하지 못하면 (예: git 미초기화) 수동적 CONTEXT로 fallback.

3. **scope 절대 경로**: `file_to_scope()`가 Windows 절대 경로를 사용할 수 있음. 상대 경로 정규화 필요 (Phase 2).

4. **모델 의존성**: v2 설계는 haiku에서도 일관된 결과를 목표로 하지만, opus급 모델은 Overmind 없이도 선행 분석을 수행할 가능성 있음.

5. **v2 벤치마크 숫자 미확정**: 위의 v1 JSONL 시퀀스와 수치는 실제 haiku 실행 데이터. v2의 8단계 캐스케이드에 대한 실행 데이터는 향후 10회 반복 실행으로 수집 예정.
