# Branch-Aware E2E: branch-conflict Scaffold Design

**Date**: 2026-03-29
**Status**: Approved
**Goal**: 서로 다른 feature branch에서 작업하는 에이전트가 Overmind의 cross-branch intent/discovery 공유로 충돌을 회피하는지 E2E 검증.

---

## 1. 배경

Phase 3에서 구현된 branch-aware 3-tier relevance:

| Tier | 조건 | 통과 타입 |
|------|------|----------|
| Same branch | `evt.branch == pull.branch` | 모든 타입 |
| Same base | `evt.base == pull.base` | intent, discovery, correction, broadcast + file-bearing |
| Different | 나머지 | broadcast, high_priority only |

단위 테스트 8개 통과. 하지만 실제 에이전트 간 cross-branch 시나리오 E2E 검증 없음.

## 2. 시나리오: Shared Config Conflict

Hive 서버에 두 모듈(auth, api)을 각각 다른 feature branch에서 추가. 두 모듈이 공유 리소스(port, .env 변수, session config)를 놓고 충돌.

### 2.1 파일 구조

```
base (main):
  config.toml     — [database] + [logging] 만 존재
  .env            — DATABASE_URL=postgresql://localhost:5432/hive
                    LOG_LEVEL=info
  start.sh        — python src/server.py
  src/server.py   — config 로드 → validate_auth → validate_api → start
  src/config_loader.py — config.toml + .env 병합
  src/auth.py     — [auth] 검증: port, secret_key, session_timeout
  src/api.py      — [api] 검증: port, api_key, session_timeout
  src/ports.py    — 전체 port 충돌 검사
  CLAUDE.md       — 규칙: config.toml, .env만 수정 가능
```

### 2.2 Branch 구성

- `main`: 기본 scaffold (auth/api 모두 실패하는 상태)
- `feat/auth`: main에서 분기. 에이전트 과제 = auth 모듈 동작
- `feat/api`: main에서 분기. 에이전트 과제 = api 모듈 동작

같은 파일 구조이지만 서로 다른 branch. `create_scaffold()`에 branch 이름 파라미터.

### 2.3 트랩 설계

#### TRAP 1: Port Conflict
- auth.py: `[auth].port` 필수, 정수, 1024-65535 범위
- api.py: `[api].port` 필수, 정수, 1024-65535 범위
- ports.py: 모든 section의 port 수집 → 중복 시 `AddressError`
- **함정**: auth.py 에러 메시지가 "port 8080 is recommended for auth services" 힌트 포함. api.py도 동일 힌트. 둘 다 8080을 선택하면 충돌.
- **cross-branch 가치**: Agent A가 8080 선점 → intent push → Agent B가 받아서 다른 port 선택

#### TRAP 2: .env 변수 형식 충돌
- auth.py: `.env`의 `SERVICE_TOKEN` 필요, HS256 JWT 형식 검증 (`^[A-Za-z0-9_-]{32,}$`)
- api.py: `.env`의 `SERVICE_TOKEN` 필요, UUID 형식 검증 (`^[0-9a-f]{8}-...`)
- **함정**: 동시에 만족 불가. 해결책: `AUTH_TOKEN` / `API_TOKEN`으로 분리
- **cross-branch 가치**: Agent A가 SERVICE_TOKEN 형식 문제 발견 → discovery push → Agent B가 별도 변수명 사용

#### TRAP 3: Session Timeout 상호 배제
- auth.py: `[auth].session_timeout` 필수, >= 3600 (보안상 긴 세션)
- api.py: `[api].session_timeout` 필수, <= 1800 (API는 짧은 세션)
- 처음엔 둘 다 `[session].timeout`을 읽으려 하지만, 공유 section으로는 양쪽 조건 동시 충족 불가
- **함정**: 에러가 "session.timeout must be >= 3600" (auth) vs "session.timeout must be <= 1800" (api)로 모순
- **cross-branch 가치**: Agent A가 auth.session_timeout으로 분리 → discovery push → Agent B가 api.session_timeout 패턴 따름

## 3. 에이전트 토폴로지

```
Phase 1: Agent A (feat/auth) — Pioneer
  branch: feat/auth, base: main
  prompt: PIONEER_PROMPT (expert — 정확한 해결법 제공)
  Overmind: ON → push intent/discovery with branch metadata

Phase 2 (병렬):
  Student B (feat/api) — Overmind ON
    branch: feat/api, base: main
    → same-base tier → Agent A의 intent/discovery 수신
    → port 충돌 회피, 변수명 분리, session 분리

  Naive B (feat/api) — Overmind OFF
    branch: feat/api, base: main
    → 아무 정보 없음
    → port 충돌, 변수 형식 오류, session 모순 반복
```

## 4. Prompt 설계

### PIONEER_PROMPT (feat/auth용)
```
feat/auth branch의 auth 모듈을 동작시켜라. 이미 해결해봤으니 따라해:

1. config.toml에 [auth] 추가: port = 8080, algorithm = "HS256", session_timeout = 3600
2. .env에 AUTH_TOKEN 추가 (SERVICE_TOKEN이 아닌 AUTH_TOKEN 사용 — 형식 충돌 방지)
   AUTH_TOKEN=overmind-branch-test-auth-token-2026
3. bash start.sh로 auth 검증 통과 확인

config.toml, .env만 수정. src/ 수정 금지.
```

### SHARED_PROMPT (feat/api용, Student + Naive 공통)
```
feat/api branch의 api 모듈을 동작시켜라.
bash start.sh로 시작. 실패하면 조사해서 config.toml과 .env를 수정.
config.toml, .env만 수정 가능. src/ 수정 금지.
```

## 5. 측정 지표

| 지표 | 설명 | Student 기대 | Naive 기대 |
|------|------|:---:|:---:|
| `port_conflict_count` | AddressError 발생 횟수 | 0 | 1+ |
| `config_file_edits` | config 수정 횟수 | 적음 | 많음 |
| `server_run_attempts` | start.sh 실행 횟수 | 적음 | 많음 |
| `saw_server_running` | 최종 성공 | 높음 | 낮음 |
| `elapsed` | 총 소요 시간 | 빠름 | 느림 |
| `used_different_port` | 8080 외 port 사용 | True | False→재시도 |
| `used_separate_token_var` | AUTH_TOKEN/API_TOKEN 분리 사용 | True | False→재시도 |
| `used_separate_session` | section별 session_timeout | True | False→모순 |

### 신규 analyze 지표
`analyze_conversation()`에 branch-specific 지표 추가:
- `port_conflict_count`: "AddressError" 또는 "port conflict" 출현 횟수
- `used_different_port`: config.toml 최종 상태에서 [api].port != 8080
- `used_separate_token_var`: .env에 API_TOKEN 존재
- `used_separate_session`: config.toml에 [api].session_timeout 존재

## 6. scaffold 구현

### 6.1 파일: `server/tests/fixtures/ab_scaffolds/branch_conflict.py`

- `REPO_NAME = "hive-branch-conflict"`
- `REPO_ID = "github.com/test/hive-branch-conflict"`
- `MAX_TURNS = 30`
- `SCAFFOLD_FILES`: 위 2.1의 파일 구조
- `PIONEER_PROMPT`, `SHARED_PROMPT`: 위 4절
- `create_scaffold(base_dir, branch="feat/auth")`:
  1. `git init` + main commit
  2. `git checkout -b {branch}`
  3. return repo_dir
- `check_config(repo_dir)`: 각 트랩별 boolean + all_ok

### 6.2 `__init__.py` 등록
SCAFFOLDS dict에 `"branch_conflict": branch_conflict` 추가.

### 6.3 테스트 파일
기존 `test_live_agents_AB_statistical.py`에서 scaffold_name parametrize로 자동 포함.
단, branch_conflict는 Phase 1에서 feat/auth, Phase 2에서 feat/api로 branch가 달라야 하므로
**별도 테스트 함수** `test_branch_aware_ab()` 추가하거나, scaffold에 `create_scaffold()`가 branch 파라미터를 받는 구조.

### 6.4 ab_runner.py 변경
`run_agent()`에 `branch` 파라미터 추가 (optional). 지정 시 `OVERMIND_BRANCH` / `OVERMIND_BASE_BRANCH` 환경변수 주입, 또는 scaffold가 이미 해당 branch에 있으므로 플러그인이 `git rev-parse`로 자동 감지.

→ 실제 git branch이므로 **플러그인 수정 불필요**. `api_client.py`의 `get_current_branch()`가 자동 감지.

## 7. 검증 전략

### 7.1 단위 테스트 (서버 불필요)
- `check_config()` 정상/비정상 케이스
- scaffold 생성 후 branch 확인 (`git branch --show-current`)

### 7.2 E2E Live 테스트
```bash
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k branch_conflict --student-n 2 --naive-m 2 --agent-model haiku
```

### 7.3 성공 기준
- Student의 `port_conflict_count` 평균 < Naive 평균
- Student의 `saw_server_running` 비율 > Naive 비율
- Student의 `elapsed` 평균 < Naive 평균

## 8. 기존 코드 변경 최소화

| 파일 | 변경 | 유형 |
|------|------|------|
| `ab_scaffolds/branch_conflict.py` | 신규 | 신규 파일 |
| `ab_scaffolds/__init__.py` | import 추가 | 1줄 |
| `test_live_agents_AB_statistical.py` | branch-aware 테스트 함수 추가 | 신규 함수 |
| `ab_runner.py` | `analyze_conversation`에 branch 지표 추가 | 확장 |

플러그인, 서버, store 수정 없음. 기존 테스트 영향 없음.
