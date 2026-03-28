# Overmind — Project Context

## What is this?

Overmind는 복수의 독립적 Claude Code 인스턴스 간 메모리를 실시간 동기화하는 시스템이다.
두 아티팩트: **Overmind Server** (Python, FastAPI + FastMCP) + **Overmind Plugin** (Claude Code 플러그인).

## Current State: Phase 3 완료

### 완료된 것

**Server** (`server/`):
- Pydantic 모델, SQLite store with aiosqlite (push/pull/dedup/scope filter/TTL)
- FastAPI REST API: push, pull, broadcast, report, graph, timeline, repos
- FastMCP v3 wrapper: overmind_push, overmind_pull, overmind_broadcast, overmind_memory, overmind_feedback
- Web dashboard: Overview + Graph + Timeline + Flow View (Hive Mind 테마)
  - Graph: Flow View / Agent View / Scope View 모드 토글
  - Scope 필터 패널: scope 버튼 클릭 시 관련 노드/엣지 하이라이트, 다형성 scope 빨간 테두리
  - Agent 필터: 에이전트별 이벤트 필터링
  - Ghost 노드: 소비된 이벤트 복제본, puller's row에 ghost dots 표시
  - Broadcast push/pull 카운트 정확 반영
- Pull 이력 추적: 누가 어떤 이벤트를 consume했는지 in-memory 기록
- 단일 프로세스에서 REST + MCP + Dashboard 서빙 (port 7777)
- DB 관리 스크립트: `server/scripts/db_cleanup.py` (status/ttl/purge/vacuum/export)

**Plugin** (`plugin/`):
- Hook: SessionStart(auto pull), PostToolUse(변경 누적 + batch push), SessionEnd(잔여 flush), PreToolUse(conflict detection + blocking)
- PostToolUse: Write/Edit 완료 후 변경 파일을 state에 누적, 개수(5)/시간(30분)/스코프 전환 시 batch push
- PreToolUse: 구조화된 레슨 기반 충돌 감지 (deny/warn/ignore) + legacy high_priority fallback
- conflict_detector: StructuredLesson의 action/target을 tool_input과 매칭 (prohibit→deny, replace/avoid→warn, require→warn, prefer→ignore)
- Portable hooks: 크로스 플랫폼 Python 경로 자동 감지
- Skill: overmind-broadcast, overmind-report
- Command: /overmind:broadcast
- API client: urllib 기반 REST 호출, git remote → repo_id 정규화, flush 로직
- 마켓플레이스 배포 지원 (plugin manifest + hooks.json 스키마)

**Tests**: 204+ pass
- Server: 88개 (models 12 + store 22 + api 13 + mcp 6 + scenarios 28 + summary 2 + 기타)
- Plugin: 116개 (api_client 27 + flush_logic 22 + formatter 15 + context_writer 8 + diff_collector 6 + conflict_detector 18 + hooks 11 + 기타)
- E2E Live: 3개 시나리오 (AB, AB_multistage, AB_complex) — `claude` CLI 필요

**Docs**:
- `docs/prd.md` — PRD
- `docs/setup-guide.md` — 플러그인 설치 가이드
- `docs/research/overmind-research.md` — 아키텍처 연구 (v2.3)
- `docs/design/phase1-design.md` — Phase 1 설계 스펙
- `docs/plans/phase1-implementation.md` — Phase 1 구현 플랜 (11 tasks)

### 남은 작업

**검증**:
- ~~실제 2인 환경에서 push/pull 사이클 검증~~ ✅
- ~~Plugin 실제 설치 테스트~~ ✅
- ~~SessionEnd push 내용 개선~~ ✅ PostToolUse로 세션 중 변경 자동 push, SessionEnd는 잔여 flush만
- ~~테스트 보강~~ ✅ Plugin 59개 + Server 51개 = 110개 테스트

### 설계 인사이트 (반영 완료)

- ~~Pull 응답 최적화 (delta-only pull)~~ ✅ `since` 파라미터 + `last_pull_ts` 상태 추적으로 구현 완료
- ~~`detail` 파라미터~~ ✅ `?detail=summary|full` 구현 완료
- ~~서머리 생성~~ ✅ SummaryGenerator Protocol 구현 완료
- ~~urgent → high_priority 네이밍~~ ✅ 코드 전체 리네이밍 완료 (Priority = "normal" | "high_priority")

### Phase 2 계획 (A/B 병렬, 동등 우선순위)

**Phase 2-A: 서버 데이터 품질 개선**
- ~~서버 측 서머리 생성~~ ✅ (SummaryGenerator Protocol + MockSummaryGenerator, LLM 교체 대비)
- ~~`?detail=summary|full` pull 파라미터~~ ✅
- ~~SQLite store 이관~~ ✅
- ~~피드백 점수 (prevented_error, helpful/irrelevant) 축적~~ ✅ (feedback API + MCP tool + PreToolUse 자동)
- ~~PostToolUse lesson 필드 활용~~ → Phase 3으로 이관 (플러그인 연동 시 자동 타입 분류)
- ~~**Push "why" 보강**~~ ✅ git diff snippet + Bash 에러 context를 result에 포함 (diff_collector + PostToolUse context capture)

**Phase 2-B: 클라이언트 레슨 반영 (수신 측 영향력)**
- ~~`.claude/overmind-context.md` 동기화: 훅이 관리하는 전용 파일, TTL 기반 만료~~ ✅
- ~~pull 측 충돌 감지~~ ✅ conflict_detector: 구조화된 레슨 기반 deny/warn/ignore + legacy scope-aware fallback
- ~~overmind_memory MCP tool~~ ✅ 팀 메모리를 마크다운으로 조회 (scope 필터 지원)
- ~~구조화된 레슨 포맷~~ ✅ StructuredLesson `{action, target, reason, replacement}` — DB 영구 저장, push/pull round-trip
- 장기: Claude Code 플러그인 메모리 API 지원 시 네이티브 통합

연구 문서: `docs/research/cross-agent-influence.md`

**Phase 3: Branch-Aware Selective Intelligence** ✅
- ~~Branch metadata~~ ✅ `current_branch`/`base_branch` 자동 감지 (git) + MemoryEvent 필드 + DB 저장
- ~~이벤트 타입 분화~~ ✅ `intent` 타입 추가 — cross-branch 가치 높은 forward-looking 선언
- ~~Pull relevance 3-tier~~ ✅ same branch(all) > same base(intent/discovery/correction) > different(broadcast/high_priority only)
- ~~선택적 수용~~ ✅ PreToolUse에서 branch context 제공, formatter PLANNED CHANGES 섹션
- ~~Lesson 자동분류~~ ✅ lesson action → event type 매핑 (prohibit→correction, replace→decision, avoid→discovery)

## Tech Stack

- Python 3.11+, FastAPI, FastMCP v3, Pydantic v2, uvicorn
- Storage: SQLite (aiosqlite)
- Dashboard: Vanilla JS + D3.js v7 (CDN, no build)
- Fonts: Pretendard + SUIT(한글) + Orbitron(디스플레이) + JetBrains Mono(코드)
- Tests: pytest + pytest-asyncio + httpx TestClient + FastMCP in-memory Client
- Package: uv + pyproject.toml

## How to Run

```bash
# Server
cd server && uv sync --all-extras && uv run python -m overmind.main

# Tests (server 88 + plugin 116)
cd server && uv run pytest tests/ -v
cd server && uv run pytest ../plugin/tests/ -v

# Dashboard
# http://localhost:7777/dashboard (서버 실행 후)

# Cross-agent test data 생성
python server/tests/scenarios/crosstest.py

# DB 관리
python server/scripts/db_cleanup.py status          # 현황
python server/scripts/db_cleanup.py ttl --days 14   # TTL 정리
python server/scripts/db_cleanup.py vacuum           # 디스크 공간 회수
python server/scripts/db_cleanup.py export <repo_id> # JSONL 내보내기

# MCP 연결
claude mcp add overmind --transport http http://localhost:7777/mcp
```

## Key Files

| File | Purpose |
|------|---------|
| `server/overmind/models.py` | 모든 Pydantic 모델 (MemoryEvent, GraphEdge 등) |
| `server/overmind/store.py` | SQLite store (StoreProtocol + SQLiteStore, push/pull/graph/stats) |
| `server/overmind/api.py` | FastAPI REST 엔드포인트 (create_app) |
| `server/overmind/mcp_server.py` | FastMCP 도구 래퍼 (push/pull/broadcast/memory/feedback) |
| `server/overmind/main.py` | 서버 진입점 (REST + MCP 동시 서빙) |
| `server/overmind/dashboard/static/app.js` | 대시보드 JS (Overview + Graph/Flow + Timeline) |
| `server/overmind/dashboard/static/style.css` | 대시보드 CSS (Hive Mind 테마) |
| `server/overmind/dashboard/static/index.html` | 대시보드 HTML |
| `server/tests/scenarios/crosstest.py` | 교차 push/pull 테스트 스크립트 (서버 실행 상태에서) |
| `server/scripts/db_cleanup.py` | JSONL store 관리 (status/ttl/purge/compact/export) |
| `docs/setup-guide.md` | 플러그인 설치 가이드 (마켓플레이스/수동/환경변수) |
| `plugin/hooks/` | Claude Code 훅 (SessionStart/PostToolUse/SessionEnd/PreToolUse) |
| `plugin/hooks/on_post_tool_use.py` | PostToolUse 훅: 변경 누적 + batch push |
| `plugin/scripts/api_client.py` | 훅용 공유 HTTP 클라이언트 + flush 로직 |
| `plugin/scripts/conflict_detector.py` | 구조화된 레슨 기반 충돌 감지 (deny/warn/ignore) |
| `plugin/tests/` | Plugin 테스트 (api_client, formatter, flush, conflict_detector, hooks) |

## Conventions

- Line endings: LF (소스), CRLF (batch) — `.gitattributes`에서 관리
- `core.autocrlf = false`
- 커밋 메시지: conventional commits (feat/fix/refactor/chore/docs)
- 한글 사용 가능 (PRD, 연구문서, 이벤트 데이터 등)

## Design Principles

- **SOLID 원칙 준수**: 단일 책임, 개방-폐쇄, 리스코프 치환, 인터페이스 분리, 의존성 역전을 지킨다.
- **지속 가능한 프로젝트**: 유지보수성을 최우선으로 고려한다. 당장 동작하는 코드보다 오래 유지할 수 있는 코드를 작성한다.
- **인터페이스 우선**: 구현체를 교체할 수 있도록 Protocol/ABC로 계약을 먼저 정의한다.
- **테스트가 regression guard**: 기존 테스트가 깨지지 않는 범위에서 리팩토링한다.
