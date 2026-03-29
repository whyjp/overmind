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
- API client: urllib 기반 REST 호출, git remote → repo_id 정규화, flush 로직, 명시적 cwd 기반 branch 감지
- 마켓플레이스 배포 지원 (plugin manifest + hooks.json 스키마)

**Tests**: 256 pass (server 134 + plugin 122)
- Server: 134개 (models 12 + store 30 + api 14 + mcp 6 + scenarios 28 + summary 2 + nightmare 18 + branch_conflict 11 + microservices 15) — 4 deselected (e2e_live/multi_agent 마커)
- Plugin: 122개 (api_client 32 + flush_logic 22 + formatter 15 + context_writer 10 + diff_collector 6 + conflict_detector 19 + hooks 11 + 기타)
- E2E Live: 2 시나리오 (nightmare + branch_conflict) — `claude` CLI 필요
- Statistical AB: `--student-n N --naive-m M --agent-model MODEL` pytest 옵션
- **Deprecated scaffolds**: simple/multistage/complex — Overmind 효과 측정 불가로 레지스트리에서 제거 (파일 참고용 보존)

**Docs**:
- `docs/prd.md` — PRD
- `docs/setup-guide.md` — 플러그인 설치 가이드
- `docs/research/overmind-research.md` — 아키텍처 연구 (v2.3)
- `docs/design/phase1-design.md` — Phase 1 설계 스펙
- `docs/plans/phase1-implementation.md` — Phase 1 구현 플랜 (11 tasks)

### Statistical AB 벤치마크 인사이트

단계 수보다 **문제의 복잡도**가 Overmind 효과를 결정:
- 에러 메시지가 솔루션을 직접 가리키면 LLM이 Overmind 없이도 풀어버림
- 상호의존성, misleading errors, 다단계 추론이 필요한 트랩이어야 차이 발생
- **nightmare** scaffold: Student 23% 빠름, 33% vs 0% 성공 (Pioneer 전문가 프롬프트 전략)
- **branch_conflict** scaffold: cross-branch intent/discovery 공유 검증 (feat/auth ↔ feat/api)
- 벤치마크 상세: `docs/benchmark-ab-test.md`

**Deprecated scaffolds** (simple, multistage, complex): Overmind 효과 측정 불가로 레지스트리에서 제거. 파일은 참고용 보존.

### AB Scaffold 설계 기준 (새 scaffold 추가 시 필수)

새 AB test scaffold는 아래 조건을 **모두** 충족해야 함. 하나라도 미충족 시 Overmind 효과 측정 불가:
1. **Misleading error**: 에러 메시지 ≠ 실제 원인 (LLM이 에러만 보고 못 풀어야 함)
2. **Cross-file 의존성**: 단일 파일 수정으로 해결 불가 (최소 2개 파일 연동)
3. **누적/상호배타 제약**: A→B→C 순서 의존 또는 상호 배타 조건 (port 충돌, 토큰 포맷 등)
4. **정량 측정 가능**: server_run_attempts, proactive_config_fix, success_rate 등 명확한 메트릭 차이 예상
5. **소스 코드 복잡도**: 검증 로직이 충분히 복잡해야 함 (LLM이 소스를 읽고 한번에 파악 불가). 300줄 이하 단일 파일은 haiku가 즉시 해독 → Pioneer 지식 불필요
6. **순차 캐스케이드**: 트랩이 동시에 노출되면 안 됨. fix T1 → reveals T2 구조여야 Pioneer의 순차적 발견이 가치를 가짐

**Deprecated scaffolds 교훈**: microservices(소스 300줄, 동시 에러 노출)에서 Pioneer context가 Student를 오히려 방해 (Naive 2배 나음). 소스 복잡도 + 순차 캐스케이드가 없으면 Overmind context는 해로울 수 있음.

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

# Tests (server 95 + scaffold 11 + plugin 122)
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
| `server/tests/fixtures/ab_scaffolds/` | AB test scaffold 모듈 — active: nightmare, branch_conflict (deprecated: simple, multistage, complex, microservices) |
| `server/tests/fixtures/ab_runner.py` | 공통 agent runner + 통계 분석 |
| `plugin/tests/` | Plugin 테스트 (api_client, formatter, flush, conflict_detector, hooks) |

## Conventions

- **인코딩: UTF-8** — 모든 Python(`.py`) 및 Node/JS(`.js`, `.ts`) 파일은 반드시 UTF-8로 작성. subprocess 호출 시 `encoding="utf-8"` 명시
- Line endings: LF (소스), CRLF (batch) — `.gitattributes`에서 관리
- `core.autocrlf = false`
- 커밋 메시지: conventional commits (feat/fix/refactor/chore/docs)
- 한글 사용 가능 (PRD, 연구문서, 이벤트 데이터 등)

## Design Principles

- **SOLID 원칙 준수**: 단일 책임, 개방-폐쇄, 리스코프 치환, 인터페이스 분리, 의존성 역전을 지킨다.
- **지속 가능한 프로젝트**: 유지보수성을 최우선으로 고려한다. 당장 동작하는 코드보다 오래 유지할 수 있는 코드를 작성한다.
- **인터페이스 우선**: 구현체를 교체할 수 있도록 Protocol/ABC로 계약을 먼저 정의한다.
- **테스트가 regression guard**: 기존 테스트가 깨지지 않는 범위에서 리팩토링한다.
