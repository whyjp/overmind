# Phase 2-A Part 2: Summary Generation + Feedback System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add push-time summary generation (with pluggable SummaryGenerator) and a feedback system (auto deny tracking + MCP tool) to measure lesson impact.

**Architecture:** `SummaryGenerator` Protocol with `MockSummaryGenerator` injected into `SQLiteStore` via DI. New `feedback` table + `POST /api/memory/feedback` endpoint + `overmind_feedback` MCP tool. PreToolUse hook sends automatic `prevented_error` feedback on deny.

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, FastMCP, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-27-phase2a-summary-feedback-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `server/overmind/summary.py` | SummaryGenerator Protocol + MockSummaryGenerator |
| Modify | `server/overmind/models.py` | Add summary, prevented_count to MemoryEvent; FeedbackRequest/Response models |
| Modify | `server/overmind/store.py` | Schema migration, push with summary, record_feedback method |
| Modify | `server/overmind/api.py` | POST /api/memory/feedback endpoint, report stats |
| Modify | `server/overmind/mcp_server.py` | overmind_feedback tool |
| Modify | `server/overmind/main.py` | Pass SummaryGenerator to SQLiteStore |
| Modify | `plugin/hooks/on_pre_tool_use.py` | Auto feedback on deny |
| Modify | `server/tests/test_store.py` | Summary + feedback store tests |
| Modify | `server/tests/test_api.py` | Feedback API test |
| Modify | `server/tests/test_mcp.py` | overmind_feedback MCP test |

---

### Task 1: Create SummaryGenerator Protocol + MockSummaryGenerator

**Files:**
- Create: `server/overmind/summary.py`
- Test: `server/tests/test_summary.py`

- [ ] **Step 1: Write the test**

Create `server/tests/test_summary.py`:

```python
import pytest
from overmind.models import MemoryEvent
from overmind.summary import MockSummaryGenerator


def _make_event(**kwargs) -> MemoryEvent:
    defaults = {
        "id": "evt_001", "repo_id": "github.com/test/repo", "user": "dev_a",
        "ts": "2026-03-27T10:00:00Z", "type": "correction", "result": "fixed the bug",
    }
    defaults.update(kwargs)
    return MemoryEvent(**defaults)


@pytest.mark.asyncio
class TestMockSummaryGenerator:
    async def test_returns_result_when_process_exists(self):
        gen = MockSummaryGenerator()
        evt = _make_event(process=["step1", "step2"])
        summary = await gen.generate(evt)
        assert summary == "fixed the bug"

    async def test_returns_none_when_no_process(self):
        gen = MockSummaryGenerator()
        evt = _make_event(process=[])
        summary = await gen.generate(evt)
        assert summary is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_summary.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement summary.py**

Create `server/overmind/summary.py`:

```python
"""Summary generation for Overmind events."""

from __future__ import annotations

from typing import Protocol

from overmind.models import MemoryEvent


class SummaryGenerator(Protocol):
    """Event summary generator. Implement this Protocol for LLM-based summary."""

    async def generate(self, event: MemoryEvent) -> str | None:
        """Generate a summary from event's process + result. None if not applicable."""
        ...


class MockSummaryGenerator:
    """Pass-through: returns result as summary when process exists."""

    async def generate(self, event: MemoryEvent) -> str | None:
        if not event.process:
            return None
        return event.result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_summary.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/overmind/summary.py server/tests/test_summary.py
git commit -m "feat: SummaryGenerator Protocol + MockSummaryGenerator"
```

---

### Task 2: Add summary + prevented_count to MemoryEvent model

**Files:**
- Modify: `server/overmind/models.py`

- [ ] **Step 1: Add fields to MemoryEvent**

In `server/overmind/models.py`, add to `MemoryEvent`:

```python
class MemoryEvent(BaseModel):
    """A single memory event in the Overmind system."""

    id: str
    repo_id: str
    user: str
    ts: str
    type: EventType
    result: str

    # Optional fields
    prompt: str | None = None
    files: list[str] = Field(default_factory=list)
    process: list[str] = Field(default_factory=list)
    priority: Priority = "normal"
    scope: str | None = None
    summary: str | None = None
    prevented_count: int = 0
```

- [ ] **Step 2: Add FeedbackRequest and FeedbackResponse models**

Add to `server/overmind/models.py`:

```python
FeedbackType = Literal["prevented_error", "helpful", "irrelevant"]


class FeedbackRequest(BaseModel):
    """Request body for POST /api/memory/feedback."""

    repo_id: str
    event_id: str
    user: str
    type: FeedbackType


class FeedbackResponse(BaseModel):
    """Response for POST /api/memory/feedback."""

    recorded: bool
    prevented_count: int
```

- [ ] **Step 3: Add feedback stats to ReportResponse**

Update `ReportResponse` in `server/overmind/models.py`:

```python
class ReportResponse(BaseModel):
    """Response for GET /api/report."""

    repo_id: str
    period: str
    total_pushes: int
    total_pulls: int
    unique_users: int
    events_by_type: dict[str, int]
    total_feedback: int = 0
    prevented_errors: int = 0
```

- [ ] **Step 4: Run model tests**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: all 7 PASS (existing tests unaffected — new fields have defaults)

- [ ] **Step 5: Commit**

```bash
git add server/overmind/models.py
git commit -m "feat: add summary, prevented_count, FeedbackRequest/Response models"
```

---

### Task 3: Schema migration + push with summary + record_feedback in store

**Files:**
- Modify: `server/overmind/store.py`
- Modify: `server/tests/test_store.py`

- [ ] **Step 1: Write store tests for summary and feedback**

Add to `server/tests/test_store.py`:

```python
from overmind.summary import MockSummaryGenerator


# Update the store fixture to pass summary_generator:
@pytest_asyncio.fixture
async def store(data_dir):
    s = SQLiteStore(data_dir=data_dir, summary_generator=MockSummaryGenerator())
    await s.init_db()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestSummary:
    async def test_push_generates_summary_when_process_exists(self, store):
        evt = _make_event("evt_sum_001", process=["step1", "step2"])
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].summary == "test result"

    async def test_push_no_summary_when_no_process(self, store):
        evt = _make_event("evt_sum_002", process=[])
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].summary is None


@pytest.mark.asyncio
class TestFeedback:
    async def test_record_feedback(self, store):
        evt = _make_event("evt_fb_001")
        await store.push([evt])
        was_new, count = await store.record_feedback(
            "github.com/test/repo", "evt_fb_001", "agent_b", "prevented_error"
        )
        assert was_new is True
        assert count == 1

    async def test_feedback_increments_prevented_count(self, store):
        evt = _make_event("evt_fb_002")
        await store.push([evt])
        await store.record_feedback("github.com/test/repo", "evt_fb_002", "agent_a", "prevented_error")
        await store.record_feedback("github.com/test/repo", "evt_fb_002", "agent_b", "prevented_error")
        result = await store.pull(repo_id="github.com/test/repo")
        fb_evt = next(e for e in result.events if e.id == "evt_fb_002")
        assert fb_evt.prevented_count == 2

    async def test_feedback_dedup(self, store):
        evt = _make_event("evt_fb_003")
        await store.push([evt])
        was_new1, _ = await store.record_feedback("github.com/test/repo", "evt_fb_003", "agent_a", "prevented_error")
        was_new2, _ = await store.record_feedback("github.com/test/repo", "evt_fb_003", "agent_a", "prevented_error")
        assert was_new1 is True
        assert was_new2 is False

    async def test_helpful_feedback_no_prevented_count(self, store):
        evt = _make_event("evt_fb_004")
        await store.push([evt])
        await store.record_feedback("github.com/test/repo", "evt_fb_004", "agent_a", "helpful")
        result = await store.pull(repo_id="github.com/test/repo")
        fb_evt = next(e for e in result.events if e.id == "evt_fb_004")
        assert fb_evt.prevented_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py::TestSummary tests/test_store.py::TestFeedback -v`
Expected: FAIL

- [ ] **Step 3: Update schema in store.py**

In `server/overmind/store.py`, update `_SCHEMA` to add feedback table:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    user TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    result TEXT NOT NULL,
    prompt TEXT,
    files TEXT DEFAULT '[]',
    process TEXT DEFAULT '[]',
    priority TEXT DEFAULT 'normal',
    scope TEXT,
    summary TEXT,
    prevented_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_id);
CREATE INDEX IF NOT EXISTS idx_events_repo_ts ON events(repo_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_repo_user ON events(repo_id, user);
CREATE INDEX IF NOT EXISTS idx_events_repo_scope ON events(repo_id, scope);

CREATE TABLE IF NOT EXISTS pull_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    puller TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_user TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pull_repo ON pull_log(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pull_dedup ON pull_log(repo_id, puller, event_id);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    user TEXT NOT NULL,
    type TEXT NOT NULL,
    ts TEXT NOT NULL,
    UNIQUE(event_id, user, type)
);

CREATE INDEX IF NOT EXISTS idx_feedback_event ON feedback(event_id);
"""
```

Add migration in `init_db()` after `executescript(_SCHEMA)`:

```python
    async def init_db(self) -> None:
        """Create the database connection and tables."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        # Migrate existing DBs: add columns if they don't exist
        await self._migrate_columns()

    async def _migrate_columns(self) -> None:
        """Add new columns to existing databases (idempotent)."""
        cursor = await self.db.execute("PRAGMA table_info(events)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "summary" not in columns:
            await self.db.execute("ALTER TABLE events ADD COLUMN summary TEXT")
        if "prevented_count" not in columns:
            await self.db.execute("ALTER TABLE events ADD COLUMN prevented_count INTEGER DEFAULT 0")
        await self.db.commit()
```

- [ ] **Step 4: Update SQLiteStore constructor to accept SummaryGenerator**

```python
from overmind.summary import SummaryGenerator, MockSummaryGenerator

class SQLiteStore:
    def __init__(self, data_dir: Path, summary_generator: SummaryGenerator | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "overmind.db"
        self._db: aiosqlite.Connection | None = None
        self._version: dict[str, int] = defaultdict(int)
        self._global_version: int = 0
        self._summary_generator = summary_generator or MockSummaryGenerator()
```

- [ ] **Step 5: Update push() to generate summary and store it**

Update the INSERT statement in `push()` to include summary and prevented_count:

```python
    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """INSERT new events with dedup. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0
        accepted_repos: set[str] = set()

        for evt in events:
            # Generate summary if not already set
            if evt.summary is None:
                evt.summary = await self._summary_generator.generate(evt)

            async with self.db.execute(
                """INSERT OR IGNORE INTO events
                   (id, repo_id, user, ts, type, result, prompt, files, process, priority, scope, summary, prevented_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evt.id, evt.repo_id, evt.user, evt.ts, evt.type,
                    evt.result, evt.prompt,
                    json.dumps(evt.files), json.dumps(evt.process),
                    evt.priority, evt.scope, evt.summary, evt.prevented_count,
                ),
            ) as cur:
                if cur.rowcount > 0:
                    accepted += 1
                    accepted_repos.add(evt.repo_id)
                else:
                    duplicates += 1

        if accepted > 0:
            await self.db.commit()
            self._global_version += 1
            for rid in accepted_repos:
                self._version[rid] += 1

        return accepted, duplicates
```

- [ ] **Step 6: Update _row_to_event to include summary and prevented_count**

Update `_row_to_event()` in store.py:

```python
    def _row_to_event(self, row: aiosqlite.Row, detail: DetailLevel = "full") -> MemoryEvent:
        """Convert a database row to MemoryEvent."""
        files = json.loads(row["files"]) if row["files"] else []
        if detail == "full":
            process = json.loads(row["process"]) if row["process"] else []
            prompt = row["prompt"]
        else:
            process = []
            prompt = None

        return MemoryEvent(
            id=row["id"],
            repo_id=row["repo_id"],
            user=row["user"],
            ts=row["ts"],
            type=row["type"],
            result=row["result"],
            prompt=prompt,
            files=files,
            process=process,
            priority=row["priority"],
            scope=row["scope"],
            summary=row["summary"],
            prevented_count=row["prevented_count"] or 0,
        )
```

- [ ] **Step 7: Implement record_feedback()**

Add to `SQLiteStore`:

```python
    async def record_feedback(
        self, repo_id: str, event_id: str, user: str, feedback_type: str
    ) -> tuple[bool, int]:
        """Record feedback for an event. Returns (was_new, current_prevented_count)."""
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        # Insert feedback (UNIQUE constraint prevents duplicates)
        async with self.db.execute(
            """INSERT OR IGNORE INTO feedback (repo_id, event_id, user, type, ts)
               VALUES (?, ?, ?, ?, ?)""",
            (repo_id, event_id, user, feedback_type, now_iso),
        ) as cur:
            was_new = cur.rowcount > 0

        # Increment prevented_count if type is prevented_error and feedback was new
        if was_new and feedback_type == "prevented_error":
            await self.db.execute(
                "UPDATE events SET prevented_count = prevented_count + 1 WHERE id = ?",
                (event_id,),
            )

        await self.db.commit()

        # Return current prevented_count
        cursor = await self.db.execute(
            "SELECT prevented_count FROM events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0

        return was_new, count
```

Add `record_feedback` to `StoreProtocol`:

```python
    async def record_feedback(
        self, repo_id: str, event_id: str, user: str, feedback_type: str
    ) -> tuple[bool, int]: ...
```

- [ ] **Step 8: Run tests**

Run: `cd server && uv run pytest tests/test_store.py -v`
Expected: all PASS (existing 14 + new 6 = 20)

- [ ] **Step 9: Commit**

```bash
git add server/overmind/store.py server/tests/test_store.py
git commit -m "feat: schema migration, push with summary, record_feedback"
```

---

### Task 4: Update get_repo_stats with feedback counts

**Files:**
- Modify: `server/overmind/store.py`

- [ ] **Step 1: Update get_repo_stats()**

In `get_repo_stats()`, add feedback queries after existing logic:

```python
        # Feedback stats
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM feedback WHERE repo_id = ?", (repo_id,)
        )
        total_feedback = (await cursor.fetchone())[0]

        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM feedback WHERE repo_id = ? AND type = 'prevented_error'",
            (repo_id,),
        )
        prevented_errors = (await cursor.fetchone())[0]

        return ReportResponse(
            repo_id=repo_id,
            period=period,
            total_pushes=len(rows),
            total_pulls=unique_pulls,
            unique_users=unique_users,
            events_by_type=dict(events_by_type),
            total_feedback=total_feedback,
            prevented_errors=prevented_errors,
        )
```

- [ ] **Step 2: Run report tests**

Run: `cd server && uv run pytest tests/test_api.py::TestReportEndpoint -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/overmind/store.py
git commit -m "feat: add feedback stats to get_repo_stats"
```

---

### Task 5: Wire feedback into API + update api.py and main.py

**Files:**
- Modify: `server/overmind/api.py`
- Modify: `server/overmind/main.py`
- Test: `server/tests/test_api.py`

- [ ] **Step 1: Write API test for feedback endpoint**

Add to `server/tests/test_api.py`:

```python
from overmind.models import FeedbackResponse


@pytest.mark.asyncio
class TestFeedbackEndpoint:
    async def test_feedback_prevented_error(self, client):
        # First push an event
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_fb_api_001",
                "type": "correction",
                "ts": "2026-03-27T10:00:00Z",
                "result": "dangerous pattern found",
            }],
        })
        # Send feedback
        resp = await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_api_001",
            "user": "agent_b",
            "type": "prevented_error",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["recorded"] is True
        assert body["prevented_count"] == 1

    async def test_feedback_dedup(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_fb_api_002",
                "type": "correction",
                "ts": "2026-03-27T10:00:00Z",
                "result": "test",
            }],
        })
        await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_api_002",
            "user": "agent_b",
            "type": "prevented_error",
        })
        resp = await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_api_002",
            "user": "agent_b",
            "type": "prevented_error",
        })
        body = resp.json()
        assert body["recorded"] is False
        assert body["prevented_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_api.py::TestFeedbackEndpoint -v`
Expected: FAIL — endpoint not found

- [ ] **Step 3: Add feedback endpoint to api.py**

Add imports to `server/overmind/api.py`:

```python
from overmind.models import (
    BroadcastRequest,
    BroadcastResponse,
    FeedbackRequest,
    FeedbackResponse,
    MemoryEvent,
    PullResponse,
    PushRequest,
    PushResponse,
    ReportResponse,
)
```

Add endpoint inside `create_app()`:

```python
    @app.post("/api/memory/feedback", response_model=FeedbackResponse)
    async def record_feedback(request: FeedbackRequest) -> FeedbackResponse:
        was_new, count = await store.record_feedback(
            request.repo_id, request.event_id, request.user, request.type,
        )
        return FeedbackResponse(recorded=was_new, prevented_count=count)
```

- [ ] **Step 4: Update main.py to pass SummaryGenerator**

In `server/overmind/main.py`, update imports and store creation:

```python
from overmind.store import SQLiteStore
from overmind.summary import MockSummaryGenerator
```

In `create_standalone_app()`:

```python
    store = SQLiteStore(data_dir=data_dir, summary_generator=MockSummaryGenerator())
```

In `main()`:

```python
    store = SQLiteStore(data_dir=data_dir, summary_generator=MockSummaryGenerator())
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_api.py -v`
Expected: all PASS (existing + 2 new feedback tests)

- [ ] **Step 6: Commit**

```bash
git add server/overmind/api.py server/overmind/main.py server/tests/test_api.py
git commit -m "feat: POST /api/memory/feedback endpoint + SummaryGenerator DI in main"
```

---

### Task 6: Add overmind_feedback MCP tool

**Files:**
- Modify: `server/overmind/mcp_server.py`
- Test: `server/tests/test_mcp.py`

- [ ] **Step 1: Write MCP test**

Add to `server/tests/test_mcp.py`:

```python
    async def test_overmind_feedback(self, mcp):
        async with Client(mcp) as dev_a, Client(mcp) as dev_b:
            # Push an event first
            await dev_a.call_tool("overmind_push", {
                "repo_id": "github.com/test/repo",
                "user": "dev_a",
                "events": [{
                    "id": "evt_mcp_fb_001",
                    "type": "correction",
                    "ts": "2026-03-27T10:00:00Z",
                    "result": "dangerous pattern",
                }],
            })
            # Send feedback
            result = await dev_b.call_tool("overmind_feedback", {
                "repo_id": "github.com/test/repo",
                "event_id": "evt_mcp_fb_001",
                "user": "dev_b",
                "feedback_type": "helpful",
            })
            assert "recorded" in str(result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_mcp.py::TestMCPTools::test_overmind_feedback -v`
Expected: FAIL — tool not found

- [ ] **Step 3: Add overmind_feedback tool**

Add to `server/overmind/mcp_server.py` inside `create_mcp_server()`:

```python
    @mcp.tool()
    async def overmind_feedback(
        repo_id: str,
        event_id: str,
        user: str,
        feedback_type: str,
    ) -> dict:
        """Rate a pulled lesson's usefulness.

        Call this when a lesson you received from Overmind influenced your decision
        (feedback_type='helpful'), prevented an error (feedback_type='prevented_error'),
        or was irrelevant (feedback_type='irrelevant').

        Args:
            repo_id: Repository identifier
            event_id: The event ID to rate
            user: Your agent identifier
            feedback_type: One of "prevented_error", "helpful", "irrelevant"
        """
        was_new, count = await store.record_feedback(repo_id, event_id, user, feedback_type)
        return {"recorded": was_new, "prevented_count": count}
```

- [ ] **Step 4: Update MCP store fixture**

In `server/tests/test_mcp.py`, update the store fixture:

```python
from overmind.store import SQLiteStore
from overmind.summary import MockSummaryGenerator


@pytest_asyncio.fixture
async def store(data_dir):
    s = SQLiteStore(data_dir=data_dir, summary_generator=MockSummaryGenerator())
    await s.init_db()
    yield s
    await s.close()
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_mcp.py -v`
Expected: all 4 PASS (3 existing + 1 new)

- [ ] **Step 6: Commit**

```bash
git add server/overmind/mcp_server.py server/tests/test_mcp.py
git commit -m "feat: overmind_feedback MCP tool"
```

---

### Task 7: PreToolUse auto-feedback on deny

**Files:**
- Modify: `plugin/hooks/on_pre_tool_use.py`

- [ ] **Step 1: Add feedback call on deny**

In `plugin/hooks/on_pre_tool_use.py`, add `api_post` import and feedback call:

```python
from api_client import get_repo_id, get_user, api_get, api_post, file_to_scope
```

Update the blocking section:

```python
    if blocking_rules:
        # Send automatic feedback: these rules prevented an error
        for evt in blocking_rules:
            api_post("/api/memory/feedback", {
                "repo_id": repo_id,
                "event_id": evt["id"],
                "user": user,
                "type": "prevented_error",
            })

        reasons = [evt["result"] for evt in blocking_rules]
        reason = " | ".join(reasons)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"[OVERMIND BLOCK] Team rule for {scope}: {reason}",
            }
        }
        print(json.dumps(output))
        return
```

- [ ] **Step 2: Run hook E2E test to verify no regression**

Run: `cd server && uv run pytest tests/scenarios/test_hooks_e2e.py -v`
Expected: all 8 PASS

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/on_pre_tool_use.py
git commit -m "feat: PreToolUse auto-sends prevented_error feedback on deny"
```

---

### Task 8: Full regression run

- [ ] **Step 1: Run complete server test suite**

Run: `cd server && uv run pytest tests/ -v`
Expected: all tests PASS (~63+: 57 existing + new summary/feedback tests)

- [ ] **Step 2: Run plugin tests**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all 59 plugin tests PASS

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, Phase 2-A section, mark summary and feedback as done:

```markdown
- ~~서버 측 서머리 생성~~ ✅ (MockSummaryGenerator, LLM 교체 대비 Protocol)
- ~~피드백 점수 (relevance_score, prevented_error) 축적~~ ✅
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark Phase 2-A summary + feedback as done"
```
