# Phase 2-A Part 1: SQLite Store + Detail Param — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSONL file-based store with async SQLite (aiosqlite), add `?detail=summary|full` pull parameter, and adapt the cleanup script.

**Architecture:** `StoreProtocol` defines the contract; `SQLiteStore` implements it with aiosqlite. All store methods become `async def` (except version counters). The API layer adds `detail` param to pull. Existing 53 tests serve as regression guard — interface stays identical.

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-27-phase2a-sqlite-detail-design.md`

---

### Task 1: Add aiosqlite dependency

**Files:**
- Modify: `server/pyproject.toml`

- [ ] **Step 1: Add aiosqlite to dependencies**

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0.0",
    "fastmcp>=2.0.0",
    "aiosqlite>=0.20.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `cd server && uv sync --all-extras`
Expected: aiosqlite installed successfully

- [ ] **Step 3: Commit**

```bash
git add server/pyproject.toml server/uv.lock
git commit -m "chore: add aiosqlite dependency for SQLite store"
```

---

### Task 2: Define StoreProtocol and write SQLiteStore skeleton with init_db

**Files:**
- Modify: `server/overmind/store.py`
- Test: `server/tests/test_store.py`

- [ ] **Step 1: Write test for store initialization**

Add to `server/tests/test_store.py`:

```python
import pytest
import pytest_asyncio
from overmind.models import MemoryEvent
from overmind.store import SQLiteStore


@pytest_asyncio.fixture
async def store(data_dir):
    s = SQLiteStore(data_dir=data_dir)
    await s.init_db()
    yield s
    await s.close()


def _make_event(id: str, user: str = "dev_a", repo_id: str = "github.com/test/repo",
                type: str = "correction", files: list[str] | None = None,
                ts: str = "2026-03-26T05:30:00Z", result: str = "test result",
                priority: str = "normal", process: list[str] | None = None,
                prompt: str | None = None) -> MemoryEvent:
    return MemoryEvent(
        id=id, repo_id=repo_id, user=user, ts=ts, type=type,
        result=result, files=files or [], priority=priority,
        process=process or [], prompt=prompt,
    )


class TestInit:
    @pytest.mark.asyncio
    async def test_init_creates_db(self, store, data_dir):
        db_path = data_dir / "overmind.db"
        assert db_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_store.py::TestInit -v`
Expected: FAIL — `SQLiteStore` not defined

- [ ] **Step 3: Write StoreProtocol and SQLiteStore skeleton**

Replace entire `server/overmind/store.py` with:

```python
"""SQLite-backed memory store for Overmind events."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, Optional, Protocol

import aiosqlite

from overmind.models import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryEvent,
    PolymorphismAlert,
    PullResponse,
    ReportResponse,
)


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    return datetime.fromisoformat(ts)


def _file_to_scope(file_path: str) -> str:
    """Convert a file path like 'src/auth/login.ts' to 'src/auth/*'."""
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return "*"
    return "/".join(parts[:-1]) + "/*"


DetailLevel = Literal["summary", "full"]


class StoreProtocol(Protocol):
    """Storage backend contract.

    All store implementations must conform to this interface.
    Designed for future replacement (e.g. vector DB).
    """

    async def init_db(self) -> None: ...
    async def close(self) -> None: ...
    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]: ...
    async def pull(
        self,
        repo_id: str,
        *,
        user: Optional[str] = None,
        exclude_user: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        detail: DetailLevel = "full",
    ) -> PullResponse: ...
    async def list_repos(self) -> list[str]: ...
    async def get_repo_stats(
        self, repo_id: str, *, since: Optional[str] = None,
        until: Optional[str] = None, period: str = "7d",
    ) -> ReportResponse: ...
    async def get_graph_data(self, repo_id: str) -> GraphResponse: ...
    async def get_flow_data(self, repo_id: str) -> dict: ...
    def get_version(self, repo_id: str) -> int: ...
    def get_global_version(self) -> int: ...
    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int: ...


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    repo_id     TEXT NOT NULL,
    user        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    result      TEXT NOT NULL,
    prompt      TEXT,
    files       TEXT DEFAULT '[]',
    process     TEXT DEFAULT '[]',
    priority    TEXT DEFAULT 'normal',
    scope       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_repo       ON events(repo_id);
CREATE INDEX IF NOT EXISTS idx_events_repo_ts    ON events(repo_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_repo_user  ON events(repo_id, user);
CREATE INDEX IF NOT EXISTS idx_events_repo_scope ON events(repo_id, scope);

CREATE TABLE IF NOT EXISTS pull_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     TEXT NOT NULL,
    puller      TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    event_user  TEXT NOT NULL,
    ts          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pull_repo   ON pull_log(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pull_dedup ON pull_log(repo_id, puller, event_id);
"""


class SQLiteStore:
    """Async SQLite store for MemoryEvent objects."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._db_path = self.data_dir / "overmind.db"
        self._conn: aiosqlite.Connection | None = None
        self._version: dict[str, int] = defaultdict(int)
        self._global_version: int = 0

    async def init_db(self) -> None:
        """Initialize database connection and create tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    # Methods will be implemented in subsequent tasks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_store.py::TestInit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/overmind/store.py server/tests/test_store.py
git commit -m "feat: StoreProtocol + SQLiteStore skeleton with init_db"
```

---

### Task 3: Implement push()

**Files:**
- Modify: `server/overmind/store.py`
- Modify: `server/tests/test_store.py`

- [ ] **Step 1: Write tests for push**

Update the existing `TestPush` class in `server/tests/test_store.py`:

```python
@pytest.mark.asyncio
class TestPush:
    async def test_push_single_event(self, store):
        evt = _make_event("evt_001")
        accepted, duplicates = await store.push([evt])
        assert accepted == 1
        assert duplicates == 0

    async def test_push_duplicate_ignored(self, store):
        evt = _make_event("evt_001")
        await store.push([evt])
        accepted, duplicates = await store.push([evt])
        assert accepted == 0
        assert duplicates == 1

    async def test_push_multiple_events(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(5)]
        accepted, duplicates = await store.push(events)
        assert accepted == 5
        assert duplicates == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py::TestPush -v`
Expected: FAIL — push() not implemented

- [ ] **Step 3: Implement push()**

Add to `SQLiteStore` in `server/overmind/store.py`:

```python
    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """Insert events into SQLite. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0

        for evt in events:
            try:
                await self._conn.execute(
                    """INSERT OR IGNORE INTO events
                       (id, repo_id, user, ts, type, result, prompt, files, process, priority, scope)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evt.id, evt.repo_id, evt.user, evt.ts, evt.type,
                        evt.result, evt.prompt,
                        json.dumps(evt.files), json.dumps(evt.process),
                        evt.priority, evt.scope,
                    ),
                )
                if self._conn.total_changes > 0:
                    # Check if the row was actually inserted
                    cursor = await self._conn.execute(
                        "SELECT changes()"
                    )
                    row = await cursor.fetchone()
                    if row[0] > 0:
                        accepted += 1
                    else:
                        duplicates += 1
                else:
                    duplicates += 1
            except Exception:
                duplicates += 1

        await self._conn.commit()

        if accepted > 0:
            self._global_version += 1
            repo_ids = {evt.repo_id for evt in events}
            for rid in repo_ids:
                self._version[rid] += 1

        return accepted, duplicates
```

**Note:** The `INSERT OR IGNORE` + `changes()` pattern handles dedup. A simpler approach that is more reliable:

```python
    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """Insert events into SQLite. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0

        for evt in events:
            cursor = await self._conn.execute(
                "SELECT 1 FROM events WHERE id = ?", (evt.id,)
            )
            if await cursor.fetchone():
                duplicates += 1
                continue

            await self._conn.execute(
                """INSERT INTO events
                   (id, repo_id, user, ts, type, result, prompt, files, process, priority, scope)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evt.id, evt.repo_id, evt.user, evt.ts, evt.type,
                    evt.result, evt.prompt,
                    json.dumps(evt.files), json.dumps(evt.process),
                    evt.priority, evt.scope,
                ),
            )
            accepted += 1

        await self._conn.commit()

        if accepted > 0:
            self._global_version += 1
            repo_ids = {evt.repo_id for evt in events}
            for rid in repo_ids:
                self._version[rid] += 1

        return accepted, duplicates
```

Use this second approach — simpler and deterministic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_store.py::TestPush -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add server/overmind/store.py server/tests/test_store.py
git commit -m "feat: SQLiteStore.push() with dedup"
```

---

### Task 4: Implement pull() with detail parameter

**Files:**
- Modify: `server/overmind/store.py`
- Modify: `server/tests/test_store.py`

- [ ] **Step 1: Write tests for pull (port existing + add detail test)**

Update/replace `TestPullBasic` in `server/tests/test_store.py`:

```python
@pytest.mark.asyncio
class TestPullBasic:
    async def test_pull_returns_pushed_events(self, store):
        evt = _make_event("evt_001")
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"

    async def test_pull_excludes_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        await store.push([evt_a, evt_b])
        result = await store.pull(repo_id="github.com/test/repo", exclude_user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_b"

    async def test_pull_filters_by_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        await store.push([evt_a, evt_b])
        result = await store.pull(repo_id="github.com/test/repo", user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_a"

    async def test_pull_with_since(self, store):
        evt_old = _make_event("evt_001", ts="2026-03-25T01:00:00Z")
        evt_new = _make_event("evt_002", ts="2026-03-26T06:00:00Z")
        await store.push([evt_old, evt_new])
        result = await store.pull(repo_id="github.com/test/repo", since="2026-03-25T15:00:00Z")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_002"

    async def test_pull_with_limit(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(10)]
        await store.push(events)
        result = await store.pull(repo_id="github.com/test/repo", limit=3)
        assert len(result.events) == 3
        assert result.has_more is True

    async def test_pull_empty_repo(self, store):
        result = await store.pull(repo_id="github.com/nonexistent/repo")
        assert len(result.events) == 0
        assert result.has_more is False

    async def test_pull_broadcast_urgent_first(self, store):
        evt_normal = _make_event("evt_001", priority="normal", ts="2026-03-26T05:00:00Z")
        evt_urgent = _make_event("evt_002", priority="urgent", ts="2026-03-26T04:00:00Z")
        await store.push([evt_normal, evt_urgent])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].id == "evt_002"  # urgent first despite older ts

    async def test_pull_different_repos_isolated(self, store):
        evt_1 = _make_event("evt_001", repo_id="github.com/test/repo1")
        evt_2 = _make_event("evt_002", repo_id="github.com/test/repo2")
        await store.push([evt_1, evt_2])
        result = await store.pull(repo_id="github.com/test/repo1")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"

    async def test_pull_detail_summary(self, store):
        evt = _make_event(
            "evt_detail_001",
            process=["step1", "step2"],
            prompt="original prompt",
            files=["src/auth/login.ts"],
        )
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo", detail="summary")
        assert len(result.events) == 1
        e = result.events[0]
        # summary keeps: id, repo_id, user, ts, type, result, priority, scope, files
        assert e.id == "evt_detail_001"
        assert e.files == ["src/auth/login.ts"]
        # summary excludes: process, prompt
        assert e.process == []
        assert e.prompt is None

    async def test_pull_detail_full(self, store):
        evt = _make_event(
            "evt_detail_002",
            process=["step1", "step2"],
            prompt="original prompt",
        )
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo", detail="full")
        e = result.events[0]
        assert e.process == ["step1", "step2"]
        assert e.prompt == "original prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py::TestPullBasic -v`
Expected: FAIL — pull() not implemented

- [ ] **Step 3: Implement pull() with scope matching and detail support**

Add helper and `pull()` to `SQLiteStore` in `server/overmind/store.py`:

```python
    def _matches_scope(self, evt_scope: str | None, evt_files: list[str], scope: str | None) -> bool:
        """Return True if the event matches the given scope glob."""
        if scope is None:
            return True
        if evt_scope and fnmatch(evt_scope, scope):
            return True
        for f in evt_files:
            if fnmatch(f, scope):
                return True
        return False

    def _row_to_event(self, row: aiosqlite.Row, detail: DetailLevel = "full") -> MemoryEvent:
        """Convert a database row to a MemoryEvent."""
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
        )

    async def pull(
        self,
        repo_id: str,
        *,
        user: Optional[str] = None,
        exclude_user: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        detail: DetailLevel = "full",
    ) -> PullResponse:
        """Return events for a repo, sorted urgent-first then newest-first."""
        query = "SELECT * FROM events WHERE repo_id = ?"
        params: list = [repo_id]

        if user is not None:
            query += " AND user = ?"
            params.append(user)
        if exclude_user is not None:
            query += " AND user != ?"
            params.append(exclude_user)
        if since is not None:
            query += " AND ts > ?"
            params.append(since)

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()

        # Scope filtering in Python (fnmatch)
        filtered = []
        for row in rows:
            evt_files = json.loads(row["files"]) if row["files"] else []
            if self._matches_scope(row["scope"], evt_files, scope):
                filtered.append(row)

        # Sort: urgent first, then newest first
        urgent = sorted(
            [r for r in filtered if r["priority"] == "urgent"],
            key=lambda r: r["ts"],
            reverse=True,
        )
        normal = sorted(
            [r for r in filtered if r["priority"] != "urgent"],
            key=lambda r: r["ts"],
            reverse=True,
        )
        sorted_rows = urgent + normal

        has_more = len(sorted_rows) > limit
        result_rows = sorted_rows[:limit]

        # Record pull history
        puller = exclude_user
        if puller:
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            for row in result_rows:
                await self._conn.execute(
                    """INSERT OR IGNORE INTO pull_log
                       (repo_id, puller, event_id, event_user, ts)
                       VALUES (?, ?, ?, ?, ?)""",
                    (repo_id, puller, row["id"], row["user"], now_iso),
                )
            await self._conn.commit()

        events = [self._row_to_event(row, detail) for row in result_rows]
        return PullResponse(events=events, count=len(events), has_more=has_more)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_store.py::TestPullBasic -v`
Expected: 10 PASS (8 existing + 2 new detail tests)

- [ ] **Step 5: Commit**

```bash
git add server/overmind/store.py server/tests/test_store.py
git commit -m "feat: SQLiteStore.pull() with scope filtering and detail param"
```

---

### Task 5: Implement list_repos(), get_version(), get_global_version()

**Files:**
- Modify: `server/overmind/store.py`

- [ ] **Step 1: Implement the three methods**

Add to `SQLiteStore` in `server/overmind/store.py`:

```python
    async def list_repos(self) -> list[str]:
        """Return all known repo_ids."""
        cursor = await self._conn.execute("SELECT DISTINCT repo_id FROM events ORDER BY repo_id")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    def get_version(self, repo_id: str) -> int:
        """Return current version counter for a repo (for SSE change detection)."""
        return self._version[repo_id]

    def get_global_version(self) -> int:
        """Return global version counter (for new repo detection via SSE)."""
        return self._global_version
```

- [ ] **Step 2: Run existing API tests that exercise list_repos**

Run: `cd server && uv run pytest tests/test_store.py -v`
Expected: all store tests PASS

- [ ] **Step 3: Commit**

```bash
git add server/overmind/store.py
git commit -m "feat: SQLiteStore list_repos, get_version, get_global_version"
```

---

### Task 6: Implement get_repo_stats()

**Files:**
- Modify: `server/overmind/store.py`

- [ ] **Step 1: Implement get_repo_stats()**

Add to `SQLiteStore` in `server/overmind/store.py`:

```python
    async def get_repo_stats(
        self,
        repo_id: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        period: str = "7d",
    ) -> ReportResponse:
        """Return aggregate statistics for a repo."""
        query = "SELECT * FROM events WHERE repo_id = ?"
        params: list = [repo_id]

        if since:
            query += " AND ts >= ?"
            params.append(since)
        if until:
            query += " AND ts <= ?"
            params.append(until)

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()

        unique_users = len({r["user"] for r in rows})
        events_by_type: dict[str, int] = defaultdict(int)
        for r in rows:
            events_by_type[r["type"]] += 1

        # Count unique (puller, event_id) pairs from pull_log
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT puller, event_id FROM pull_log WHERE repo_id = ?)",
            (repo_id,),
        )
        row = await cursor.fetchone()
        unique_pulls = row[0]

        return ReportResponse(
            repo_id=repo_id,
            period=period,
            total_pushes=len(rows),
            total_pulls=unique_pulls,
            unique_users=unique_users,
            events_by_type=dict(events_by_type),
        )
```

- [ ] **Step 2: Run report tests**

Run: `cd server && uv run pytest tests/test_api.py::TestReportEndpoint -v`
Expected: will fail until API is wired — skip for now, verify in Task 9

- [ ] **Step 3: Commit**

```bash
git add server/overmind/store.py
git commit -m "feat: SQLiteStore.get_repo_stats()"
```

---

### Task 7: Implement get_graph_data() and get_flow_data()

**Files:**
- Modify: `server/overmind/store.py`

- [ ] **Step 1: Implement get_graph_data()**

Add to `SQLiteStore` in `server/overmind/store.py`:

```python
    async def _fetch_all_events(self, repo_id: str) -> list[MemoryEvent]:
        """Fetch all events for a repo as MemoryEvent objects."""
        cursor = await self._conn.execute(
            "SELECT * FROM events WHERE repo_id = ?", (repo_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def _fetch_pull_log(self, repo_id: str) -> list[dict]:
        """Fetch deduplicated pull log entries for a repo."""
        cursor = await self._conn.execute(
            "SELECT DISTINCT puller, event_id, event_user, ts FROM pull_log WHERE repo_id = ?",
            (repo_id,),
        )
        rows = await cursor.fetchall()
        return [{"puller": r[0], "event_id": r[1], "event_user": r[2], "ts": r[3]} for r in rows]

    async def get_graph_data(self, repo_id: str) -> GraphResponse:
        """Return graph nodes, edges, and polymorphism alerts for a repo."""
        all_events = await self._fetch_all_events(repo_id)

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_users: set[str] = set()
        seen_scopes: set[str] = set()
        scope_users: dict[str, set[str]] = defaultdict(set)
        scope_intents: dict[str, list[str]] = defaultdict(list)

        for evt in all_events:
            if evt.user not in seen_users:
                nodes.append(GraphNode(id=f"user:{evt.user}", type="user", label=evt.user))
                seen_users.add(evt.user)

            nodes.append(
                GraphNode(
                    id=f"event:{evt.id}",
                    type="event",
                    label=evt.result[:60] if evt.result else evt.id,
                    event_type=evt.type,
                    data={"result": evt.result, "process": evt.process, "ts": evt.ts},
                )
            )
            edges.append(
                GraphEdge(source=f"user:{evt.user}", target=f"event:{evt.id}", relation="pushed")
            )

            scopes = {_file_to_scope(f) for f in evt.files}
            if evt.scope:
                scopes.add(evt.scope)

            for scope in scopes:
                if scope not in seen_scopes:
                    nodes.append(GraphNode(id=f"scope:{scope}", type="scope", label=scope))
                    seen_scopes.add(scope)
                edges.append(
                    GraphEdge(source=f"event:{evt.id}", target=f"scope:{scope}", relation="affects")
                )
                scope_users[scope].add(evt.user)
                scope_intents[scope].append(evt.result)

        polymorphisms: list[PolymorphismAlert] = []
        for scope, users in scope_users.items():
            if len(users) > 1:
                polymorphisms.append(
                    PolymorphismAlert(scope=scope, users=sorted(users), intents=scope_intents[scope])
                )

        # Pull edges with ghost nodes
        pull_entries = await self._fetch_pull_log(repo_id)
        for entry in pull_entries:
            puller = entry["puller"]
            evt_id = entry["event_id"]
            evt_user = entry["event_user"]

            if puller == evt_user:
                continue

            if puller not in seen_users:
                nodes.append(GraphNode(id=f"user:{puller}", type="user", label=puller))
                seen_users.add(puller)

            orig_evt = next((e for e in all_events if e.id == evt_id), None)
            ghost_id = f"ghost:{puller}:{evt_id}"

            nodes.append(GraphNode(
                id=ghost_id,
                type="event",
                label=orig_evt.result[:60] if orig_evt else evt_id,
                event_type=orig_evt.type if orig_evt else None,
                data={
                    "ghost": True,
                    "consumed_by": puller,
                    "original_user": evt_user,
                    "result": orig_evt.result if orig_evt else "",
                    "ts": entry.get("ts", ""),
                },
            ))

            edges.append(GraphEdge(source=f"user:{puller}", target=ghost_id, relation="consumed"))
            edges.append(GraphEdge(source=f"event:{evt_id}", target=ghost_id, relation="pulled"))

        return GraphResponse(nodes=nodes, edges=edges, polymorphisms=polymorphisms)
```

- [ ] **Step 2: Implement get_flow_data()**

Add to `SQLiteStore`:

```python
    async def get_flow_data(self, repo_id: str) -> dict:
        """Return chronological flow data: push events + pull links."""
        all_events = await self._fetch_all_events(repo_id)
        all_events.sort(key=lambda e: _parse_ts(e.ts))

        pull_entries = await self._fetch_pull_log(repo_id)
        puller_set = {e["puller"] for e in pull_entries}
        agents = sorted({e.user for e in all_events} | puller_set)

        events = [
            {
                "id": e.id, "user": e.user, "type": e.type,
                "result": e.result, "ts": e.ts, "scope": e.scope,
                "files": e.files, "process": e.process, "priority": e.priority,
            }
            for e in all_events
        ]

        pull_links = []
        for entry in pull_entries:
            if entry["puller"] == entry.get("event_user", ""):
                continue
            pull_links.append({
                "puller": entry["puller"],
                "event_id": entry["event_id"],
                "event_user": entry.get("event_user", ""),
                "ts": entry.get("ts", ""),
            })

        scope_users: dict[str, set[str]] = defaultdict(set)
        scope_intents: dict[str, list[str]] = defaultdict(list)
        for evt in all_events:
            scopes = {_file_to_scope(f) for f in evt.files}
            if evt.scope:
                scopes.add(evt.scope)
            for scope in scopes:
                scope_users[scope].add(evt.user)
                scope_intents[scope].append(evt.result)

        polymorphisms = [
            {"scope": scope, "users": sorted(users), "intents": scope_intents[scope]}
            for scope, users in scope_users.items()
            if len(users) > 1
        ]

        return {
            "agents": agents,
            "events": events,
            "pull_links": pull_links,
            "polymorphisms": polymorphisms,
        }
```

- [ ] **Step 3: Commit**

```bash
git add server/overmind/store.py
git commit -m "feat: SQLiteStore.get_graph_data() and get_flow_data()"
```

---

### Task 8: Implement cleanup_expired()

**Files:**
- Modify: `server/overmind/store.py`

- [ ] **Step 1: Implement cleanup_expired()**

Add to `SQLiteStore`:

```python
    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int:
        """Remove events older than ttl_days. Returns count of removed events."""
        cutoff = datetime.now(tz=timezone.utc) - __import__("datetime").timedelta(days=ttl_days)
        cutoff_iso = cutoff.isoformat()

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE repo_id = ? AND ts < ?",
            (repo_id, cutoff_iso),
        )
        row = await cursor.fetchone()
        count = row[0]

        if count > 0:
            await self._conn.execute(
                "DELETE FROM events WHERE repo_id = ? AND ts < ?",
                (repo_id, cutoff_iso),
            )
            await self._conn.commit()

        return count
```

Fix: use proper import at top of file. Add `from datetime import timedelta` to the existing datetime imports:

```python
from datetime import datetime, timedelta, timezone
```

Then the method becomes:

```python
    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int:
        """Remove events older than ttl_days. Returns count of removed events."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=ttl_days)
        cutoff_iso = cutoff.isoformat()

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE repo_id = ? AND ts < ?",
            (repo_id, cutoff_iso),
        )
        row = await cursor.fetchone()
        count = row[0]

        if count > 0:
            await self._conn.execute(
                "DELETE FROM events WHERE repo_id = ? AND ts < ?",
                (repo_id, cutoff_iso),
            )
            await self._conn.commit()

        return count
```

- [ ] **Step 2: Run all store tests**

Run: `cd server && uv run pytest tests/test_store.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add server/overmind/store.py
git commit -m "feat: SQLiteStore.cleanup_expired()"
```

---

### Task 9: Wire async store into API layer + lifespan

**Files:**
- Modify: `server/overmind/api.py`
- Modify: `server/overmind/main.py`
- Modify: `server/overmind/mcp_server.py`

- [ ] **Step 1: Update api.py — async store calls + detail param**

Replace `server/overmind/api.py`:

```python
"""FastAPI application for Overmind memory sync server."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from overmind.models import (
    BroadcastRequest,
    BroadcastResponse,
    MemoryEvent,
    PullResponse,
    PushRequest,
    PushResponse,
    ReportResponse,
)
from overmind.store import SQLiteStore


def create_app(
    data_dir: Optional[Path] = None,
    store: Optional[SQLiteStore] = None,
    lifespan=None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    if data_dir is None:
        data_dir = Path("data")
    data_dir = Path(data_dir)

    if store is None:
        store = SQLiteStore(data_dir=data_dir)

    # Wrap lifespan to init/close store
    outer_lifespan = lifespan

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        await store.init_db()
        if outer_lifespan:
            async with outer_lifespan(app):
                yield
        else:
            yield
        await store.close()

    app = FastAPI(title="Overmind Memory Sync Server", lifespan=app_lifespan)

    # Mount dashboard static files if directory exists
    dashboard_dir = Path(__file__).parent / "dashboard" / "static"
    if dashboard_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    @app.get("/api/repos")
    async def list_repos() -> list[str]:
        return await store.list_repos()

    @app.post("/api/memory/push", response_model=PushResponse)
    async def push_memory(request: PushRequest) -> PushResponse:
        events = [evt.to_event(request.repo_id, request.user) for evt in request.events]
        accepted, duplicates = await store.push(events)
        return PushResponse(accepted=accepted, duplicates=duplicates)

    @app.get("/api/memory/pull", response_model=PullResponse)
    async def pull_memory(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        scope: Optional[str] = Query(default=None),
        user: Optional[str] = Query(default=None),
        exclude_user: Optional[str] = Query(default=None),
        limit: int = Query(default=100),
        detail: str = Query(default="full"),
    ) -> PullResponse:
        return await store.pull(
            repo_id,
            since=since,
            scope=scope,
            user=user,
            exclude_user=exclude_user,
            limit=limit,
            detail=detail,
        )

    @app.post("/api/memory/broadcast", response_model=BroadcastResponse)
    async def broadcast_memory(request: BroadcastRequest) -> BroadcastResponse:
        bcast_id = f"bcast_{uuid.uuid4().hex[:12]}"
        ts = datetime.now(timezone.utc).isoformat()

        event = MemoryEvent(
            id=bcast_id,
            repo_id=request.repo_id,
            user=request.user,
            ts=ts,
            type="broadcast",
            result=request.message,
            priority=request.priority,
            scope=request.scope,
            files=request.related_files,
        )
        await store.push([event])
        return BroadcastResponse(id=bcast_id, delivered=True)

    @app.get("/api/report", response_model=ReportResponse)
    async def get_report(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        until: Optional[str] = Query(default=None),
        period: str = Query(default="7d"),
    ) -> ReportResponse:
        return await store.get_repo_stats(repo_id, since=since, until=until, period=period)

    @app.get("/api/report/graph")
    async def get_report_graph(repo_id: str = Query(...)):
        return await store.get_graph_data(repo_id)

    @app.get("/api/report/flow")
    async def get_report_flow(repo_id: str = Query(...)):
        return await store.get_flow_data(repo_id)

    @app.get("/api/report/timeline")
    async def get_report_timeline(repo_id: str = Query(...)):
        pull_resp = await store.pull(repo_id, limit=1000)
        swimlanes: dict[str, list] = defaultdict(list)
        for evt in pull_resp.events:
            swimlanes[evt.user].append(evt.model_dump())
        return {"swimlanes": swimlanes}

    @app.get("/api/stream")
    async def event_stream(repo_id: Optional[str] = Query(default=None)):
        """SSE endpoint: sends 'update' on repo data changes, 'repos' on new repo discovery."""
        async def generate():
            try:
                last_repo_version = store.get_version(repo_id) if repo_id else 0
                last_global_version = store.get_global_version()
                last_repos = set(await store.list_repos())

                yield f"data: {json.dumps({'type': 'connected', 'repos': sorted(last_repos)})}\n\n"

                while True:
                    await asyncio.sleep(1)

                    current_global = store.get_global_version()
                    if current_global == last_global_version:
                        continue

                    last_global_version = current_global

                    current_repos = set(await store.list_repos())
                    new_repos = current_repos - last_repos
                    if new_repos:
                        yield f"data: {json.dumps({'type': 'repos', 'new': sorted(new_repos), 'all': sorted(current_repos)})}\n\n"
                        last_repos = current_repos

                    if repo_id:
                        current_repo_v = store.get_version(repo_id)
                        if current_repo_v != last_repo_version:
                            last_repo_version = current_repo_v
                            yield f"data: {json.dumps({'type': 'update', 'version': current_repo_v})}\n\n"
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
```

- [ ] **Step 2: Update main.py — use SQLiteStore**

Replace `server/overmind/main.py`:

```python
"""Overmind server entry point: REST (FastAPI) + MCP (FastMCP) on single uvicorn."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from overmind.api import create_app
from overmind.mcp_server import create_mcp_server
from overmind.store import SQLiteStore


def create_standalone_app():
    """Factory for uvicorn --factory. Reads OVERMIND_DATA_DIR env var."""
    import os
    data_dir = Path(os.environ.get("OVERMIND_DATA_DIR", "data"))
    store = SQLiteStore(data_dir=data_dir)
    return create_app(data_dir=data_dir, store=store)


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7777, help="Bind port (default: 7777)")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = SQLiteStore(data_dir=data_dir)

    mcp = create_mcp_server(store)
    mcp_app = mcp.http_app(path="/")

    app = create_app(data_dir=data_dir, store=store, lifespan=mcp_app.lifespan)
    app.mount("/mcp", mcp_app)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update mcp_server.py — async store calls**

Replace `server/overmind/mcp_server.py`:

```python
"""FastMCP wrapper exposing Overmind store as MCP tools."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastmcp import FastMCP

from overmind.store import SQLiteStore
from overmind.models import MemoryEvent


def create_mcp_server(store: SQLiteStore) -> FastMCP:
    mcp = FastMCP("Overmind", instructions="Distributed memory sync for Claude Code")

    @mcp.tool()
    async def overmind_push(repo_id: str, user: str, events: list[dict]) -> dict:
        """Push memory events to Overmind server."""
        parsed = []
        for e in events:
            parsed.append(MemoryEvent(repo_id=repo_id, user=user, **e))
        accepted, duplicates = await store.push(parsed)
        return {"accepted": accepted, "duplicates": duplicates}

    @mcp.tool()
    async def overmind_pull(
        repo_id: str,
        exclude_user: str | None = None,
        since: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Pull other agents' memory events from Overmind server."""
        result = await store.pull(
            repo_id=repo_id,
            exclude_user=exclude_user,
            since=since,
            scope=scope,
            limit=limit,
        )
        return result.model_dump()

    @mcp.tool()
    async def overmind_broadcast(
        repo_id: str,
        user: str,
        message: str,
        priority: str = "normal",
        scope: str | None = None,
        related_files: list[str] | None = None,
    ) -> dict:
        """Broadcast urgent message to all agents on this repo."""
        evt_id = f"bcast_{uuid.uuid4().hex[:12]}"
        evt = MemoryEvent(
            id=evt_id,
            repo_id=repo_id,
            user=user,
            ts=datetime.now(timezone.utc).isoformat(),
            type="broadcast",
            result=message,
            files=related_files or [],
            priority=priority,
            scope=scope,
        )
        await store.push([evt])
        return {"id": evt_id, "delivered": True}

    return mcp
```

- [ ] **Step 4: Run all API + MCP tests**

Run: `cd server && uv run pytest tests/test_api.py tests/test_mcp.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add server/overmind/api.py server/overmind/main.py server/overmind/mcp_server.py
git commit -m "feat: wire async SQLiteStore into API + MCP + lifespan"
```

---

### Task 10: Add detail param API test

**Files:**
- Modify: `server/tests/test_api.py`

- [ ] **Step 1: Add detail parameter tests**

Add to `TestPullEndpoint` in `server/tests/test_api.py`:

```python
    async def test_pull_detail_summary(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_detail_api",
                "type": "correction",
                "ts": "2026-03-26T05:30:00Z",
                "result": "found the bug",
                "files": ["src/auth/login.ts"],
                "process": ["step1", "step2"],
                "prompt": "fix the auth bug",
            }],
        })
        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/test/repo",
            "detail": "summary",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        evt = body["events"][0]
        assert evt["files"] == ["src/auth/login.ts"]
        assert evt["process"] == []
        assert evt["prompt"] is None
```

- [ ] **Step 2: Run test**

Run: `cd server && uv run pytest tests/test_api.py::TestPullEndpoint::test_pull_detail_summary -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_api.py
git commit -m "test: add detail=summary API test"
```

---

### Task 11: Fix scenario tests for async store

**Files:**
- Modify: `server/tests/scenarios/test_multi_agent_sim.py` (remove duplicate ServerThread, use shared helper)
- Modify: `server/tests/scenarios/test_e2e_server.py` (no change needed — subprocess based)

The scenario tests that use `ServerThread` + `create_app()` should work without changes because:
- `create_app()` now has a lifespan that calls `init_db()` automatically
- ServerThread runs uvicorn which handles the lifespan
- The HTTP API interface is unchanged

- [ ] **Step 1: Run all scenario tests**

Run: `cd server && uv run pytest tests/scenarios/ -v`
Expected: all PASS. If any fail, investigate and fix.

- [ ] **Step 2: Run the complete test suite**

Run: `cd server && uv run pytest tests/ -v`
Expected: all 53+ tests PASS (53 existing + 2-3 new detail tests)

- [ ] **Step 3: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: adapt scenario tests for async SQLiteStore"
```

---

### Task 12: Adapt db_cleanup.py for SQLite

**Files:**
- Modify: `server/scripts/db_cleanup.py`

- [ ] **Step 1: Rewrite db_cleanup.py**

Replace `server/scripts/db_cleanup.py`:

```python
#!/usr/bin/env python3
"""Overmind SQLite store management utility.

Usage:
    python scripts/db_cleanup.py status                      # Show store stats
    python scripts/db_cleanup.py ttl [--days 14]             # Remove events older than N days
    python scripts/db_cleanup.py purge-repo <repo_id>        # Delete all data for a repo
    python scripts/db_cleanup.py purge-user <repo_id> <user> # Delete all events by a user in a repo
    python scripts/db_cleanup.py purge-all                   # Delete database file
    python scripts/db_cleanup.py vacuum                      # Reclaim disk space
    python scripts/db_cleanup.py export <repo_id> [--out FILE] # Export repo events as JSONL
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "overmind.db"


def _get_db_path(args: argparse.Namespace) -> Path:
    return Path(args.db) if args.db else DEFAULT_DB


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_status(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    if not db_path.exists():
        print("No database found.")
        return

    conn = _connect(db_path)
    print(f"Database: {db_path} ({db_path.stat().st_size / 1024:.1f} KB)\n")

    cursor = conn.execute(
        """SELECT repo_id, COUNT(*) as cnt, COUNT(DISTINCT user) as users,
                  MIN(ts) as oldest, MAX(ts) as newest
           FROM events GROUP BY repo_id ORDER BY repo_id"""
    )
    total_events = 0
    for row in cursor:
        cnt = row["cnt"]
        total_events += cnt
        print(f"  repo: {row['repo_id']}")
        print(f"    events: {cnt}  users: {row['users']}")
        if row["oldest"]:
            print(f"    range: {row['oldest'][:19]} ~ {row['newest'][:19]}")
        print()

    pull_count = conn.execute("SELECT COUNT(*) FROM pull_log").fetchone()[0]
    print(f"Total: {total_events} events, {pull_count} pull log entries")
    conn.close()


def cmd_ttl(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_iso = cutoff.isoformat()

    count_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.execute("DELETE FROM events WHERE ts < ?", (cutoff_iso,))
    conn.commit()
    count_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    removed = count_before - count_after
    print(f"TTL cleanup (>{args.days} days): removed {removed}, kept {count_after}")
    conn.close()


def cmd_purge_repo(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE repo_id = ?", (args.repo_id,)
    ).fetchone()[0]

    if count == 0:
        print(f"Repo not found: {args.repo_id}")
        conn.close()
        return

    conn.execute("DELETE FROM events WHERE repo_id = ?", (args.repo_id,))
    conn.execute("DELETE FROM pull_log WHERE repo_id = ?", (args.repo_id,))
    conn.commit()
    print(f"Purged repo '{args.repo_id}': {count} events deleted")
    conn.close()


def cmd_purge_user(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE repo_id = ? AND user = ?",
        (args.repo_id, args.user),
    ).fetchone()[0]

    if count == 0:
        print(f"User '{args.user}' not found in repo '{args.repo_id}'")
        conn.close()
        return

    conn.execute(
        "DELETE FROM events WHERE repo_id = ? AND user = ?",
        (args.repo_id, args.user),
    )
    conn.commit()
    print(f"Purged user '{args.user}' from repo '{args.repo_id}': {count} events deleted")
    conn.close()


def cmd_purge_all(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    if not db_path.exists():
        print("No database found.")
        return

    if not args.yes:
        confirm = input("This will delete the entire Overmind database. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    db_path.unlink()
    print("Database deleted.")


def cmd_vacuum(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    size_before = db_path.stat().st_size
    conn.execute("VACUUM")
    conn.close()
    size_after = db_path.stat().st_size

    saved = size_before - size_after
    print(f"Vacuum complete: {size_before / 1024:.1f} KB → {size_after / 1024:.1f} KB (saved {saved / 1024:.1f} KB)")


def cmd_export(args: argparse.Namespace) -> None:
    db_path = _get_db_path(args)
    conn = _connect(db_path)

    cursor = conn.execute(
        "SELECT * FROM events WHERE repo_id = ? ORDER BY ts",
        (args.repo_id,),
    )
    rows = cursor.fetchall()

    if not rows:
        print(f"Repo not found: {args.repo_id}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    out = sys.stdout
    if args.out:
        out = open(args.out, "w", encoding="utf-8")

    for row in rows:
        event = {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "user": row["user"],
            "ts": row["ts"],
            "type": row["type"],
            "result": row["result"],
            "prompt": row["prompt"],
            "files": json.loads(row["files"]) if row["files"] else [],
            "process": json.loads(row["process"]) if row["process"] else [],
            "priority": row["priority"],
            "scope": row["scope"],
        }
        out.write(json.dumps(event, ensure_ascii=False) + "\n")

    if args.out:
        out.close()
        print(f"Exported {len(rows)} events to {args.out}", file=sys.stderr)
    else:
        print(f"# {len(rows)} events exported", file=sys.stderr)

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind SQLite store management utility")
    parser.add_argument("--db", help=f"Database path (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show store stats")

    p_ttl = sub.add_parser("ttl", help="Remove events older than N days")
    p_ttl.add_argument("--days", type=int, default=14, help="TTL in days (default: 14)")

    p_repo = sub.add_parser("purge-repo", help="Delete all data for a repo")
    p_repo.add_argument("repo_id", help="e.g. github.com/user/project")

    p_user = sub.add_parser("purge-user", help="Delete all events by a user in a repo")
    p_user.add_argument("repo_id")
    p_user.add_argument("user")

    p_all = sub.add_parser("purge-all", help="Delete database file")
    p_all.add_argument("--yes", action="store_true", help="Skip confirmation")

    sub.add_parser("vacuum", help="Reclaim disk space (SQLite VACUUM)")

    p_export = sub.add_parser("export", help="Export repo events as JSONL")
    p_export.add_argument("repo_id")
    p_export.add_argument("--out", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "status": cmd_status,
        "ttl": cmd_ttl,
        "purge-repo": cmd_purge_repo,
        "purge-user": cmd_purge_user,
        "purge-all": cmd_purge_all,
        "vacuum": cmd_vacuum,
        "export": cmd_export,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the script help output**

Run: `cd server && uv run python scripts/db_cleanup.py --help`
Expected: shows usage with `vacuum` instead of `compact`

- [ ] **Step 3: Commit**

```bash
git add server/scripts/db_cleanup.py
git commit -m "refactor: adapt db_cleanup.py for SQLite (compact → vacuum)"
```

---

### Task 13: Update CLAUDE.md references

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Changes needed:
- Server description: `JSONL file-based store` → `SQLite store (aiosqlite)`
- Storage in Tech Stack: `JSONL file-based (Phase 2: SQLite)` → `SQLite (aiosqlite)`
- Key Files: `store.py` description → `SQLite store 핵심 로직 (StoreProtocol + SQLiteStore)`
- DB cleanup commands: `compact` → `vacuum`, remove `export` JSONL reference
- Phase 2-A: mark SQLite and detail as done

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for SQLite store migration"
```

---

### Task 14: Full regression run + cleanup

- [ ] **Step 1: Run complete server test suite**

Run: `cd server && uv run pytest tests/ -v`
Expected: all tests PASS (53+ existing + new detail tests)

- [ ] **Step 2: Run plugin tests to verify no breakage**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all 59 plugin tests PASS (plugin uses REST API, no store dependency)

- [ ] **Step 3: Start server and verify dashboard**

Run: `cd server && uv run python -m overmind.main --data-dir /tmp/overmind_test`
Open: `http://localhost:7777/dashboard`
Expected: dashboard loads, no errors in console

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: final adjustments for SQLite migration"
```

- [ ] **Step 5: Remove old JSONL data directory (if exists)**

The old `data/repos/` directory can be safely deleted since we're using `data/overmind.db` now. This is optional cleanup.
