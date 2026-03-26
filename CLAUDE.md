# Overmind — Project Context

## What is this?

Overmind는 복수의 독립적 Claude Code 인스턴스 간 메모리를 실시간 동기화하는 시스템이다.
두 아티팩트: **Overmind Server** (Python, FastAPI + FastMCP) + **Overmind Plugin** (Claude Code 플러그인).

## Current State: Phase 1 구현 완료 + 대시보드 완성

### 완료된 것

**Server** (`server/`):
- Pydantic 모델, JSONL file-based store (push/pull/dedup/scope filter/TTL)
- FastAPI REST API: push, pull, broadcast, report, graph, timeline, repos
- FastMCP v3 wrapper: overmind_push, overmind_pull, overmind_broadcast (lifespan 수정 완료)
- Web dashboard: Overview + Graph + Timeline + Flow View (Hive Mind 테마)
  - Graph: Flow View / Agent View / Scope View 모드 토글
  - Scope 필터 패널: scope 버튼 클릭 시 관련 노드/엣지 하이라이트, 다형성 scope 빨간 테두리
  - Agent 필터: 에이전트별 이벤트 필터링
  - Ghost 노드: 소비된 이벤트 복제본, puller's row에 ghost dots 표시
  - Broadcast push/pull 카운트 정확 반영
- Pull 이력 추적: 누가 어떤 이벤트를 consume했는지 in-memory 기록
- 단일 프로세스에서 REST + MCP + Dashboard 서빙 (port 7777)
- DB 관리 스크립트: `server/scripts/db_cleanup.py` (status/ttl/purge/compact/export)

**Plugin** (`plugin/`):
- Hook: SessionStart(auto pull), SessionEnd(auto push), PreToolUse(selective pull on Write/Edit)
- Portable hooks: 크로스 플랫폼 Python 경로 자동 감지
- Skill: overmind-broadcast, overmind-report
- Command: /overmind:broadcast
- API client: urllib 기반 REST 호출, git remote → repo_id 정규화
- 마켓플레이스 배포 지원 (plugin manifest + hooks.json 스키마)

**Tests**: 33개 전부 pass (models 7 + store 11 + api 9 + mcp 3 + scenarios 3)

**Docs**:
- `docs/prd.md` — PRD
- `docs/setup-guide.md` — 플러그인 설치 가이드
- `docs/research/overmind-research.md` — 아키텍처 연구 (v2.3)
- `docs/design/phase1-design.md` — Phase 1 설계 스펙
- `docs/plans/phase1-implementation.md` — Phase 1 구현 플랜 (11 tasks)

### 남은 작업

**검증**:
- 실제 2인 환경에서 push/pull 사이클 검증 (Go/No-Go 판정)
- Plugin 실제 설치 테스트 (`claude --plugin-dir ./plugin`)
- SessionEnd push 내용 개선: 현재 단순 "session ended" → 실제 correction/decision 캡처

**테스트 보강**:
- Hook 단위 테스트 (`plugin/tests/`): stdin 파이프 + 서버 mock
- api_client.py 순수 함수 테스트: normalize_git_remote, file_to_scope 등
- E2E 서버 시나리오 테스트: subprocess 기동 → httpx 실제 HTTP 호출
- Concurrent push stress test: asyncio.gather race condition 검증

### 설계 인사이트 (스펙 반영 대기)

디자인 스펙에 아직 반영되지 않은 논의 결과:

1. **Pull 응답 최적화 원칙**: delta-only pull, context 부담 = 프롬프트 간격 × 동시 작업자 수
2. **`detail` 파라미터**: `?detail=lesson` (기본) | `diff` | `full`
3. **서머리 생성**: 구조적 추출 우선, LLM은 process→lesson 압축 시에만
4. **urgent → high_priority**: 네이밍 재검토 필요 (실제 동작은 pull 시 상단 정렬뿐)

반영 대상: design spec §3.2 (pull API), §5.2 (훅 동작), §10 (확장 경로)

### Phase 2 계획 (A/B 병렬, 동등 우선순위)

**Phase 2-A: 서버 데이터 품질 개선**
- 서버 측 서머리 생성 (경량 LLM — process→lesson 압축 시에만)
- `?detail=lesson|diff|full` pull 파라미터
- SQLite store 이관
- 피드백 점수 (relevance_score, prevented_error) 축적
- SessionEnd 세션 내용 분석 → 의미 있는 이벤트 자동 추출

**Phase 2-B: 클라이언트 레슨 반영 (수신 측 영향력)**
- `.claude/overmind-context.md` 동기화: 훅이 관리하는 전용 파일, TTL 기반 만료
- pull 측 충돌 감지: 현재 편집 의도 vs 레슨 내용 비교 → deny/ask/systemMessage 판단
- MCP resource: `overmind://memory/{repo_id}` 팀 메모리 조회
- 구조화된 레슨 포맷: `{action, target, reason}` → 키워드 매칭 기반 충돌 감지
- 장기: Claude Code 플러그인 메모리 API 지원 시 네이티브 통합

연구 문서: `docs/research/cross-agent-influence.md`

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
| `server/overmind/dashboard/static/app.js` | 대시보드 JS (Overview + Graph/Flow + Timeline) |
| `server/overmind/dashboard/static/style.css` | 대시보드 CSS (Hive Mind 테마) |
| `server/overmind/dashboard/static/index.html` | 대시보드 HTML |
| `server/tests/scenarios/crosstest.py` | 교차 push/pull 테스트 스크립트 (서버 실행 상태에서) |
| `server/scripts/db_cleanup.py` | JSONL store 관리 (status/ttl/purge/compact/export) |
| `docs/setup-guide.md` | 플러그인 설치 가이드 (마켓플레이스/수동/환경변수) |
| `plugin/hooks/` | Claude Code 훅 (Python 스크립트) |
| `plugin/scripts/api_client.py` | 훅용 공유 HTTP 클라이언트 |

## Conventions

- Line endings: LF (소스), CRLF (batch) — `.gitattributes`에서 관리
- `core.autocrlf = false`
- 커밋 메시지: conventional commits (feat/fix/refactor/chore/docs)
- 한글 사용 가능 (PRD, 연구문서, 이벤트 데이터 등)
