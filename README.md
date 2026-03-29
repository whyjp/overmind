# Overmind

Distributed memory synchronization for Claude Code — share knowledge, process, and context across independent agents and developers in real-time.

> *StarCraft의 Overmind(초월체)처럼, 각 Claude 인스턴스가 물리적으로 별개이되 동일한 memory pool을 참조하는 상태를 유지합니다.*

## What it does

- **과정 공유**: 결론만이 아닌 시도 → 실패 → correction → 선택의 전체 과정을 동기화
- **사전 차단**: 한 에이전트의 삽질 결과가 다른 에이전트의 사전 방어막이 됨
- **다형성 감지**: 같은 코드 영역에 서로 다른 intent가 공존할 때 감지 및 고지
- **실시간 broadcast**: 긴급 변경사항을 모든 에이전트에게 즉시 전파

## Quick Start

### 1. Server 실행

```bash
cd server
uv sync --all-extras
uv run python -m overmind.main
```

서버가 `http://localhost:7777`에서 시작됩니다.

### 2. Plugin 설치 (GitHub에서 한 번에)

대상 프로젝트의 Claude Code 세션에서:

```
/plugin marketplace add whyjp/overmind
/plugin install overmind-plugin
```

이 한 번의 설치로 **hooks + MCP + skills + commands**가 모두 설정됩니다.

| 자동 설정 항목 | 내용 |
|-------------|------|
| **Hooks** | SessionStart(pull), PostToolUse(변경 누적+push), PreToolUse(scope 경고/차단), SessionEnd(잔여 flush) |
| **MCP** | overmind_push, overmind_pull, overmind_broadcast 도구 |
| **Skills** | overmind-broadcast, overmind-report |
| **Commands** | /overmind:broadcast |

### 3. 확인

```bash
# 서버 상태
curl http://localhost:7777/api/repos

# 대시보드
# http://localhost:7777/dashboard
```

### 4. 2-에이전트 교차 테스트

터미널 2개에서 동일 프로젝트, 서로 다른 유저로 실행:

```bash
# 터미널 A
OVERMIND_USER=agent_a claude

# 터미널 B
OVERMIND_USER=agent_b claude
```

Agent A 작업 → 세션 종료 → Agent B 세션 시작 시 Agent A의 이벤트가 자동 pull됩니다.

## A/B Benchmark: Cross-Model Knowledge Transfer

**똑똑한 모델(sonnet)의 해결 과정이 Overmind를 통해 저렴한 모델(haiku)에게 자동 전파되어, 비용 효율적으로 팀 전체 성과를 끌어올린다.**

Pioneer(sonnet) → Student(haiku+Overmind) vs Naive(haiku, 대조군). 동일한 프롬프트, 모델 차이만으로 Overmind의 가치를 증명.

### Nightmare Scaffold (5트랩, 4파일, Pioneer=sonnet, Student/Naive=haiku)

| 지표 | Pioneer(sonnet) | Student(haiku+OM) | Naive(haiku) | Student vs Naive |
|------|:---:|:---:|:---:|:---:|
| **성공률** | 100% | **100%** | **50%** | **2배** |
| **서버 실행 횟수** | 2 | **8** | 13.5 | **-41%** |
| **config 수정 횟수** | 4 | **9.5** | 12 | **-21%** |

### Branch-Conflict Scaffold (3트랩, cross-branch, Pioneer=sonnet)

| 지표 | Pioneer(sonnet) | Student(haiku+OM) | Naive(haiku) | Student vs Naive |
|------|:---:|:---:|:---:|:---:|
| **성공률** | 100% | **100%** | 100% | 동일 |
| **서버 실행 횟수** | 1 | **3.5** | 5 | **-30%** |
| **config 수정 횟수** | 2 | **3** | 4 | **-25%** |

### 왜 이 벤치마크가 유효한가

- **프롬프트 조작 없음** — Pioneer도 Student/Naive와 동일한 프롬프트 사용
- **모델 차이만** — sonnet이 자연스럽게 더 나은 해결 과정을 생성
- **자동 전파** — Overmind Plugin이 Pioneer의 시행착오를 자동 push, Student가 SessionStart에서 자동 pull
- **공정한 비교** — Student와 Naive는 동일 모델, 동일 프롬프트, Overmind 연결만 다름

### Overmind가 전달하는 것

```
[OVERMIND] Team context from other agents on this repo.

TEAMMATE CHANGES — What other agents changed (with diffs):
- Modified config.toml (1 file)
  Diff: +[server]\n+host = "localhost"\n+port = 3000\n+env = "development"
  (by agent_pioneer)
```

> Formatter는 **사실만 전달**한다. 에이전트가 자연스럽게 판단하고 활용.

상세 결과: [`docs/benchmark-ab-test.md`](docs/benchmark-ab-test.md)

실행:
```bash
cd server

# Nightmare: Pioneer=sonnet, Student/Naive=haiku
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k nightmare --student-n 2 --naive-m 2 \
  --agent-model haiku --pioneer-model sonnet

# Branch-Conflict: cross-branch knowledge transfer
uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k branch_aware --student-n 2 --naive-m 2 \
  --agent-model haiku --pioneer-model sonnet
```

---

## How it works

### Plugin Hook 동작

| 시점 | 동작 |
|------|------|
| **세션 시작** | 팀 이벤트를 pull → RULES/FIXES/CONTEXT/ANNOUNCEMENTS로 분류 → Claude에 지시형 프롬프트 주입 |
| **파일 수정 후** | 변경 파일을 state에 누적 → 개수/시간/스코프 전환 시 diff-enriched 이벤트를 batch push |
| **파일 수정 전** | scope 관련 이벤트 pull → urgent correction이면 **편집 차단**, 그 외 경고 |
| **세션 종료** | 잔여 pending changes flush push |

### Architecture

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
│ MCP tool            │── MCP ───→│ /mcp/ endpoint       │
└─────────────────────┘            │                      │
각 Claude Code 인스턴스에 1개씩       │ /dashboard           │
                                   └──────────────────────┘
                                   프로젝트당 1개 (공유)
```

## Event Types

| Type | 의미 | 예시 |
|------|------|------|
| `correction` | 에러 → 해결 과정 | `.env 설정 누락 → 추가로 해결` |
| `decision` | 대안 검토 후 선택 | `JWT vs OAuth2 → OAuth2+PKCE 채택` |
| `discovery` | 새로 발견한 사실 | `JSONB GIN 인덱스 성능 이슈` |
| `change` | 파일 구조 변경 | `모듈 추가/삭제/리팩토링` |
| `broadcast` | 긴급 전파 | `API 스키마 변경됨` |

## Usage

### MCP Tools (Claude Code 세션에서 자연어 사용)

```
"이 변경사항을 팀에 알려줘"     → overmind_broadcast 호출
"팀 최근 활동 보여줘"          → overmind_pull 호출
"auth 영역 관련 이력 확인해줘"  → overmind_pull(scope="src/auth/*")
```

### Slash Command

```
/overmind:broadcast "API 스키마 v2로 변경됨"
```

### Dashboard

`http://localhost:7777/dashboard`:

- **Overview**: push/pull 통계, 이벤트 타입 분포, 이벤트 피드
- **Graph**: Flow View (시간순 이벤트 흐름 + ghost dots) / Agent View / Scope View
- **Timeline**: 에이전트별 swimlane 타임라인, broadcast 수직선

---

## Manual Setup (Plugin 마켓플레이스 대신 수동 설치)

마켓플레이스 설치가 안 되는 경우 수동으로 설정합니다.

### --plugin-dir (로컬 개발/테스트)

```bash
claude --plugin-dir /path/to/overmind/plugin
```

영구 설정:

```json
// .claude/settings.local.json
{ "plugins": ["/path/to/overmind/plugin"] }
```

### MCP 수동 연결

```bash
claude mcp add overmind --transport http http://localhost:7777/mcp/
```

팀원이 다른 머신에서 접속하는 경우:

```bash
claude mcp add overmind --transport http http://<서버IP>:7777/mcp/
```

### Hooks 수동 설정

`.claude/settings.local.json` (`PLUGIN_DIR`을 실제 경로로 교체):

```json
{
  "hooks": {
    "SessionStart": [{"type": "command", "command": "python PLUGIN_DIR/hooks/on_session_start.py", "timeout": 5000}],
    "SessionEnd": [{"type": "command", "command": "python PLUGIN_DIR/hooks/on_session_end.py", "timeout": 5000}],
    "PreToolUse": [{"type": "command", "matcher": "^(Write|Edit)$", "command": "python PLUGIN_DIR/hooks/on_pre_tool_use.py", "timeout": 3000}]
  }
}
```

### Environment Variables

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `OVERMIND_URL` | `http://localhost:7777` | 서버 주소 |
| `OVERMIND_USER` | 시스템 `USER`/`USERNAME` | 에이전트 식별자 |
| `OVERMIND_REPO_ID` | `git remote` 자동 추출 | git 없는 환경 |

### REST API 직접 호출

```bash
# Push
curl -X POST http://localhost:7777/api/memory/push \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "github.com/team/project", "user": "dev_a",
       "events": [{"id": "evt_001", "type": "correction",
       "ts": "2026-03-26T05:30:00Z",
       "result": ".env에 SERVICE_A_INTERNAL_URL 설정 필요",
       "files": ["src/config/env.ts"]}]}'

# Pull
curl "http://localhost:7777/api/memory/pull?repo_id=github.com/team/project&exclude_user=dev_b"

# Broadcast
curl -X POST http://localhost:7777/api/memory/broadcast \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "github.com/team/project", "user": "dev_a",
       "message": "API 스키마 v2로 변경", "priority": "urgent"}'
```

---

## Development

```bash
cd server && uv sync --all-extras

# Run tests (222+ tests)
uv run pytest tests/ -v                    # server 95 + scaffold 11
cd ../plugin && python -m pytest tests/ -v  # plugin 117

# Run server
uv run python -m overmind.main --port 7778
```

## Project Structure

```
overmind/
├── server/                    # Overmind Server
│   ├── overmind/
│   │   ├── models.py          # Pydantic models
│   │   ├── store.py           # SQLite store + scope filter
│   │   ├── api.py             # FastAPI REST endpoints
│   │   ├── mcp_server.py      # FastMCP wrapper
│   │   ├── main.py            # Entry point (REST + MCP + Dashboard)
│   │   └── dashboard/static/  # Web dashboard (D3.js)
│   └── tests/                 # pytest test suite
├── plugin/                    # Claude Code Plugin
│   ├── hooks/                 # SessionStart/End, PreToolUse
│   ├── skills/                # broadcast, report
│   ├── commands/              # /overmind:broadcast
│   └── scripts/               # api_client, formatter
└── docs/
    ├── prd.md
    ├── setup-guide.md
    ├── design/
    ├── plans/
    └── research/
        ├── overmind-research.md
        └── cross-agent-influence.md
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Server | Python 3.11+, FastAPI, FastMCP v3, Pydantic v2 |
| Storage | SQLite (aiosqlite) |
| Dashboard | Vanilla JS, D3.js v7 |
| Plugin | Python (urllib, no dependencies) |
| Tests | pytest, pytest-asyncio, httpx, FastMCP in-memory client |
