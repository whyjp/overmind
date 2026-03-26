# Overmind Plugin 설치 가이드

프로젝트별로 Overmind 플러그인을 설치하여 Claude Code 에이전트 간 메모리를 동기화합니다.

## 사전 요구사항

- Python 3.11+
- Overmind 서버 실행 중 (`http://localhost:7777`)
- Claude Code CLI

## 설치 (프로젝트별)

대상 프로젝트의 루트 디렉토리에서 진행합니다.

### 1. MCP 서버 연결

```bash
claude mcp add overmind --transport http http://localhost:7777/mcp
```

이 명령은 프로젝트 루트에 `.mcp.json`을 생성합니다:

```json
{
  "mcpServers": {
    "overmind": {
      "type": "http",
      "url": "http://localhost:7777/mcp"
    }
  }
}
```

### 2. Hooks 설정

프로젝트의 `.claude/settings.local.json`에 hooks를 추가합니다. `PLUGIN_DIR`은 overmind 플러그인 디렉토리의 **절대 경로**로 교체하세요.

```bash
mkdir -p .claude
```

`.claude/settings.local.json`:

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

> **Windows 예시**: `PLUGIN_DIR` → `D:/github/overmind/plugin`
> **Mac/Linux 예시**: `PLUGIN_DIR` → `/home/user/overmind/plugin`
>
> 경로 구분자는 `/` (forward slash)를 사용하세요.

### 3. 환경변수 (선택)

기본값이 있으므로 대부분 설정 불필요합니다.

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `OVERMIND_URL` | `http://localhost:7777` | 서버 주소 변경 시 |
| `OVERMIND_USER` | 시스템 `USER`/`USERNAME` | 에이전트 식별자 오버라이드 |
| `OVERMIND_REPO_ID` | `git remote get-url origin`에서 자동 추출 | git 없는 환경 |

## 동작 확인

### 서버 상태 확인

```bash
curl http://localhost:7777/api/repos
```

빈 배열 `[]` 또는 기존 repo 목록이 나오면 서버 정상.

### 플러그인 동작 확인

1. 대상 프로젝트에서 Claude Code 세션 시작
2. 세션 시작 시 `Overmind: N team events since last session:` 메시지 확인 (이벤트가 없으면 출력 없음 — 정상)
3. 다른 터미널에서 수동 push:

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

4. Claude Code 세션에서 파일 편집 시도 → PreToolUse 훅이 관련 이벤트를 pull

### 대시보드 확인

브라우저에서 `http://localhost:7777/dashboard` → repo 선택 → 이벤트 흐름 시각화

## 2-에이전트 교차 테스트

터미널 2개를 열고 동일 프로젝트에서 서로 다른 유저로 Claude Code를 실행합니다.

**터미널 A:**
```bash
OVERMIND_USER=agent_a claude
```

**터미널 B:**
```bash
OVERMIND_USER=agent_b claude
```

Agent A의 세션에서 작업 → 세션 종료 → Agent B의 세션 시작 시 Agent A의 이벤트가 pull됩니다.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| Hook 출력 없음 | 서버 미실행 | `curl localhost:7777/api/repos` 확인 |
| `repo_id` null | git remote 미설정 | `OVERMIND_REPO_ID` 환경변수 설정 |
| Python not found | PATH에 python 없음 | `python3`로 변경 또는 절대 경로 사용 |
| 타임스탬프 파싱 에러 | `+`가 URL 인코딩 안 됨 | api_client.py 최신 버전 확인 (urlencode 수정) |

## 제거

```bash
# MCP 서버 제거
claude mcp remove overmind

# Hooks 제거: .claude/settings.local.json에서 hooks 섹션 삭제
```
