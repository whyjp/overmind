# Phase 2-A (Part 2): Summary 생성 + Feedback 시스템

**Date**: 2026-03-27
**Status**: Approved

## 배경

Phase 2-A Part 1에서 SQLite 이관과 `?detail` 파라미터를 완료했다. Part 2는 데이터 품질의 나머지 두 축을 다룬다:

1. **Summary 생성**: push 시 `process` 필드를 요약해서 `summary` 필드 자동 채움. 초기 구현은 Mock (pass-through), 나중에 LLM으로 교체.
2. **Feedback 시스템**: 이벤트의 실제 영향력을 측정. PreToolUse deny 시 자동 `prevented_error` 기록 + MCP tool로 Claude가 능동적 피드백.

## 설계 원칙

- SOLID: SummaryGenerator Protocol로 LLM 교체 대비 (OCP, DIP)
- 확실한 시그널만 자동화: deny = prevented_error (100% 확실)
- 불확실한 시그널은 Claude 판단에 위임: MCP tool로 능동적 호출
- 기존 57 테스트 regression guard 유지

## 1. DB 스키마 변경

기존 `events` 테이블에 2개 컬럼 추가:

```sql
ALTER TABLE events ADD COLUMN summary TEXT;
ALTER TABLE events ADD COLUMN prevented_count INTEGER DEFAULT 0;
```

새 테이블:

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    user        TEXT NOT NULL,
    type        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    UNIQUE(event_id, user, type)
);

CREATE INDEX IF NOT EXISTS idx_feedback_event ON feedback(event_id);
```

`init_db()`에서 ALTER TABLE은 `PRAGMA table_info`로 컬럼 존재 체크 후 추가. feedback 테이블은 CREATE TABLE IF NOT EXISTS.

`prevented_count`를 events에 두는 이유: pull 시 정렬/필터에 활용, 매번 JOIN 피함 (denormalized).

## 2. MemoryEvent 모델 변경

```python
class MemoryEvent(BaseModel):
    # ... 기존 필드 ...
    summary: str | None = None
    prevented_count: int = 0
```

`PushEventInput.to_event()`도 동일하게 summary, prevented_count 전달.

## 3. SummaryGenerator Protocol

신규 파일: `server/overmind/summary.py`

```python
from typing import Protocol
from overmind.models import MemoryEvent

class SummaryGenerator(Protocol):
    """이벤트 요약 생성기. LLM 교체 시 이 Protocol을 구현."""
    async def generate(self, event: MemoryEvent) -> str | None: ...

class MockSummaryGenerator:
    """Pass-through: result를 그대로 반환."""
    async def generate(self, event: MemoryEvent) -> str | None:
        if not event.process:
            return None
        return event.result
```

### Push 파이프라인

```
클라이언트 → POST /api/memory/push → store.push(events)
                                        ↓
                                    for evt in events:
                                        evt.summary = await generator.generate(evt)
                                        ↓
                                    INSERT INTO events
```

- `SummaryGenerator`는 `SQLiteStore` 생성 시 주입 (DI)
- `SQLiteStore(data_dir, summary_generator=MockSummaryGenerator())`
- 나중에 LLM 교체: `LLMSummaryGenerator(api_key, model)` 구현체 주입

### summary와 detail의 관계

- `detail="full"`: 모든 필드 포함 (summary도 포함)
- `detail="summary"`: process/prompt 제외, summary 필드는 포함
- summary 필드가 None이면 클라이언트는 result를 직접 사용

## 4. Feedback API

### REST 엔드포인트

```
POST /api/memory/feedback
{
    "repo_id": "github.com/team/project",
    "event_id": "evt_abc123",
    "user": "agent_b",
    "type": "prevented_error"    // "prevented_error" | "helpful" | "irrelevant"
}

→ { "recorded": true, "prevented_count": 3 }
```

서버 동작:
1. `feedback` 테이블에 INSERT OR IGNORE (UNIQUE 제약으로 중복 방지)
2. `type == "prevented_error"` 이면 `UPDATE events SET prevented_count = prevented_count + 1`
3. 현재 `prevented_count` 반환

### Pydantic 모델

```python
class FeedbackRequest(BaseModel):
    repo_id: str
    event_id: str
    user: str
    type: Literal["prevented_error", "helpful", "irrelevant"]

class FeedbackResponse(BaseModel):
    recorded: bool
    prevented_count: int
```

### Store 메서드

```python
async def record_feedback(self, repo_id: str, event_id: str, user: str,
                           feedback_type: str) -> tuple[bool, int]:
    """Record feedback. Returns (was_new, current_prevented_count)."""
```

StoreProtocol에도 추가.

## 5. MCP Tool

```python
@mcp.tool()
async def overmind_feedback(
    repo_id: str,
    event_id: str,
    user: str,
    feedback_type: str,
) -> dict:
    """Rate a lesson's usefulness. Call after a pulled lesson
    influenced your decision (helpful) or was irrelevant."""
```

Claude가 pull된 lesson을 보고 능동적으로 호출. 훅이 아닌 Claude의 판단에 의존.

## 6. PreToolUse 자동 Feedback

`plugin/hooks/on_pre_tool_use.py`에서 deny 반환 시, 동시에 feedback API 호출:

```python
if blocking_events:
    for evt in blocking_events:
        api_post("/api/memory/feedback", {
            "repo_id": repo_id,
            "event_id": evt["id"],
            "user": current_user,
            "type": "prevented_error",
        })
    return json.dumps({"permissionDecision": "deny", ...})
```

deny가 발동하면 lesson이 실제로 위험한 행동을 막은 것 — 100% 확실한 시그널.

## 7. Report 확장

`get_repo_stats()`에 feedback 통계 추가:

```python
class ReportResponse(BaseModel):
    # ... 기존 필드 ...
    total_feedback: int          # 전체 피드백 수
    prevented_errors: int        # prevented_error 피드백 수
```

## 8. 테스트 전략

| 테스트 | 내용 |
|--------|------|
| `test_store.py::test_push_generates_summary` | push 시 summary 생성 확인 |
| `test_store.py::test_record_feedback` | feedback 기록 + prevented_count 증가 |
| `test_store.py::test_feedback_dedup` | 같은 (event_id, user, type) 중복 방지 |
| `test_api.py::test_feedback_endpoint` | POST /api/memory/feedback |
| `test_mcp.py::test_overmind_feedback` | MCP tool 호출 |
| `test_hooks_e2e.py::test_deny_sends_feedback` | PreToolUse deny 시 feedback 자동 전송 |

기존 57 테스트 + 신규 ~6개 = ~63개 목표.

## 9. 변경 파일 요약

| 변경 | 파일 |
|------|------|
| 수정 | `server/overmind/models.py` (summary, prevented_count 필드 + Feedback 모델) |
| 수정 | `server/overmind/store.py` (스키마 마이그레이션, push에 summary, record_feedback) |
| 신규 | `server/overmind/summary.py` (SummaryGenerator Protocol + MockSummaryGenerator) |
| 수정 | `server/overmind/api.py` (feedback 엔드포인트) |
| 수정 | `server/overmind/mcp_server.py` (overmind_feedback tool) |
| 수정 | `server/overmind/main.py` (SummaryGenerator DI) |
| 수정 | `plugin/hooks/on_pre_tool_use.py` (deny 시 feedback 자동 전송) |
| 수정 | 테스트 파일들 (신규 테스트 추가) |
