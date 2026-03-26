# Overmind Phase 1 Design Spec

> Date: 2026-03-26
> Status: Approved
> Scope: Phase 1 PoC — 레이어드 빌드 (서버 코어 → MCP 래퍼 → 플러그인 + 대시보드)

---

## 1. 목표

Phase 1의 목표는 Overmind 아키텍처의 핵심 push/pull 사이클을 검증하는 것이다.

**Go/No-Go 판정 기준** (연구 문서 §4.1):
1. 의도적 lesson 전파가 실제로 이루어지는가
2. 피드백 점수(relevance_score, prevented_error)가 확보되는가

**접근법**: 레이어드 빌드
- 레이어 1: 서버 코어 (REST API + JSONL store)
- 레이어 2: FastMCP 래퍼 (MCP tool 노출)
- 레이어 3: Claude Code 플러그인 (훅 + 스킬 + 슬래시 커맨드)
- 레이어 4: 백오피스 대시보드 (D3.js 그래프 + 통계 + 타임라인)

---

## 2. 데이터 모델

### 2.1 JSONL 이벤트 스키마

```python
# 필수 필드
{
  "id": str,          # uuid4 — 중복 제거 키
  "repo_id": str,     # 정규화된 repo 식별자
  "user": str,        # 작업 주체 식별자 (dev_a, agent_1, ...)
  "ts": str,          # ISO 8601 타임스탬프
  "type": str,        # "decision" | "correction" | "discovery" | "change" | "broadcast"
  "result": str       # 핵심 결론 (한 줄)
}

# 선택 필드
{
  "prompt": str,          # 작업 맥락 요약
  "files": list[str],     # 관련 파일 경로 (scope 인덱싱에 사용)
  "process": list[str],   # 과정 기록 (시도 → 실패 → 해결)
  "priority": str,        # "normal" | "urgent" (broadcast용)
  "scope": str            # 명시적 scope (broadcast용)
}
```

### 2.2 repo_id 식별

```python
# git remote origin URL에서 정규화
# "git@github.com:user/project.git" → "github.com/user/project"
# "https://github.com/user/project.git" → "github.com/user/project"
repo_id = normalize_git_remote(origin_url)

# remote 없는 로컬 전용 repo → "local/{directory_hash}" fallback
```

### 2.3 스토리지 레이아웃

```
data/
├── repos/
│   └── {repo_id}/
│       ├── events/
│       │   ├── {user}/
│       │   │   └── YYYY-MM-DD.jsonl    # 유저별 일별 append-only
│       │   └── ...
│       └── index/
│           └── scope.json              # files[] → event id 역인덱스
└── meta/
    └── repos.json                      # repo_id → 메타데이터
```

- 쓰기: append-only JSONL. 중복 제거는 `id` 기반 set check.
- scope 인덱스: `files[]` 각 경로를 glob 패턴으로 매핑하여 event id 리스트 관리.
- TTL: 14일. 서버 시작 시 만료 이벤트 정리.

---

## 3. REST API

### 3.1 POST /api/memory/push

```python
# Request
{
  "repo_id": "github.com/user/project",
  "user": "dev_a",
  "events": [
    {
      "id": "evt_...",
      "type": "correction",
      "ts": "2026-03-26T14:30:22+09:00",
      "result": ".env에 SERVICE_A_INTERNAL_URL 필요",
      "files": ["src/config/env.ts"],
      "process": ["ECONNREFUSED 발생", "SERVICE_A_INTERNAL_URL 미설정 확인"]
    }
  ]
}

# Response 200
{"accepted": 2, "duplicates": 0}
```

### 3.2 GET /api/memory/pull

```
?repo_id=...          # 필수
&since=...            # 선택 (기본: 24h 전)
&scope=src/auth/*     # 선택 (glob 패턴)
&user=dev_a           # 선택 (특정 유저만)
&exclude_user=dev_b   # 선택 (자기 자신 제외)
&limit=50             # 선택 (기본: 50)
```

```python
# Response 200
{"events": [...], "count": 12, "has_more": false}
```

### 3.3 POST /api/memory/broadcast

```python
# Request
{
  "repo_id": "github.com/user/project",
  "user": "master_agent",
  "priority": "urgent",
  "scope": "src/api/*",
  "message": "API 스키마 v2로 변경",
  "related_files": ["src/api/schema.ts"]
}

# Response 200
{"id": "evt_...", "delivered": true}
```

내부적으로 `type: "broadcast"` 이벤트로 변환, 동일 JSONL store에 저장. pull 시 `priority: "urgent"` 상단 정렬.

### 3.4 GET /api/report

```python
# ?repo_id=... 필수
# Response 200
{
  "repo_id": "...",
  "period": "24h",
  "total_pushes": 47,
  "total_pulls": 23,
  "unique_users": 3,
  "events_by_type": {"correction": 12, "decision": 8, ...}
}
```

### 3.5 GET /api/report/graph

```python
# ?repo_id=...&since=...
# Response 200
{
  "nodes": [
    {"id": "dev_a", "type": "user"},
    {"id": "evt_001", "type": "event", "event_type": "correction", ...},
    {"id": "src/auth/*", "type": "scope"}
  ],
  "edges": [
    {"source": "dev_a", "target": "evt_001", "relation": "pushed"},
    {"source": "evt_001", "target": "src/auth/*", "relation": "affects"}
  ],
  "polymorphisms": [
    {"scope": "src/auth/*", "users": ["dev_a", "dev_b"], "intents": ["보안 강화", "성능 최적화"]}
  ]
}
```

### 3.6 GET /api/report/timeline

```python
# ?repo_id=...&since=...
# Response 200 — 유저별 swimlane 데이터
```

### 3.7 에러 응답

- 400: 필수 필드 누락 `{"error": "repo_id is required"}`
- 404: 존재하지 않는 repo `{"error": "repo not found", "repo_id": "..."}`

---

## 4. MCP 래퍼

REST API 위에 얇은 FastMCP 래퍼. 동일 프로세스에서 REST(FastAPI) + MCP(FastMCP streamable-http) 동시 서빙.

```python
@mcp.tool()
async def overmind_push(repo_id: str, user: str, events: list[dict]) -> dict
    # → POST /api/memory/push

@mcp.tool()
async def overmind_pull(
    repo_id: str,
    exclude_user: str | None = None,
    since: str | None = None,
    scope: str | None = None,
    limit: int = 50
) -> dict
    # → GET /api/memory/pull

@mcp.tool()
async def overmind_broadcast(
    repo_id: str, user: str, message: str,
    priority: str = "normal",
    scope: str | None = None,
    related_files: list[str] | None = None
) -> dict
    # → POST /api/memory/broadcast
```

포트: REST `http://localhost:7777/api/...`, MCP `http://localhost:7777/mcp`

클라이언트 연결: `claude mcp add overmind --transport http http://localhost:7777/mcp`

---

## 5. 플러그인

### 5.1 구조

```
overmind-plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── hooks/
│   ├── hooks.json
│   ├── on_session_start.py        # pull 트리거
│   ├── on_session_end.py          # push 트리거
│   └── on_pre_tool_use.py         # Write/Edit 시 관련 영역 pull
├── skills/
│   ├── overmind-broadcast/
│   │   └── SKILL.md
│   └── overmind-report/
│       └── SKILL.md
├── commands/
│   └── broadcast.md
└── scripts/
    └── api_client.py              # 공용 REST client
```

### 5.2 훅 동작

**SessionStart → pull**
1. git remote에서 repo_id 도출
2. `GET /api/memory/pull?repo_id=...&exclude_user={self}&since={last_pull_ts}`
3. 결과를 `systemMessage`로 반환 → Claude context injection

**SessionEnd → push**
1. 세션 중 주요 인터랙션을 JSONL 이벤트로 구성
2. `POST /api/memory/push`

**PreToolUse(Write/Edit) → 선택적 pull**
1. `tool_input.file_path`에서 scope 추출 (예: `src/auth/oauth2.ts` → `src/auth/*`)
2. `GET /api/memory/pull?repo_id=...&scope=src/auth/*&exclude_user={self}`
3. 관련 이벤트 있으면 `systemMessage`로 선제 고지, 없으면 빈 응답

### 5.3 hooks.json

```json
{
  "hooks": [
    {
      "event": "SessionStart",
      "command": "python hooks/on_session_start.py",
      "timeout": 5000
    },
    {
      "event": "SessionEnd",
      "command": "python hooks/on_session_end.py",
      "timeout": 5000
    },
    {
      "event": "PreToolUse",
      "matcher": {"tool_name": "^(Write|Edit)$"},
      "command": "python hooks/on_pre_tool_use.py",
      "timeout": 3000
    }
  ]
}
```

### 5.4 설계 결정

- 훅은 Python (Windows 호환 + 서버와 언어 일치 + LLM 확장 용이)
- 훅 → REST 직접 호출 (httpx). MCP는 Claude 인터랙티브 사용 전용.
- `last_pull_ts`는 로컬 `.overmind_state.json`에 기록하여 중복 수신 방지

---

## 6. 백오피스 대시보드

FastAPI `StaticFiles`로 서빙. `http://localhost:7777/dashboard`로 접근. 빌드 도구 없이 vanilla JS + D3.js CDN.

### 6.1 탭 구성

**Overview**: repo별 push/pull 횟수, 유저 수, 이벤트 타입 분포, 시간대별 볼륨 차트, 최근 이벤트 피드

**Graph**: D3.js force-directed graph
- 노드: User/Agent(●), Event(■), File/Scope(◆) — 타입별 색상/아이콘 구분
- 엣지: pushed(User→Event), affects(Event→Scope), pulled(User←Event, 점선)
- 같은 scope에 복수 유저 이벤트 → 다형성 경고 시각적 강조 (빨간 엣지/글로우)
- 노드 클릭 → 상세 정보 패널 (이벤트 JSON, process 로그)

**Timeline**: 유저별 swimlane 수평 타임라인
- 같은 시간대 + 같은 scope 이벤트 간 연결선
- broadcast는 모든 swimlane 관통 수직선

### 6.2 추가 API

- `GET /api/report/graph?repo_id=...&since=...` — 노드/엣지/다형성 데이터
- `GET /api/report/timeline?repo_id=...&since=...` — swimlane 데이터

---

## 7. 테스트 전략

### 7.1 레이어별 단위 테스트 (pytest)

**서버 코어** (`tests/test_store.py`, `tests/test_api.py`):
- push/pull 기본, 중복 제거, scope 필터, since 필터, self 제외, TTL 만료, broadcast 정렬, 400/404 에러

**MCP** (`tests/test_mcp.py`):
- FastMCP in-memory client로 복수 클라이언트 push/pull, broadcast 우선 정렬, concurrent push race condition

**훅** (`tests/test_hooks.py`):
- stdin JSON pipe로 각 훅 단독 실행, stdout/exit code 검증

### 7.2 목업 시나리오 (1인 검증)

- **사전 차단**: dev_a `.env` 해결 push → dev_b 해당 영역 pull → lesson 포함 확인
- **다형성 감지**: dev_a "보안", dev_b "성능" 동일 scope push → dev_c pull → 양쪽 intent 수신 확인
- **복수 repo 격리**: repo_1 push가 repo_2 pull에 나타나지 않는지 확인

---

## 8. 프로젝트 디렉토리 구조

```
overmind/
├── docs/
│   ├── overmind-research.md
│   └── superpowers/specs/
│       └── 2026-03-26-overmind-phase1-design.md   # 이 문서
├── server/
│   ├── overmind/
│   │   ├── __init__.py
│   │   ├── models.py              # Pydantic 모델
│   │   ├── store.py               # JSONL store + scope index + TTL
│   │   ├── api.py                 # FastAPI REST endpoints
│   │   ├── mcp_server.py          # FastMCP wrapper
│   │   └── dashboard/
│   │       ├── __init__.py
│   │       └── static/
│   │           ├── index.html
│   │           ├── app.js
│   │           └── style.css
│   ├── tests/
│   │   ├── test_store.py
│   │   ├── test_api.py
│   │   ├── test_mcp.py
│   │   └── scenarios/
│   │       ├── test_scenario_preemptive_block.py
│   │       ├── test_scenario_polymorphism.py
│   │       └── test_scenario_multi_repo.py
│   ├── pyproject.toml
│   └── README.md
├── plugin/
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── .mcp.json
│   ├── hooks/
│   │   ├── hooks.json
│   │   ├── on_session_start.py
│   │   ├── on_session_end.py
│   │   └── on_pre_tool_use.py
│   ├── skills/
│   │   ├── overmind-broadcast/
│   │   │   └── SKILL.md
│   │   └── overmind-report/
│   │       └── SKILL.md
│   ├── commands/
│   │   └── broadcast.md
│   └── scripts/
│       └── api_client.py
└── README.md
```

---

## 9. 기술 스택

| 컴포넌트 | 기술 |
|----------|------|
| 서버 프레임워크 | FastAPI (REST) + FastMCP (MCP) |
| 스토리지 | File-based JSONL (Phase 2에서 SQLite) |
| 대시보드 | Vanilla JS + D3.js (CDN, no build) |
| 플러그인 훅 | Python (httpx로 REST 호출) |
| 테스트 | pytest + FastMCP in-memory client + httpx TestClient |
| 패키지 관리 | uv + pyproject.toml |

---

## 10. Phase 1 이후 확장 경로

Phase 1 Go/No-Go 통과 시:
- Phase 2: SQLite 이관, 서머리 생성 (경량 LLM), `?detail=lesson|summary|full`
- Phase 3: broadcast urgent SSE, 다형성 서버 측 사전 탐지, 자기평가 메타 리포트
