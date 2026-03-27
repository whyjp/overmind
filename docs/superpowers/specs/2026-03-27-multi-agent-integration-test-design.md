# Multi-Agent Integration Test (Hook 시뮬레이션 + Claude CLI)

**Date**: 2026-03-27
**Status**: Approved

## 배경

현재 Overmind 테스트는 단위 테스트와 단일 agent E2E까지 커버하지만, 두 agent가 병렬로 작업하며 cross-agent 정보 교환이 실제로 작동하는지 검증하는 통합 테스트가 없다.

두 레벨의 테스트를 구축한다:
- **C (Hook 시뮬레이션)**: 서버 + hook subprocess 교차 호출, 결정적, CI 적합
- **A (Claude CLI)**: 실제 `claude -p`로 agent 2개 병렬 실행, 수동 실행

## Scaffold 프로젝트: "Hive"

테스트용 임시 git repo. 팀 태스크 관리 API 프로젝트를 시뮬레이션.

```
hive/
├── package.json
├── .env.example
├── src/
│   ├── index.ts
│   ├── config/
│   │   ├── database.ts
│   │   └── env.ts
│   ├── models/
│   │   ├── user.ts
│   │   ├── task.ts
│   │   └── team.ts
│   ├── auth/
│   │   ├── middleware.ts
│   │   ├── jwt.ts
│   │   └── routes.ts
│   ├── api/
│   │   ├── users.ts
│   │   ├── tasks.ts
│   │   └── teams.ts
│   ├── services/
│   │   ├── notification.ts
│   │   └── cache.ts
│   └── utils/
│       ├── logger.ts
│       └── errors.ts
├── tests/
│   ├── auth.test.ts
│   └── tasks.test.ts
└── docs/
    └── api.md
```

파일 내용은 최소한의 stub (타입 정의, import, TODO 주석 정도). 실제 동작하는 코드일 필요 없음 — agent가 수정할 수 있을 정도의 구조만 제공.

### scaffold 생성

`server/tests/fixtures/scaffold_hive.py`에 scaffold 생성 함수를 정의:

```python
def create_hive_repo(base_dir: Path) -> Path:
    """Create a scaffolded 'Hive' project as a git repo. Returns repo path."""
```

- `base_dir / "hive"` 에 디렉토리 트리 생성
- 각 파일에 stub 내용 작성
- `git init` + `git add . && git commit -m "initial"`
- git remote를 fake로 설정: `git remote add origin https://github.com/test/hive.git`
- repo path 반환

## 시나리오: 두 Agent의 병렬 기능 개발

### Agent A: "OAuth2 + PKCE 인증 도입"

작업 대상 파일:
- `src/auth/jwt.ts` — OAuth2 토큰 핸들링 추가
- `src/auth/routes.ts` — OAuth2 콜백 엔드포인트
- `src/auth/middleware.ts` — JWT + OAuth2 듀얼 지원 **(충돌 지점)**
- `src/config/env.ts` — OAUTH_CLIENT_ID, OAUTH_SECRET 추가 **(충돌 지점)**
- `.env.example` — 새 환경 변수 문서화

### Agent B: "태스크 할당 + 알림 시스템"

작업 대상 파일:
- `src/api/tasks.ts` — 할당 엔드포인트
- `src/models/task.ts` — assignee 필드 추가
- `src/services/notification.ts` — 할당 시 이메일 알림
- `src/auth/middleware.ts` — role-based 권한 추가 **(충돌 지점)**
- `src/config/env.ts` — SMTP_HOST, SMTP_PORT 추가 **(충돌 지점)**

### 의도적 충돌 지점

| Scope | Agent A | Agent B | 기대 Overmind 반응 |
|-------|---------|---------|-------------------|
| `src/auth/middleware.ts` | OAuth2 지원 | role 권한 | polymorphism 감지, PreToolUse 경고 |
| `src/config/env.ts` | OAuth 변수 | SMTP 변수 | scope 변경 알림 |
| `src/auth/*` 전체 | 주 작업 영역 | 부분 의존 | SessionStart RULES 주입 |

## 테스트 C: Hook 시뮬레이션

**파일**: `server/tests/scenarios/test_multi_agent_sim.py`

서버를 thread에서 실행하고, hook 스크립트를 subprocess로 교차 호출하여 두 agent의 작업 흐름을 시뮬레이션.

### 시뮬레이션 시퀀스

```
시간 →

Agent A                              Agent B
───────                              ───────
1. SessionStart (pull)               2. SessionStart (pull)
   → 이벤트 없음, 조용                  → 이벤트 없음, 조용

3. PostToolUse: auth/jwt.ts
4. PostToolUse: auth/routes.ts
5. PostToolUse: auth/middleware.ts
                                     6. PreToolUse: auth/middleware.ts
                                        → A의 변경 경고 systemMessage 수신 ✓
                                     7. PostToolUse: api/tasks.ts
                                     8. PostToolUse: models/task.ts

9. PostToolUse: config/env.ts
   (5개 누적 → flush 발생)
   → change 이벤트 서버 push ✓
                                     10. PostToolUse: services/notification.ts
                                     11. PostToolUse: auth/middleware.ts
                                     12. PostToolUse: config/env.ts
                                         (5개 누적 → flush 발생)
                                         → change 이벤트 서버 push ✓

13. PreToolUse: config/env.ts
    → B의 config 변경 경고 수신 ✓

14. SessionEnd (A)                   15. SessionEnd (B)
    → 잔여 flush                         → 잔여 flush
```

### 검증 항목

1. **PostToolUse 누적**: state file에 pending_changes 누적 확인
2. **Flush 발생**: 5개 누적 시 서버에 `change` 이벤트 push 확인
3. **PreToolUse cross-agent 경고**: Agent B가 `src/auth/*` 진입 시 A의 이벤트를 systemMessage로 수신
4. **Polymorphism 감지**: Graph API에서 `src/auth/*` scope에 두 user 감지
5. **Scope 분리**: `src/api/*` pull에 `src/auth/*` 이벤트 안 섞임
6. **SessionEnd flush**: 잔여 pending 이벤트 push 확인
7. **Report 정확성**: total_pushes, unique_users, events_by_type 검증

### 구현 구조

```python
@pytest.fixture(scope="module")
def server(tmp_path_factory):
    # ServerThread로 Overmind 서버 실행

@pytest.fixture(scope="module")
def hive_repo(tmp_path_factory):
    # scaffold_hive.create_hive_repo() 호출

def run_hook(script, env, stdin_data=""):
    # 기존 test_hooks_e2e.py의 run_hook 재사용

class TestMultiAgentSimulation:
    def test_full_sequence(self, server, base_url, hive_repo, tmp_path):
        # 위 시퀀스 1-15 순차 실행
        # 각 단계별 assertion
```

## 테스트 A: Claude CLI 실제 실행

**파일**: `server/tests/scenarios/test_live_agents.py`

**마커**: `@pytest.mark.e2e_live` — 기본 CI에서 제외, 수동 실행만.

### 실행 흐름

```python
@pytest.mark.e2e_live
class TestLiveAgents:
    def test_parallel_agents(self, ...):
        # 1. Hive scaffold repo 생성
        # 2. Overmind server 시작
        # 3. Agent A, B 병렬 실행
        proc_a = subprocess.Popen([
            "claude", "-p",
            "Add OAuth2+PKCE authentication. Modify auth/jwt.ts, auth/routes.ts, "
            "auth/middleware.ts, config/env.ts, .env.example. "
            "Use passport-oauth2 v4.x (v3.x doesn't support PKCE).",
            "--max-turns", "10",
            "--plugin-dir", str(plugin_dir),
        ], cwd=str(hive_repo), env=agent_a_env)

        proc_b = subprocess.Popen([
            "claude", "-p",
            "Add task assignment with email notifications. Modify api/tasks.ts, "
            "models/task.ts, services/notification.ts, auth/middleware.ts (add role check), "
            "config/env.ts (add SMTP settings).",
            "--max-turns", "10",
            "--plugin-dir", str(plugin_dir),
        ], cwd=str(hive_repo), env=agent_b_env)

        proc_a.wait(timeout=120)
        proc_b.wait(timeout=120)

        # 4. Overmind 서버 검증
```

### Claude CLI 환경 설정

각 agent는 별도 OVERMIND_USER와 OVERMIND_STATE_FILE을 사용:

```python
agent_a_env = {
    **os.environ,
    "OVERMIND_URL": base_url,
    "OVERMIND_REPO_ID": "github.com/test/hive",
    "OVERMIND_USER": "agent_a",
    "OVERMIND_STATE_FILE": str(tmp_path / "state_a.json"),
}
```

### 검증 (Soft Assertions)

실제 LLM은 비결정적이므로 검증은 soft:

1. **이벤트 존재**: 서버에 `agent_a`와 `agent_b`의 이벤트가 각각 1개 이상 존재
2. **Scope 커버리지**: `src/auth/*` scope에 양쪽 agent의 이벤트 존재
3. **타입 확인**: `change` 타입 이벤트가 존재
4. **Polymorphism**: Graph API에서 polymorphism alert 1개 이상 (auth scope)

hard assertion이 아닌 **경고 + 리포트** 방식:

```python
# Hard: 이벤트가 존재해야 함
assert events["count"] >= 2, "At least 2 events expected from 2 agents"

# Soft: polymorphism은 agent 행동에 따라 달라질 수 있음
if not graph["polymorphisms"]:
    warnings.warn("No polymorphism detected — agents may not have overlapped")
```

## pytest 마커 설정

`server/pyproject.toml`에 마커 등록:

```toml
[tool.pytest.ini_options]
markers = [
    "e2e_live: requires real Claude CLI, run manually (deselect by default)",
    "multi_agent: multi-agent simulation tests",
]
```

기본 실행 시 e2e_live 제외:

```toml
addopts = "-m 'not e2e_live'"
```

## 변경 파일 요약

| 변경 | 파일 |
|------|------|
| 신규 | `server/tests/fixtures/scaffold_hive.py` |
| 신규 | `server/tests/scenarios/test_multi_agent_sim.py` |
| 신규 | `server/tests/scenarios/test_live_agents.py` |
| 수정 | `server/pyproject.toml` (pytest 마커) |
