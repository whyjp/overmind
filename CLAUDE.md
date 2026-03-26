# Overmind — Project Context

## What is this?

Overmind는 복수의 독립적 Claude Code 인스턴스 간 메모리를 실시간 동기화하는 시스템이다.
두 아티팩트: **Overmind Server** (Python, FastAPI + FastMCP) + **Overmind Plugin** (Claude Code 플러그인).

## Current State: Phase 1 구현 완료 + 대시보드 개선 진행 중

### 완료된 것

**Server** (`server/`):
- Pydantic 모델, JSONL file-based store (push/pull/dedup/scope filter/TTL)
- FastAPI REST API: push, pull, broadcast, report, graph, timeline, repos
- FastMCP v3 wrapper: overmind_push, overmind_pull, overmind_broadcast
- Web dashboard: Overview + Graph + Timeline (Hive Mind 테마)
- Pull 이력 추적: 누가 어떤 이벤트를 consume했는지 in-memory 기록
- Graph: ghost 노드(소비된 이벤트 복제본), 2-column 레이아웃(Agent→Events), scope 인라인 태그
- 단일 프로세스에서 REST + MCP + Dashboard 서빙 (port 7777)
- DB 관리 스크립트: `server/scripts/db_cleanup.py` (status/ttl/purge/compact/export)

**Plugin** (`plugin/`):
- Hook: SessionStart(auto pull), SessionEnd(auto push), PreToolUse(selective pull on Write/Edit)
- Skill: overmind-broadcast, overmind-report
- Command: /overmind:broadcast
- API client: urllib 기반 REST 호출, git remote → repo_id 정규화

**Tests**: 33개 전부 pass (models 7 + store 11 + api 9 + mcp 3 + scenarios 3)

**Docs**:
- `docs/prd.md` — PRD
- `docs/research/overmind-research.md` — 아키텍처 연구 (v2.3)
- `docs/design/phase1-design.md` — Phase 1 설계 스펙
- `docs/design/phase1-implementation.md` — Phase 1 구현 플랜 (11 tasks)

### 다음 세션 즉시 TODO — 대시보드 그래프 개선

유저 피드백 3건이 대기 중이다. 우선순위 순:

1. **Scope 필터 패널**: `#graph-scope-filter` HTML은 이미 있고 CSS도 준비됨. scope 버튼을 렌더링하고, 클릭 시 해당 scope 관련 노드/엣지만 하이라이트(나머지 dim)하는 JS 로직 구현 필요. 다형성 scope는 빨간 테두리로 구분.

2. **Scope 기준 뷰 (그래프 모드 전환)**: 현재는 "에이전트 기준" 뷰(Agent→Event 흐름)만 있음. "Scope 기준" 뷰를 추가하여, scope를 중심 노드로 놓고 교차 push/pull을 시각화. 그래프 상단에 뷰 모드 토글(Agent View / Scope View) 추가.

3. **Broadcast push/pull 카운트**: broadcast는 push 1건이지만 여러 에이전트가 pull하므로, Overview의 push/pull 카운트가 이를 반영해야 함. 또한 graph에서 broadcast의 ghost 노드가 pull한 에이전트마다 생성되는지 확인.

### 아직 안 된 것 (Phase 1 범위 내)

- **실사용 검증**: 실제 2인 환경에서 push/pull 사이클 검증 미완료 (Go/No-Go 판정 전)
- **Plugin 실제 설치 테스트**: `claude --plugin-dir ./plugin`으로 실제 Claude Code 세션에서 hook 동작 미검증
- **SessionEnd push 내용**: 현재 단순 "session ended" 이벤트만 push — 세션 중 실제 correction/decision 캡처 로직 미구현
- **Hook 단위 테스트**: `plugin/tests/` — stdin 파이프로 Hook 스크립트 단독 실행 + 서버 mock 테스트 미작성
- **api_client.py 순수 함수 테스트**: normalize_git_remote, file_to_scope 등
- **E2E 서버 시나리오 테스트**: subprocess로 서버 기동 → httpx 실제 HTTP 호출 자동화
- **Concurrent push stress test**: asyncio.gather 동시 push race condition 검증

### 설계 인사이트 (스펙 반영 대기)

디자인 스펙에 아직 반영되지 않은 논의 결과:

1. **Pull 응답 최적화 원칙**: 매 프롬프팅 훅 시점에서 pull되는 데이터는 "이전 pull 이후 delta"만. context 부담은 프롬프트 간격 × 동시 작업자 수의 함수. 기본 pull은 PRD/spec diff + lesson만, 풀 컨텍스트는 예외적 경우에만.
2. **`detail` 파라미터 Phase 1 도입**: `?detail=lesson` (기본) | `diff` | `full` — Phase 2가 아닌 Phase 1부터.
3. **서머리 생성 대부분 LLM 불필요**: result 필드 추출 + 문서 diff는 구조적 추출로 처리 가능, LLM은 process→lesson 압축 시에만.
4. **urgent → high_priority**: "urgent"라는 단어가 즉시 알림을 암시하지만, 실제 동작은 pull 시 상단 정렬뿐. 네이밍 재검토 필요.

반영 대상 위치: design spec §3.2 (pull API), §5.2 (훅 동작), §10 (확장 경로)

### 테스트 유효성 분석

- **기계적 100% 검증 가능**: Models, Store, REST API, MCP, 시나리오 (Task 1-8)
- **기계적 부분 검증**: Hook 스크립트 (stdin→stdout 파이프), api_client 순수 함수
- **사람 테스트 필수**: Claude가 systemMessage를 해석하여 사전 고지하는가 (= Go/No-Go 기준 자체)
- 배관 자동화 완료 후, 사람 테스트는 "Claude의 lesson surface 판단" 한 가지에만 집중 가능

### Phase 2 계획

- 서버 측 서머리 생성 (경량 LLM — process→lesson 압축 시에만)
- `?detail=lesson|diff|full` pull 파라미터 (Phase 1 후반 또는 Phase 2 초반)
- SQLite store 이관
- 피드백 점수 (relevance_score, prevented_error) 축적
- SessionEnd에서 세션 내용을 분석하여 의미 있는 이벤트 자동 추출

## Tech Stack

- Python 3.11+, FastAPI, FastMCP v3, Pydantic v2, uvicorn
- Storage: JSONL file-based (Phase 2: SQLite)
- Dashboard: Vanilla JS + D3.js v7 (CDN, no build)
- Fonts: Pretendard + SUIT(한글) + Orbitron(디스플레이) + JetBrains Mono(코드)
- Tests: pytest + pytest-asyncio + httpx TestClient + FastMCP in-memory Client
- Package: uv + pyproject.toml

## How to Run

```bash
# Server
cd server && uv sync --all-extras && uv run python -m overmind.main

# Tests
cd server && uv run pytest tests/ -v

# Dashboard
# http://localhost:7777/dashboard (서버 실행 후)

# Cross-agent test data 생성
python server/tests/scenarios/crosstest.py

# DB 관리
python server/scripts/db_cleanup.py status          # 현황
python server/scripts/db_cleanup.py ttl --days 14   # TTL 정리
python server/scripts/db_cleanup.py compact          # 빈 파일/중복 제거
python server/scripts/db_cleanup.py export <repo_id> # JSONL 내보내기

# MCP 연결
claude mcp add overmind --transport http http://localhost:7777/mcp
```

## Key Files

| File | Purpose |
|------|---------|
| `server/overmind/models.py` | 모든 Pydantic 모델 (MemoryEvent, GraphEdge 등) |
| `server/overmind/store.py` | JSONL store 핵심 로직 (push/pull/graph/stats/pull_log) |
| `server/overmind/api.py` | FastAPI REST 엔드포인트 (create_app) |
| `server/overmind/mcp_server.py` | FastMCP 도구 래퍼 (create_mcp_server) |
| `server/overmind/main.py` | 서버 진입점 (REST + MCP 동시 서빙) |
| `server/overmind/dashboard/static/app.js` | 대시보드 JS (Overview + Graph + Timeline) |
| `server/overmind/dashboard/static/style.css` | 대시보드 CSS (Hive Mind 테마) |
| `server/overmind/dashboard/static/index.html` | 대시보드 HTML |
| `server/tests/scenarios/crosstest.py` | 교차 push/pull 테스트 스크립트 (서버 실행 상태에서) |
| `server/scripts/db_cleanup.py` | JSONL store 관리 (status/ttl/purge/compact/export) |
| `plugin/hooks/` | Claude Code 훅 (Python 스크립트) |
| `plugin/scripts/api_client.py` | 훅용 공유 HTTP 클라이언트 |

## Conventions

- Line endings: LF (소스), CRLF (batch) — `.gitattributes`에서 관리
- `core.autocrlf = false`
- 커밋 메시지: conventional commits (feat/fix/refactor/chore/docs)
- 한글 사용 가능 (PRD, 연구문서, 이벤트 데이터 등)
