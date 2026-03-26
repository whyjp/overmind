# Overmind

Distributed memory synchronization for Claude Code — share knowledge, process, and context across independent agents and developers in real-time.

> *StarCraft의 Overmind(초월체)처럼, 각 Claude 인스턴스가 물리적으로 별개이되 동일한 memory pool을 참조하는 상태를 유지합니다.*

## What it does

- **과정 공유**: 결론만이 아닌 시도 → 실패 → correction → 선택의 전체 과정을 동기화
- **사전 차단**: 한 에이전트의 삽질 결과가 다른 에이전트의 사전 방어막이 됨
- **다형성 감지**: 같은 코드 영역에 서로 다른 intent가 공존할 때 감지 및 고지
- **실시간 broadcast**: 긴급 변경사항을 모든 에이전트에게 즉시 전파

## Architecture

```
Overmind Plugin (클라이언트)          Overmind Server
┌─────────────────────┐            ┌──────────────────────┐
│ Hook → push         │── POST ──→│ /api/memory/push     │
│                     │            │   JSONL store        │
│ Hook → pull         │── GET ───←│ /api/memory/pull     │
│   → Claude 해석     │            │   scope filter       │
│                     │            │                      │
│ Skill → broadcast   │── POST ──→│ /api/memory/broadcast│
│                     │            │   priority 관리      │
│                     │            │                      │
│ MCP tool            │── MCP ───→│ /mcp endpoint        │
└─────────────────────┘            │                      │
각 Claude Code 인스턴스에 1개씩       │ /dashboard           │
                                   └──────────────────────┘
                                   프로젝트당 1개 (공유)
```

## Quick Start

### 1. Server 실행

```bash
cd server
uv sync --all-extras
uv run python -m overmind.main
```

서버가 `http://localhost:7777`에서 시작됩니다.

| Endpoint | URL |
|----------|-----|
| REST API | `http://localhost:7777/api/...` |
| MCP | `http://localhost:7777/mcp` |
| Dashboard | `http://localhost:7777/dashboard` |

**옵션:**

```bash
uv run python -m overmind.main --host 0.0.0.0 --port 7777 --data-dir ./data
```

- `--host`: 바인드 호스트 (기본: `0.0.0.0`, 팀 공유 시 외부 접근 가능)
- `--port`: 포트 (기본: `7777`)
- `--data-dir`: JSONL 데이터 저장 경로 (기본: `./data`)

### 2. Claude Code에 MCP 서버 연결

각 개발자/에이전트의 Claude Code에서:

```bash
claude mcp add overmind --transport http http://localhost:7777/mcp
```

팀원이 다른 머신에서 접속하는 경우:

```bash
claude mcp add overmind --transport http http://<서버IP>:7777/mcp
```

연결 확인:

```bash
claude mcp list
# overmind: http://localhost:7777/mcp (connected)
```

### 3. Plugin 설치 (자동 push/pull 훅)

```bash
# 로컬 테스트 모드
claude --plugin-dir ./plugin

# 또는 플러그인 디렉토리를 직접 지정
```

**Plugin 환경변수 설정** (선택):

```bash
# 서버 URL (기본: http://localhost:7777)
export OVERMIND_URL=http://192.168.1.100:7777

# 유저 식별자 (기본: 시스템 USERNAME)
export OVERMIND_USER=dev_a
```

### 4. Dashboard 확인

브라우저에서 `http://localhost:7777/dashboard` 접속:

- **Overview**: push/pull 통계, 이벤트 타입 분포, 이벤트 피드
- **Graph**: 에이전트 → 이벤트 → 스코프 3-column 관계 그래프, 다형성 감지 표시
- **Timeline**: 에이전트별 swimlane 타임라인, broadcast 수직선

## Usage

### MCP Tools (Claude Code 세션에서 직접 사용)

MCP 연결 후 Claude Code 세션에서 자연어로 사용:

```
"이 변경사항을 팀에 알려줘"     → overmind_broadcast 호출
"팀 최근 활동 보여줘"          → overmind_pull 호출
"auth 영역 관련 이력 확인해줘"  → overmind_pull(scope="src/auth/*")
```

### Plugin Hook 동작

Plugin이 설치되면 자동으로:

| 시점 | 동작 |
|------|------|
| **세션 시작** | 마지막 pull 이후 팀 이벤트를 자동 pull → Claude context에 주입 |
| **세션 종료** | 세션 중 주요 이벤트를 자동 push |
| **파일 수정 시** (Write/Edit) | 해당 파일 scope의 팀 이벤트를 선제적으로 pull → 사전 차단 고지 |

### Slash Command

```
/overmind:broadcast "API 스키마 v2로 변경됨"
```

### REST API 직접 호출

```bash
# Push events
curl -X POST http://localhost:7777/api/memory/push \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "github.com/team/project",
    "user": "dev_a",
    "events": [{
      "id": "evt_001",
      "type": "correction",
      "ts": "2026-03-26T14:30:00+09:00",
      "result": ".env에 SERVICE_A_INTERNAL_URL 설정 필요",
      "files": ["src/config/env.ts"],
      "process": ["ECONNREFUSED 발생", "SERVICE_A_INTERNAL_URL 미설정 확인"]
    }]
  }'

# Pull events
curl "http://localhost:7777/api/memory/pull?repo_id=github.com/team/project&exclude_user=dev_b&scope=src/config/*"

# Broadcast
curl -X POST http://localhost:7777/api/memory/broadcast \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "github.com/team/project",
    "user": "dev_a",
    "message": "API 스키마 v2로 변경",
    "priority": "urgent"
  }'
```

## Event Types

| Type | 의미 | 예시 |
|------|------|------|
| `correction` | 에러 → 해결 과정 | `.env 설정 누락 → 추가로 해결` |
| `decision` | 대안 검토 후 선택 | `JWT vs OAuth2 → OAuth2+PKCE 채택` |
| `discovery` | 새로 발견한 사실 | `JSONB GIN 인덱스 성능 이슈` |
| `change` | 파일 구조 변경 | `모듈 추가/삭제/리팩토링` |
| `broadcast` | 긴급 전파 | `API 스키마 변경됨` |

## Project Structure

```
overmind/
├── server/                    # Overmind Server
│   ├── overmind/
│   │   ├── models.py          # Pydantic models
│   │   ├── store.py           # JSONL store + scope index
│   │   ├── api.py             # FastAPI REST endpoints
│   │   ├── mcp_server.py      # FastMCP wrapper
│   │   ├── main.py            # Entry point
│   │   └── dashboard/static/  # Web dashboard (D3.js)
│   ├── tests/                 # pytest test suite
│   └── pyproject.toml
├── plugin/                    # Claude Code Plugin
│   ├── hooks/                 # SessionStart/End, PreToolUse
│   ├── skills/                # broadcast, report
│   ├── commands/              # /overmind:broadcast
│   └── scripts/api_client.py  # Shared HTTP client
└── docs/
    └── overmind-research.md   # Architecture research document
```

## Development

```bash
# Install dev dependencies
cd server && uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Run server in development
uv run python -m overmind.main --port 7778
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Server | Python, FastAPI, FastMCP, Pydantic v2 |
| Storage | File-based JSONL (Phase 2: SQLite) |
| Dashboard | Vanilla JS, D3.js v7 |
| Plugin hooks | Python (httpx) |
| Tests | pytest, pytest-asyncio, FastMCP in-memory client |
