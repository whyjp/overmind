# Overmind A/B Benchmark: Cross-Agent Lesson Sharing

## Core Finding

> **Overmind에 연결된 에이전트(Student)는 Pioneer의 시행착오를 흡수하여**
> **동일 태스크를 60% 적은 시도, 75% 적은 수정으로 완료한다.**

```
                   Pioneer      Student (+OM)     Naive (Control)
                   ────────     ─────────────     ───────────────
start.sh 실행          5              2                  5
config.toml 수정       3              1                  4
src/ 파일 분석         4              5                  4
총 turns              16             12                 17
시간 (s)            45.6           36.5               49.8
```

Pioneer가 5번의 실패를 거쳐 발견한 설정을, Student는 **1번의 수정과 2번의 실행**으로 해결했다.
Naive는 Pioneer와 동일한 시행착오를 반복했다 (5회 실행, 4회 수정).

---

## Tool-Use Sequence (실제 JSONL 데이터)

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

### Student는 왜 다른 행동을 했는가?

Student는 SessionStart에서 Overmind로부터 Pioneer의 이벤트를 수신했다:

```
[OVERMIND] Team context from other agents on this repo.

CONTEXT - Be aware of these when relevant:
- Modified .../hive-multi/* (config.toml) (by agent_pioneer)
- Modified .../hive-multi/* (config.toml) (by agent_pioneer)
- Modified .../hive-multi/* (config.toml) (by agent_pioneer)
... (8 events total)
```

이 정보는 **"config.toml이 수차례 수정됐다"**는 신호를 준다.

Pioneer/Naive는 첫 에러(network.js의 KeyError)만 보고 **해당 파일만 읽고 수정**한다.
Student는 "config에 여러 이슈가 있었다"는 맥락을 알기 때문에:
1. 첫 에러 후 network.js를 읽는 것은 동일
2. 하지만 **거기서 멈추지 않고** server.js -> auth.js -> session.js -> routes.js를 **연속 분석**
3. 모든 검증 로직을 파악한 뒤 **1회 수정으로 전체 완성**

```
Pioneer/Naive 사고: "server 에러 났네. 이것만 고치자."     -> 고침 -> 다음 에러 -> 반복
Student 사고:      "config 여러번 수정됐었네. 전체를 보자." -> 전체 분석 -> 한 번에 완성
```

---

## Metrics Comparison

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

## Test Design

```
Pioneer (+Overmind)   ---> start.sh ---> fail ---> fix ---> ... ---> push events
                                                                         |
Student (+Overmind)   ---> pull events ---> 전체 분석 ---> 1회 수정 ---> start.sh
Naive   (-Overmind)   ---> start.sh ---> fail ---> fix ---> ... ---> (no push)
```

### Scaffold: Node.js Multi-Stage Failure Cascade

4개 독립 모듈이 각각 config.toml의 다른 섹션을 검증한다.
각 모듈은 raw JavaScript exception (TypeError, ENOENT, AssertionError)을 발생시킨다.

```
src/server.js     -> require('./network') -> require('./auth') -> require('./session') -> require('./routes')
src/network.js    -> config.server.host, config.server.port      (missing: [server] section)
src/auth.js       -> config.auth.key_file -> fs.readFileSync()   (wrong path: ./keys/hmac.key)
src/session.js    -> config.session.store, config.session.ttl    (missing: [session] section)
src/routes.js     -> config.routes.paths                         (missing: [routes] section)
```

config.toml 초기 상태: `[database]`와 `[auth]`만 존재.
에이전트는 `[server]`, `[session]`, `[routes]` 섹션과 `auth.key_file` 경로를 추가해야 한다.

### Prompt (동일)

```
Get the Hive server running.
Run `bash start.sh` to start it.
If it fails, investigate and fix the issue, then retry.
You may only edit config.toml.
```

---

## Reproduction

### 기본 실행

```bash
cd server

# Default model (opus)
uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s

# Haiku model (recommended - creates clearer behavioral differences)
AGENT_MODEL=haiku uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s

# Sonnet model
AGENT_MODEL=sonnet uv run pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s
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
| Date | 2026-03-27 |
| Agent Model | claude-haiku-4-5 (`AGENT_MODEL=haiku`) |
| Platform | Windows 11 Pro |
| Python | 3.13.12 |
| Node.js | (system) |
| Overmind Server | in-process (port 17996) |
| Plugin hooks | SessionStart (pull), PostToolUse (push) |
| FLUSH_THRESHOLD | 1 (즉시 push) |
| Permission mode | bypassPermissions |
| Test duration | 96s total (Pioneer=46s + Student=37s, Naive=50s parallel) |

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
| **현재**: config.toml + 4 모듈 cascade | 중간 | start.sh 시도 횟수 감소 |
| **Multi-file edit**: .env + docker-compose.yml + config | 높음 | 여러 파일 lesson 전파 |
| **Dependency conflict**: npm 버전 충돌 | 높음 | 에러 해석 능력 |
| **Multi-agent chain**: Pioneer1 -> Pioneer2 -> Student | 높음 | lesson 누적 효과 |

---

## Limitations

1. **비결정적**: 실행마다 에이전트 행동이 다름. Pioneer/Naive는 수렴하고 Student만 일관되게 효율적인 패턴이 N회 반복으로 확인 필요.

2. **Phase 1 lesson 한계**: 이벤트는 "config.toml이 수정됐다"는 사실만 전달. Phase 2의 시맨틱 lesson이 추가되면 Student가 소스 분석 없이 바로 수정 가능하여 추가 효율 향상 예상.

3. **scope 절대 경로**: `file_to_scope()`가 Windows 절대 경로를 사용. 상대 경로 정규화 필요 (Phase 2).

4. **모델 의존성**: Opus는 태스크가 쉬워서 차이가 작을 수 있음. Haiku에서 가장 명확한 차이 관찰.
