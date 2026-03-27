# P1-3: PostToolUse Push + SessionEnd 경량화 + 테스트 보강

**Date**: 2026-03-27
**Status**: Approved

## 배경

현재 SessionEnd hook이 세션 종료 시 `"Session ended by {user}"` 한 줄만 push한다. Claude Code 세션은 수시간 지속될 수 있어서 SessionEnd 시점은 너무 늦고 거칠다.

실제 correction/decision은 세션 중간에 발생하므로, push 시점을 세션 중으로 앞당겨야 한다.

장기적으로는 메모리/레슨 처리 플러그인이 모든 tool call에서 lesson을 추출하고, 그 결과를 Overmind에 push하는 파이프라인을 상정한다:

```
Tool Call → 메모리/레슨 처리 플러그인 → 구조화된 lesson → Overmind push
```

P1-3에서는 이 파이프라인의 기반 인프라를 구축한다.

## 설계

### 1. PostToolUse Hook 신규 (`on_post_tool_use.py`)

**트리거**: Write/Edit 완료 후 (hooks.json matcher: `^(Write|Edit)$`)

**동작 흐름:**

1. stdin에서 `tool_name`, `tool_input` 파싱
2. `file_path` → `file_to_scope()` 변환 (기존 PreToolUse의 함수 재사용)
3. State file에 누적:
   ```json
   {
     "last_pull_ts": "...",
     "pending_changes": [
       {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"}
     ],
     "current_scope": "src/auth/*",
     "last_push_ts": "2026-03-27T10:00:00Z"
   }
   ```

4. Flush 조건 체크 (우선순위순):
   - **개수**: `len(pending_changes) >= FLUSH_THRESHOLD` (기본값 5)
   - **시간**: `now - last_push_ts >= FLUSH_INTERVAL` (기본값 30분)
   - **스코프 전환**: `current_scope != new_scope` → 이전 scope 분만 flush (mini-SessionEnd 취급)

5. Flush 실행:
   - `pending_changes`를 scope별로 그룹핑
   - 각 scope에 대해 `change` 타입 이벤트 생성:
     ```json
     {
       "id": "auto_<uuid_hex_12>",
       "type": "change",
       "ts": "<flush 시점 ISO8601>",
       "result": "Modified src/auth/* (3 files: login.ts, oauth2.ts, jwt.ts)",
       "files": ["src/auth/login.ts", "src/auth/oauth2.ts", "src/auth/jwt.ts"],
       "scope": "src/auth/*"
     }
     ```
   - Push 후 flush된 항목을 `pending_changes`에서 제거
   - `last_push_ts` 갱신

**환경 변수 설정 가능:**
- `OVERMIND_FLUSH_THRESHOLD`: flush 개수 (기본 5)
- `OVERMIND_FLUSH_INTERVAL`: flush 간격 초 (기본 1800)

### 2. SessionEnd 경량화 (`on_session_end.py` 수정)

**변경 내용:**
- 잔여 `pending_changes`가 있으면 scope별 그룹핑 후 flush (PostToolUse와 동일 로직)
- 잔여가 없으면 아무것도 push하지 않음
- 기존 generic `"Session ended by {user}"` 이벤트 제거
- Flush 후 `pending_changes`, `current_scope`, `last_push_ts` 초기화

### 3. `file_to_scope()` 함수 이동

현재 `on_pre_tool_use.py`에 로컬 정의되어 있음 → `api_client.py`로 이동하여 3개 hook에서 공유:
- `on_pre_tool_use.py` (기존)
- `on_post_tool_use.py` (신규)
- `on_session_end.py` (수정)

### 4. Flush 공통 로직 추출

PostToolUse와 SessionEnd가 동일한 flush 로직을 사용하므로 `api_client.py`에 공통 함수 추가:

```python
def flush_pending_changes(state: dict, repo_id: str, user: str) -> dict:
    """Flush pending_changes → scope-grouped change events. Returns updated state."""
```

### 5. hooks.json 등록

```json
"PostToolUse": [{
  "hooks": [{
    "type": "command",
    "matcher": "^(Write|Edit)$",
    "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_post_tool_use.py\"",
    "timeout": 3000
  }]
}]
```

### 6. 미래 확장 포인트

`pending_changes` 항목에 `lesson` 필드 예비:

```json
{
  "file": "...", "scope": "...", "ts": "...", "action": "Edit",
  "lesson": null
}
```

메모리/레슨 처리 플러그인이 존재하면 `lesson` 필드를 채우고, flush 시:
- `lesson`이 있으면 → `correction`/`decision` 타입으로 push
- `lesson`이 없으면 → `change` 타입으로 push (현재 동작)

### 7. Push 이벤트에 "why" 포함 (Phase 2-B 연계 과제)

**배경 — A/B 테스트 결과:**

Phase 1의 file-change 이벤트(`"Modified config.toml"`)만으로는 수신 에이전트의
행동을 통계적으로 유의미하게 변화시키지 못한다 (10회 병렬 테스트, haiku).
"무엇이 바뀌었는지(what)"만 전달되고 "왜 바뀌었는지(why)"가 없기 때문이다.

```
현재 (what only):
  result: "Modified config.toml (1 file: config.toml)"
  → 수신측: "config가 수정됐구나" (행동 변화 유도 불충분)

목표 (what + why):
  result: "Missing [server] section in config.toml → added port=3000, host=0.0.0.0"
  → 수신측: "server 섹션이 없었구나, 내가 추가해야겠다" (선제적 행동 가능)
```

**접근 방법 (summary 없이, LLM 호출 없이):**

1. **git diff 기반 result 보강**: flush 시점에 `pending_changes`의 파일들에 대해
   `git diff HEAD -- <file>` 실행, diff snippet을 result에 포함
   ```python
   # build_change_events() 수정
   result = f"Modified {scope}: {diff_summary}"
   # diff_summary 예: "+[server]\n+port = 3000\n+host = '0.0.0.0'"
   ```

2. **Bash 실행 결과 캡처**: PostToolUse 직전의 Bash tool 실행에서 에러 출력이 있었다면,
   해당 에러 메시지를 `pending_changes`의 `context` 필드에 기록
   ```json
   {"file": "config.toml", "scope": "...", "context": "KeyError: 'server' in network.js"}
   ```

3. **context → result 반영**: flush 시 context가 있으면 result에 포함
   ```
   "Fixed KeyError: 'server' in network.js → added [server] section to config.toml"
   ```

**SummaryGenerator와의 관계:**
- SummaryGenerator(mock)가 비어있으면 원본 result를 그대로 유지 (no-op)
- SummaryGenerator가 LLM을 호출할 수 있으면 diff + context를 요약
- 어느 쪽이든 "why"는 git diff와 context로부터 LLM 없이 확보 가능

**우선순위:** Phase 2-B의 `overmind-context.md` sync가 완성된 후,
push 품질을 높이는 단계로 진행. A/B 테스트로 효과 검증.

## 테스트 보강

### Plugin 테스트 (`plugin/tests/` 신규 디렉토리)

| 파일 | 범위 | 방식 |
|------|------|------|
| `test_api_client.py` | `normalize_git_remote` 10+ 케이스, `file_to_scope`, `load_state`/`save_state` | 순수 함수 단위 테스트 |
| `test_formatter.py` | `format_session_start`, `format_pre_tool_use` 출력 포맷 검증 | 순수 함수 단위 테스트 |
| `test_hooks.py` | SessionStart/SessionEnd/PreToolUse/PostToolUse stdin→stdout | subprocess + env override + mock server (또는 서버 불필요 케이스) |
| `test_flush_logic.py` | 누적 로직, flush 조건(개수/시간/스코프 전환), scope 그룹핑 | 순수 함수 단위 테스트 (state dict 조작) |

### 서버 테스트 보강 (`server/tests/`)

| 파일 | 범위 | 방식 |
|------|------|------|
| `test_api.py` 확장 | concurrent push stress test | asyncio.gather로 동시 push → pull 결과 검증 |
| `scenarios/test_e2e_server.py` | 실제 서버 subprocess 기동 → HTTP 호출 | subprocess + httpx, 별도 포트 |

### 테스트 실행

```bash
# Plugin 테스트 (순수 Python, 의존성 없음)
cd plugin && python -m pytest tests/ -v

# Server 테스트 (기존)
cd server && uv run pytest tests/ -v
```

## 변경 파일 요약

| 변경 | 파일 |
|------|------|
| 신규 | `plugin/hooks/on_post_tool_use.py` |
| 수정 | `plugin/hooks/on_session_end.py` (경량화) |
| 수정 | `plugin/hooks/on_pre_tool_use.py` (`file_to_scope` 제거, import로 대체) |
| 수정 | `plugin/scripts/api_client.py` (`file_to_scope`, `flush_pending_changes` 추가) |
| 수정 | `plugin/hooks/hooks.json` (PostToolUse 등록) |
| 신규 | `plugin/tests/test_api_client.py` |
| 신규 | `plugin/tests/test_formatter.py` |
| 신규 | `plugin/tests/test_hooks.py` |
| 신규 | `plugin/tests/test_flush_logic.py` |
| 수정 | `server/tests/test_api.py` (concurrent push 추가) |
| 신규 | `server/tests/scenarios/test_e2e_server.py` |
