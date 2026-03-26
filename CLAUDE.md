# Overmind — Project Context

## What is this?

Overmind는 복수의 독립적 Claude Code 인스턴스 간 메모리를 실시간 동기화하는 시스템이다.
두 아티팩트: **Overmind Server** (Python, FastAPI + FastMCP) + **Overmind Plugin** (Claude Code 플러그인).

## Current State: Phase 1 Complete (구현 완료, 실사용 검증 전)

### 완료된 것

**Server** (`server/`):
- Pydantic 모델, JSONL file-based store (push/pull/dedup/scope filter/TTL)
- FastAPI REST API: push, pull, broadcast, report, graph, timeline, repos
- FastMCP v3 wrapper: overmind_push, overmind_pull, overmind_broadcast
- Web dashboard: Overview (통계+이벤트피드), Graph (3-column Agent→Event→Scope), Timeline (swimlane)
- 단일 프로세스에서 REST + MCP + Dashboard 서빙 (port 7777)

**Plugin** (`plugin/`):
- Hook: SessionStart(auto pull), SessionEnd(auto push), PreToolUse(selective pull on Write/Edit)
- Skill: overmind-broadcast, overmind-report
- Command: /overmind:broadcast
- API client: httpx 기반 REST 호출, git remote → repo_id 정규화

**Tests**: 33개 전부 pass (models 7 + store 11 + api 9 + mcp 3 + scenarios 3)

**Docs**:
- `docs/prd.md` — PRD (요구사항, 성공기준, 비기능요구사항)
- `docs/research/overmind-research.md` — 아키텍처 연구 (v2.3)
- `docs/design/phase1-design.md` — Phase 1 설계 스펙
- `docs/plans/phase1-implementation.md` — Phase 1 구현 플랜 (11 tasks)

### 아직 안 된 것 (Phase 1 범위 내)

- **실사용 검증**: 실제 2인 환경에서 push/pull 사이클 검증 미완료 (Go/No-Go 판정 전)
- **Plugin 실제 설치 테스트**: `claude --plugin-dir ./plugin`으로 실제 Claude Code 세션에서 hook 동작 미검증
- **SessionEnd push 내용**: 현재 단순 "session ended" 이벤트만 push — 세션 중 실제 correction/decision 캡처 로직 미구현

### Phase 2 계획

- 서버 측 서머리 생성 (LLM API 호출)
- `?detail=lesson|summary|full` pull 파라미터
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

# MCP 연결
claude mcp add overmind --transport http http://localhost:7777/mcp
```

## Key Files

| File | Purpose |
|------|---------|
| `server/overmind/models.py` | 모든 Pydantic 모델 (MemoryEvent, PushRequest 등) |
| `server/overmind/store.py` | JSONL store 핵심 로직 (push/pull/graph/stats) |
| `server/overmind/api.py` | FastAPI REST 엔드포인트 (create_app) |
| `server/overmind/mcp_server.py` | FastMCP 도구 래퍼 (create_mcp_server) |
| `server/overmind/main.py` | 서버 진입점 (REST + MCP 동시 서빙) |
| `server/overmind/dashboard/static/` | 대시보드 HTML/CSS/JS |
| `plugin/hooks/` | Claude Code 훅 (Python 스크립트) |
| `plugin/scripts/api_client.py` | 훅용 공유 HTTP 클라이언트 |

## Conventions

- Line endings: LF (소스), CRLF (batch) — `.gitattributes`에서 관리
- `core.autocrlf = false`
- 커밋 메시지: conventional commits (feat/fix/refactor/chore/docs)
- 한글 사용 가능 (PRD, 연구문서, 이벤트 데이터 등)
