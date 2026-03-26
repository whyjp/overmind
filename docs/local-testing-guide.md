# Overmind 로컬 테스트 가이드

GitHub push 없이 로컬에서 다자간 테스트하는 방법.

## 준비

### 1. 서버 실행

```bash
cd D:/github/overmind/server
uv sync --all-extras
uv run python -m overmind.main
```

서버: `http://localhost:7777` / 대시보드: `http://localhost:7777/dashboard`

### 2. 기존 데이터 초기화 (선택)

이전 테스트 데이터를 지우고 싶다면:

```bash
# 현황 확인
python server/scripts/db_cleanup.py status

# 전체 초기화
rm -rf server/data/
```

## 다자간 테스트

### 방법 A: 같은 프로젝트에서 2개 에이전트

하나의 프로젝트 폴더에서 터미널 2개를 엽니다.

**터미널 1 (agent_a):**

```powershell
# PowerShell
cd D:/github/your-project
$env:OVERMIND_USER="agent_a"; claude --plugin-dir D:/github/overmind/plugin
```

```bash
# bash
cd D:/github/your-project
OVERMIND_USER=agent_a claude --plugin-dir D:/github/overmind/plugin
```

**터미널 2 (agent_b):**

```powershell
# PowerShell
cd D:/github/your-project
$env:OVERMIND_USER="agent_b"; claude --plugin-dir D:/github/overmind/plugin
```

```bash
# bash
cd D:/github/your-project
OVERMIND_USER=agent_b claude --plugin-dir D:/github/overmind/plugin
```

### 방법 B: 서로 다른 프로젝트에서 (같은 repo)

같은 git remote를 공유하는 2개 폴더라면 repo_id가 동일하므로 자동 연결됩니다.

```bash
# 터미널 1
cd D:/github/project-clone-1
OVERMIND_USER=agent_a claude --plugin-dir D:/github/overmind/plugin

# 터미널 2
cd D:/github/project-clone-2
OVERMIND_USER=agent_b claude --plugin-dir D:/github/overmind/plugin
```

### 방법 C: git repo가 아닌 폴더에서

`OVERMIND_REPO_ID`로 수동 지정합니다.

```powershell
# PowerShell
$env:OVERMIND_USER="agent_a"; $env:OVERMIND_REPO_ID="test/local-project"; claude --plugin-dir D:/github/overmind/plugin
```

```bash
# bash
OVERMIND_USER=agent_a OVERMIND_REPO_ID=test/local-project claude --plugin-dir D:/github/overmind/plugin
```

두 에이전트가 같은 `OVERMIND_REPO_ID`를 사용하면 연결됩니다.

## 테스트 시나리오

### 시나리오 1: 기본 push-pull

1. agent_a 세션에서 작업 수행
2. agent_a 세션 종료 (`/exit` 또는 Ctrl+C)
3. agent_b 세션 시작 → `[OVERMIND] Team context from other agents...` 확인

### 시나리오 2: MCP 수동 push → 다른 에이전트가 pull

agent_a 세션에서:
```
"이 발견을 팀에 공유해줘: bcrypt 대신 argon2를 사용해야 함"
→ Claude가 overmind_broadcast 또는 overmind_push 호출
```

agent_b 세션 시작 → RULES 섹션에 해당 내용 표시

### 시나리오 3: PreToolUse 차단 테스트

1. agent_a에서 urgent correction push:
```
"팀에 긴급 공유해줘: src/deploy/ 파일은 절대 수정하지 말 것"
→ overmind_broadcast(priority="urgent", scope="src/deploy/*")
```

2. agent_b에서 해당 파일 수정 시도:
```
"src/deploy/config.sh 수정해줘"
→ PreToolUse 훅이 차단 → "OVERMIND BLOCK" 메시지
```

### 시나리오 4: scope 기반 선택적 pull

1. agent_a가 `src/auth/` 관련 이벤트 push
2. agent_b가 `src/auth/login.ts` 편집 시도 → PreToolUse가 관련 이벤트 표시
3. agent_b가 `src/utils/helper.ts` 편집 시도 → 무관한 scope이므로 출력 없음

## 서버 없이 curl로 데이터 주입

에이전트를 실행하지 않고도 서버에 직접 이벤트를 넣을 수 있습니다:

```bash
# Push
curl -X POST http://localhost:7777/api/memory/push \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "test/local-project",
    "user": "manual_tester",
    "events": [{
      "id": "test_001",
      "type": "correction",
      "ts": "2026-03-27T00:00:00Z",
      "result": "bcrypt is slow, use argon2 instead",
      "files": ["src/auth/hash.ts"],
      "priority": "normal"
    }]
  }'

# Urgent broadcast
curl -X POST http://localhost:7777/api/memory/broadcast \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "test/local-project",
    "user": "admin",
    "message": "DO NOT modify deploy scripts",
    "priority": "urgent",
    "scope": "src/deploy/*"
  }'

# Pull 확인
curl "http://localhost:7777/api/memory/pull?repo_id=test/local-project"

# 대시보드에서 시각화
# http://localhost:7777/dashboard → test/local-project 선택
```

## 트러블슈팅

| 증상 | 확인 |
|------|------|
| 세션 시작 시 Overmind 메시지 없음 | 서버 실행 중? `curl localhost:7777/api/repos` |
| repo_id가 잘못됨 | `git remote get-url origin` 확인, 또는 `OVERMIND_REPO_ID` 설정 |
| 두 에이전트가 서로 안 보임 | 같은 `OVERMIND_REPO_ID` 사용 중인지 확인 |
| Hook 에러 | `--plugin-dir` 경로가 정확한지, Python이 PATH에 있는지 |
| MCP 연결 실패 | 서버 로그에서 `/mcp/` 요청 확인 |

## 영구 설정 (매번 --plugin-dir 안 치려면)

대상 프로젝트에 `.claude/settings.local.json` 생성:

```json
{
  "plugins": ["D:/github/overmind/plugin"]
}
```

이후 그냥 `claude`만 실행하면 됩니다. 유저명만 환경변수로:

```powershell
$env:OVERMIND_USER="agent_a"; claude
```
