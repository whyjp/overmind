# Phase 2-B (Part 1): `.claude/overmind-context.md` 동기화

**Date**: 2026-03-27
**Status**: Approved

## 배경

현재 Overmind의 레슨 전달은 SessionStart의 systemMessage에 의존한다. 이 방식은 즉시성은 좋지만, 세션이 길어지면 잊혀지고 compaction 후에도 복원되지 않는다.

`.claude/overmind-context.md` 파일을 도입하여, 훅이 pull한 팀 레슨을 프로젝트 로컬 파일로 유지한다. Claude Code는 CLAUDE.md 참조를 통해 이 파일을 세션 전체에 걸쳐 인식한다.

## 설계 원칙

- SessionStart 1회 갱신만 (PreToolUse는 기존 systemMessage 유지)
- 이벤트 없으면 기존 context.md 건드리지 않음 (stale 방지 없이 보존)
- TTL은 서버에 위임 (클라이언트 TTL 불필요, YAGNI)
- CLAUDE.md 직접 수정 안 함 — 한 줄 참조만 사용자가 수동 추가

## 1. context_writer.py

신규 파일: `plugin/scripts/context_writer.py`

### write_context_file(events, output_path)

pull된 이벤트를 타입별로 그룹핑해서 markdown 파일로 작성.

**그룹핑 순서** (중요도 순): corrections → decisions → discoveries → changes → broadcasts

**각 줄 포맷**: `- {summary or result} ({user}, {date}, scope: {scope})`
- summary가 있으면 summary 사용, 없으면 result
- scope 없으면 scope 부분 생략
- ts에서 날짜만 추출 (T 앞까지)

**빈 그룹은 생략** — corrections이 없으면 `## Corrections` 섹션을 안 씀.

**출력 예시:**

```markdown
# Overmind Team Context
> Auto-synced at session start. Do not edit manually.
> Last sync: 2026-03-27T12:00:00Z | Events: 5

## Corrections
- Use argon2 instead of bcrypt (dev_a, 2026-03-27, scope: src/auth/*)
- Fix memory leak in connection pool (dev_b, 2026-03-27, scope: src/db/*)

## Decisions
- All API endpoints must validate input with Pydantic (dev_b, 2026-03-27, scope: src/api/*)

## Discoveries
- Redis v3 pub/sub has memory leak under load (dev_a, 2026-03-27, scope: src/services/*)
```

### delete_context_file_if_exists(output_path)

파일이 존재하면 삭제. 명시적 정리용 (db_cleanup purge 후 등).

## 2. SessionStart 훅 변경

`plugin/hooks/on_session_start.py` 수정:

### 현재 동작:
1. pull → systemMessage 출력

### 변경 후:
1. pull
2. 이벤트 있으면:
   - `.claude/overmind-context.md` 생성/덮어쓰기 (context_writer 호출)
   - systemMessage 출력 (기존 유지)
3. 이벤트 없으면:
   - context.md 건드리지 않음 (기존 파일 보존)
   - 조용히 종료

### context.md 경로

`Path.cwd() / ".claude" / "overmind-context.md"`

훅은 프로젝트 루트에서 실행되므로 `cwd()`가 프로젝트 루트. `.claude/` 디렉토리가 없으면 생성.

## 3. .gitignore

`.gitignore`에 추가:

```
# Overmind context sync (local cache, not shared via git)
.claude/overmind-context.md
```

## 4. 설치 가이드 업데이트

`docs/setup-guide.md`에 추가:

```markdown
## 팀 컨텍스트 활성화 (선택)

프로젝트 CLAUDE.md에 다음 한 줄을 추가하면, Overmind이 동기화한 팀 규칙이 세션 전체에 지속됩니다:

    - 팀 동기화 규칙은 .claude/overmind-context.md를 참고하라
```

## 5. 테스트 전략

| 테스트 | 내용 |
|--------|------|
| `plugin/tests/test_context_writer.py::test_writes_grouped_by_type` | corrections/decisions/discoveries 그룹핑 확인 |
| `plugin/tests/test_context_writer.py::test_empty_groups_omitted` | 빈 타입 섹션 생략 확인 |
| `plugin/tests/test_context_writer.py::test_uses_summary_over_result` | summary 필드 우선 사용 확인 |
| `plugin/tests/test_context_writer.py::test_scope_omitted_when_none` | scope 없는 이벤트 포맷 확인 |
| `server/tests/scenarios/test_hooks_e2e.py::test_session_start_creates_context_file` | SessionStart 후 context.md 존재 + 내용 검증 |

## 6. 변경 파일 요약

| 변경 | 파일 |
|------|------|
| 신규 | `plugin/scripts/context_writer.py` |
| 신규 | `plugin/tests/test_context_writer.py` |
| 수정 | `plugin/hooks/on_session_start.py` |
| 수정 | `.gitignore` |
| 수정 | `docs/setup-guide.md` |
| 수정 | `server/tests/scenarios/test_hooks_e2e.py` |
