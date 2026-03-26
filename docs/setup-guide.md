# Overmind Plugin 설치 가이드

Claude Code 에이전트 간 메모리를 실시간 동기화하는 Overmind 플러그인을 프로젝트에 설치합니다.

## 사전 요구사항

- Python 3.11+
- Claude Code CLI
- Overmind 서버 실행 중 (`http://localhost:7777`)

## 방법 1: 플러그인 마켓플레이스 (권장)

GitHub에서 직접 설치합니다.

```bash
# 마켓플레이스 등록
/plugin marketplace add whyjp/overmind

# 플러그인 설치
/plugin install overmind-plugin
```

설치 시 hooks, MCP, skills, commands가 한 번에 설정됩니다.

## 방법 2: --plugin-dir (로컬 개발/테스트)

overmind 저장소를 클론한 후:

```bash
cd your-project
claude --plugin-dir /path/to/overmind/plugin
```

영구 설정하려면 프로젝트의 `.claude/settings.local.json`:

```json
{
  "plugins": ["/path/to/overmind/plugin"]
}
```

## 방법 3: 수동 설정

### 1. MCP 서버 연결

```bash
claude mcp add overmind --transport http http://localhost:7777/mcp/
```

### 2. Hooks 설정

`.claude/settings.local.json`에 추가 (`PLUGIN_DIR`을 실제 경로로 교체):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "python PLUGIN_DIR/hooks/on_session_start.py",
        "timeout": 5000
      }
    ],
    "SessionEnd": [
      {
        "type": "command",
        "command": "python PLUGIN_DIR/hooks/on_session_end.py",
        "timeout": 5000
      }
    ],
    "PreToolUse": [
      {
        "type": "command",
        "matcher": "^(Write|Edit)$",
        "command": "python PLUGIN_DIR/hooks/on_pre_tool_use.py",
        "timeout": 3000
      }
    ]
  }
}
```

## 환경변수 (선택)

기본값이 있으므로 대부분 설정 불필요합니다.

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `OVERMIND_URL` | `http://localhost:7777` | 서버 주소 변경 시 |
| `OVERMIND_USER` | 시스템 `USER`/`USERNAME` | 에이전트 식별자 오버라이드 |
| `OVERMIND_REPO_ID` | `git remote get-url origin`에서 자동 추출 | git 없는 환경 |

## 동작 확인

### 서버 상태

```bash
curl http://localhost:7777/api/repos
```

### 플러그인 동작

1. Claude Code 세션 시작 → `Overmind: N team events since last session:` 확인
2. 수동 push 후 pull 확인:

```bash
curl -X POST http://localhost:7777/api/memory/push \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "YOUR_REPO_ID",
    "user": "test_user",
    "events": [{
      "id": "verify_001",
      "type": "discovery",
      "ts": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
      "result": "Overmind plugin verification test"
    }]
  }'
```

3. 파일 편집 시도 → PreToolUse 훅이 관련 이벤트를 pull

### 대시보드

`http://localhost:7777/dashboard` → repo 선택 → 이벤트 흐름 시각화

## 2-에이전트 교차 테스트

터미널 2개에서 동일 프로젝트, 서로 다른 유저로 실행:

```bash
# 터미널 A
OVERMIND_USER=agent_a claude

# 터미널 B
OVERMIND_USER=agent_b claude
```

Agent A 작업 → 세션 종료 → Agent B 세션 시작 시 Agent A의 이벤트가 pull됩니다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| Hook 출력 없음 | 서버 미실행 | `curl localhost:7777/api/repos` 확인 |
| MCP 500 에러 | lifespan 미전달 | 서버 최신 버전 확인 (main.py lifespan 수정) |
| MCP 307 → 404 | 경로 불일치 | MCP URL을 `http://localhost:7777/mcp/`로 (trailing slash) |
| `repo_id` null | git remote 미설정 | `OVERMIND_REPO_ID` 환경변수 설정 |
| Python not found | PATH에 python 없음 | `python3`로 변경 또는 절대 경로 사용 |

## 제거

```bash
# 마켓플레이스 설치 제거
/plugin uninstall overmind-plugin

# 수동 설치 제거
claude mcp remove overmind
# .claude/settings.local.json에서 hooks 섹션 삭제
```
