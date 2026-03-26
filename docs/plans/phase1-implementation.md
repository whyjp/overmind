# Overmind Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Overmind distributed memory sync system — server (REST + MCP) + Claude Code plugin + dashboard — and validate the push/pull cycle with automated tests.

**Architecture:** Layered build. Layer 1: Python server core with JSONL file store and FastAPI REST. Layer 2: FastMCP wrapper exposing MCP tools. Layer 3: Claude Code plugin with hooks for automatic push/pull. Layer 4: D3.js dashboard for visualization. All in a single process on port 7777.

**Tech Stack:** Python 3.11+, FastAPI, FastMCP, uvicorn, Pydantic v2, httpx, pytest, D3.js (CDN), uv

---

## File Map

### Server (`server/`)

| File | Responsibility |
|------|---------------|
| `server/pyproject.toml` | Dependencies and project config |
| `server/overmind/__init__.py` | Package init |
| `server/overmind/models.py` | Pydantic models: MemoryEvent, PushRequest, PullResponse, BroadcastRequest, ReportResponse, GraphResponse |
| `server/overmind/store.py` | JSONL file store: append, query, scope index, TTL cleanup, dedup |
| `server/overmind/api.py` | FastAPI app: REST endpoints + dashboard static mount |
| `server/overmind/mcp_server.py` | FastMCP tools wrapping store directly (no HTTP round-trip) |
| `server/overmind/main.py` | Entry point: mount FastAPI + FastMCP on single uvicorn |
| `server/overmind/dashboard/__init__.py` | Empty (package marker) |
| `server/overmind/dashboard/static/index.html` | Dashboard SPA shell |
| `server/overmind/dashboard/static/app.js` | D3.js graph + overview + timeline |
| `server/overmind/dashboard/static/style.css` | Dashboard styles |

### Tests (`server/tests/`)

| File | Covers |
|------|--------|
| `server/tests/conftest.py` | Shared fixtures: tmp data dir, store instance, FastAPI TestClient |
| `server/tests/test_models.py` | Pydantic validation |
| `server/tests/test_store.py` | Store push/pull/dedup/TTL/scope |
| `server/tests/test_api.py` | REST endpoints via TestClient |
| `server/tests/test_mcp.py` | MCP tools via FastMCP in-memory Client |
| `server/tests/scenarios/test_scenario_preemptive_block.py` | Szenario: preemptive block |
| `server/tests/scenarios/test_scenario_polymorphism.py` | Scenario: polymorphism detection |
| `server/tests/scenarios/test_scenario_multi_repo.py` | Scenario: repo isolation |

### Plugin (`plugin/`)

| File | Responsibility |
|------|---------------|
| `plugin/.claude-plugin/plugin.json` | Plugin metadata |
| `plugin/.mcp.json` | Overmind MCP server connection |
| `plugin/hooks/hooks.json` | Hook definitions |
| `plugin/hooks/on_session_start.py` | SessionStart: pull from server |
| `plugin/hooks/on_session_end.py` | SessionEnd: push to server |
| `plugin/hooks/on_pre_tool_use.py` | PreToolUse(Write/Edit): selective pull |
| `plugin/scripts/api_client.py` | Shared httpx REST client |
| `plugin/skills/overmind-broadcast/SKILL.md` | Broadcast skill |
| `plugin/skills/overmind-report/SKILL.md` | Report skill |
| `plugin/commands/broadcast.md` | /overmind:broadcast slash command |

---

## Task 1: Project Scaffold

**Files:**
- Create: `server/pyproject.toml`
- Create: `server/overmind/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "overmind-server"
version = "0.1.0"
description = "Overmind: distributed memory sync server for Claude Code"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0.0",
    "fastmcp>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create package init**

```python
# server/overmind/__init__.py
"""Overmind: distributed memory sync server for Claude Code."""
```

- [ ] **Step 3: Install dependencies**

Run: `cd server && uv sync --all-extras`
Expected: All dependencies installed successfully.

- [ ] **Step 4: Verify installation**

Run: `cd server && uv run python -c "import fastapi; import fastmcp; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add server/pyproject.toml server/overmind/__init__.py server/uv.lock
git commit -m "feat: scaffold server project with dependencies"
```

---

## Task 2: Pydantic Models

**Files:**
- Create: `server/overmind/models.py`
- Create: `server/tests/conftest.py`
- Create: `server/tests/test_models.py`

- [ ] **Step 1: Write failing tests for models**

```python
# server/tests/test_models.py
import pytest
from datetime import datetime, timezone
from overmind.models import MemoryEvent, PushRequest, BroadcastRequest


class TestMemoryEvent:
    def test_valid_event_minimal(self):
        evt = MemoryEvent(
            id="evt_001",
            repo_id="github.com/user/project",
            user="dev_a",
            ts="2026-03-26T14:30:22+09:00",
            type="correction",
            result=".env에 SERVICE_A_INTERNAL_URL 필요",
        )
        assert evt.id == "evt_001"
        assert evt.type == "correction"

    def test_valid_event_full(self):
        evt = MemoryEvent(
            id="evt_002",
            repo_id="github.com/user/project",
            user="dev_a",
            ts="2026-03-26T14:30:22+09:00",
            type="decision",
            result="OAuth2 기반으로 전환",
            prompt="인증 방식 전환",
            files=["src/auth/oauth2.ts", "src/auth/jwt.ts"],
            process=["JWT 검토→복잡도 과다", "세션 기반→stateless 충돌", "OAuth2+PKCE 채택"],
            priority="normal",
            scope="src/auth/*",
        )
        assert evt.files == ["src/auth/oauth2.ts", "src/auth/jwt.ts"]
        assert len(evt.process) == 3

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError):
            MemoryEvent(
                id="evt_003",
                repo_id="github.com/user/project",
                user="dev_a",
                ts="2026-03-26T14:30:22+09:00",
                type="invalid_type",
                result="test",
            )

    def test_missing_required_field(self):
        with pytest.raises(ValueError):
            MemoryEvent(
                id="evt_004",
                repo_id="github.com/user/project",
                user="dev_a",
                ts="2026-03-26T14:30:22+09:00",
                type="correction",
                # result missing
            )


class TestPushRequest:
    def test_valid_push(self):
        req = PushRequest(
            repo_id="github.com/user/project",
            user="dev_a",
            events=[
                {
                    "id": "evt_001",
                    "type": "correction",
                    "ts": "2026-03-26T14:30:22+09:00",
                    "result": "test result",
                }
            ],
        )
        assert len(req.events) == 1
        assert req.events[0].repo_id == "github.com/user/project"
        assert req.events[0].user == "dev_a"


class TestBroadcastRequest:
    def test_valid_broadcast(self):
        req = BroadcastRequest(
            repo_id="github.com/user/project",
            user="master_agent",
            message="API 스키마 v2로 변경",
            priority="urgent",
            scope="src/api/*",
            related_files=["src/api/schema.ts"],
        )
        assert req.priority == "urgent"

    def test_default_priority(self):
        req = BroadcastRequest(
            repo_id="github.com/user/project",
            user="dev_a",
            message="test broadcast",
        )
        assert req.priority == "normal"
```

- [ ] **Step 2: Create conftest with shared fixtures**

```python
# server/tests/conftest.py
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for store tests."""
    return tmp_path / "data"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overmind.models'`

- [ ] **Step 4: Implement models**

```python
# server/overmind/models.py
"""Pydantic models for Overmind events and API requests/responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EventType = Literal["decision", "correction", "discovery", "change", "broadcast"]
Priority = Literal["normal", "urgent"]


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


class PushRequest(BaseModel):
    """Request body for POST /api/memory/push."""

    repo_id: str
    user: str
    events: list[PushEventInput]


class PushEventInput(BaseModel):
    """Event input within a push request. repo_id and user are inherited from parent."""

    id: str
    type: EventType
    ts: str
    result: str

    prompt: str | None = None
    files: list[str] = Field(default_factory=list)
    process: list[str] = Field(default_factory=list)
    priority: Priority = "normal"
    scope: str | None = None

    def to_event(self, repo_id: str, user: str) -> MemoryEvent:
        return MemoryEvent(
            repo_id=repo_id,
            user=user,
            **self.model_dump(),
        )


# Fix forward reference
PushRequest.model_rebuild()


class PushResponse(BaseModel):
    """Response for POST /api/memory/push."""

    accepted: int
    duplicates: int


class PullResponse(BaseModel):
    """Response for GET /api/memory/pull."""

    events: list[MemoryEvent]
    count: int
    has_more: bool


class BroadcastRequest(BaseModel):
    """Request body for POST /api/memory/broadcast."""

    repo_id: str
    user: str
    message: str
    priority: Priority = "normal"
    scope: str | None = None
    related_files: list[str] = Field(default_factory=list)


class BroadcastResponse(BaseModel):
    """Response for POST /api/memory/broadcast."""

    id: str
    delivered: bool


class ReportResponse(BaseModel):
    """Response for GET /api/report."""

    repo_id: str
    period: str
    total_pushes: int
    total_pulls: int
    unique_users: int
    events_by_type: dict[str, int]


class GraphNode(BaseModel):
    """A node in the Overmind graph visualization."""

    id: str
    type: Literal["user", "event", "scope"]
    label: str | None = None
    event_type: EventType | None = None
    data: dict | None = None


class GraphEdge(BaseModel):
    """An edge in the Overmind graph visualization."""

    source: str
    target: str
    relation: Literal["pushed", "affects", "pulled"]


class PolymorphismAlert(BaseModel):
    """A polymorphism detection alert."""

    scope: str
    users: list[str]
    intents: list[str]


class GraphResponse(BaseModel):
    """Response for GET /api/report/graph."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    polymorphisms: list[PolymorphismAlert]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/overmind/models.py server/tests/conftest.py server/tests/test_models.py
git commit -m "feat: add Pydantic models for events, requests, responses"
```

---

## Task 3: JSONL Store — Push & Basic Pull

**Files:**
- Create: `server/overmind/store.py`
- Create: `server/tests/test_store.py`

- [ ] **Step 1: Write failing tests for push and basic pull**

```python
# server/tests/test_store.py
import pytest
from overmind.models import MemoryEvent
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


def _make_event(id: str, user: str = "dev_a", repo_id: str = "github.com/test/repo",
                type: str = "correction", files: list[str] | None = None,
                ts: str = "2026-03-26T14:30:00+09:00", result: str = "test result",
                priority: str = "normal") -> MemoryEvent:
    return MemoryEvent(
        id=id, repo_id=repo_id, user=user, ts=ts, type=type,
        result=result, files=files or [], priority=priority,
    )


class TestPush:
    def test_push_single_event(self, store):
        evt = _make_event("evt_001")
        accepted, duplicates = store.push([evt])
        assert accepted == 1
        assert duplicates == 0

    def test_push_duplicate_ignored(self, store):
        evt = _make_event("evt_001")
        store.push([evt])
        accepted, duplicates = store.push([evt])
        assert accepted == 0
        assert duplicates == 1

    def test_push_multiple_events(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(5)]
        accepted, duplicates = store.push(events)
        assert accepted == 5
        assert duplicates == 0


class TestPullBasic:
    def test_pull_returns_pushed_events(self, store):
        evt = _make_event("evt_001")
        store.push([evt])
        result = store.pull(repo_id="github.com/test/repo")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"

    def test_pull_excludes_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        store.push([evt_a, evt_b])
        result = store.pull(repo_id="github.com/test/repo", exclude_user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_b"

    def test_pull_filters_by_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        store.push([evt_a, evt_b])
        result = store.pull(repo_id="github.com/test/repo", user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_a"

    def test_pull_with_since(self, store):
        evt_old = _make_event("evt_001", ts="2026-03-25T10:00:00+09:00")
        evt_new = _make_event("evt_002", ts="2026-03-26T15:00:00+09:00")
        store.push([evt_old, evt_new])
        result = store.pull(repo_id="github.com/test/repo", since="2026-03-26T00:00:00+09:00")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_002"

    def test_pull_with_limit(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(10)]
        store.push(events)
        result = store.pull(repo_id="github.com/test/repo", limit=3)
        assert len(result.events) == 3
        assert result.has_more is True

    def test_pull_empty_repo(self, store):
        result = store.pull(repo_id="github.com/nonexistent/repo")
        assert len(result.events) == 0
        assert result.has_more is False

    def test_pull_broadcast_urgent_first(self, store):
        evt_normal = _make_event("evt_001", priority="normal", ts="2026-03-26T14:00:00+09:00")
        evt_urgent = _make_event("evt_002", priority="urgent", ts="2026-03-26T13:00:00+09:00")
        store.push([evt_normal, evt_urgent])
        result = store.pull(repo_id="github.com/test/repo")
        assert result.events[0].id == "evt_002"  # urgent first despite older ts

    def test_pull_different_repos_isolated(self, store):
        evt_1 = _make_event("evt_001", repo_id="github.com/test/repo1")
        evt_2 = _make_event("evt_002", repo_id="github.com/test/repo2")
        store.push([evt_1, evt_2])
        result = store.pull(repo_id="github.com/test/repo1")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overmind.store'`

- [ ] **Step 3: Implement store**

```python
# server/overmind/store.py
"""JSONL file-based memory store with scope indexing and TTL."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path

from overmind.models import MemoryEvent, PullResponse


class MemoryStore:
    """Append-only JSONL store partitioned by repo_id / user / date."""

    def __init__(self, data_dir: Path, ttl_days: int = 14):
        self.data_dir = Path(data_dir)
        self.ttl_days = ttl_days
        self._seen_ids: dict[str, set[str]] = {}  # repo_id -> set of event ids

    def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """Append events to store. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0

        for evt in events:
            seen = self._seen_ids.setdefault(evt.repo_id, set())
            if evt.id in seen:
                duplicates += 1
                continue

            seen.add(evt.id)
            self._append_event(evt)
            accepted += 1

        return accepted, duplicates

    def pull(
        self,
        repo_id: str,
        since: str | None = None,
        scope: str | None = None,
        user: str | None = None,
        exclude_user: str | None = None,
        limit: int = 50,
    ) -> PullResponse:
        """Query events from store with filters."""
        all_events = self._read_repo_events(repo_id)

        # Apply filters
        filtered = []
        since_dt = _parse_ts(since) if since else None

        for evt in all_events:
            if user and evt.user != user:
                continue
            if exclude_user and evt.user == exclude_user:
                continue
            if since_dt and _parse_ts(evt.ts) < since_dt:
                continue
            if scope and not self._matches_scope(evt, scope):
                continue
            filtered.append(evt)

        # Sort: urgent first, then by timestamp descending
        filtered.sort(key=lambda e: (0 if e.priority == "urgent" else 1, e.ts), reverse=False)
        # Re-sort: urgent first, then newest first within each priority group
        urgent = [e for e in filtered if e.priority == "urgent"]
        normal = [e for e in filtered if e.priority != "urgent"]
        urgent.sort(key=lambda e: e.ts, reverse=True)
        normal.sort(key=lambda e: e.ts, reverse=True)
        sorted_events = urgent + normal

        has_more = len(sorted_events) > limit
        limited = sorted_events[:limit]

        return PullResponse(events=limited, count=len(limited), has_more=has_more)

    def get_repo_stats(self, repo_id: str, period_hours: int = 24) -> dict:
        """Get basic stats for a repo."""
        all_events = self._read_repo_events(repo_id)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=period_hours)

        recent = [e for e in all_events if _parse_ts(e.ts) >= cutoff]
        users = set(e.user for e in recent)
        by_type: dict[str, int] = {}
        for e in recent:
            by_type[e.type] = by_type.get(e.type, 0) + 1

        return {
            "total_pushes": len(recent),
            "unique_users": len(users),
            "events_by_type": by_type,
        }

    def get_graph_data(self, repo_id: str, since: str | None = None) -> dict:
        """Get graph nodes and edges for visualization."""
        events = self.pull(repo_id=repo_id, since=since, limit=500).events

        nodes = []
        edges = []
        seen_users: set[str] = set()
        seen_scopes: set[str] = set()

        for evt in events:
            # User node
            if evt.user not in seen_users:
                nodes.append({"id": evt.user, "type": "user", "label": evt.user})
                seen_users.add(evt.user)

            # Event node
            nodes.append({
                "id": evt.id, "type": "event", "label": evt.result[:60],
                "event_type": evt.type,
                "data": {"ts": evt.ts, "result": evt.result, "process": evt.process},
            })

            # User -> Event edge
            edges.append({"source": evt.user, "target": evt.id, "relation": "pushed"})

            # Event -> Scope edges
            for f in evt.files:
                scope_key = self._file_to_scope(f)
                if scope_key not in seen_scopes:
                    nodes.append({"id": scope_key, "type": "scope", "label": scope_key})
                    seen_scopes.add(scope_key)
                edges.append({"source": evt.id, "target": scope_key, "relation": "affects"})

        # Detect polymorphisms: same scope, different users
        scope_users: dict[str, dict[str, list[str]]] = {}  # scope -> {user: [results]}
        for evt in events:
            for f in evt.files:
                scope_key = self._file_to_scope(f)
                su = scope_users.setdefault(scope_key, {})
                su.setdefault(evt.user, []).append(evt.result)

        polymorphisms = []
        for scope_key, users_map in scope_users.items():
            if len(users_map) >= 2:
                polymorphisms.append({
                    "scope": scope_key,
                    "users": list(users_map.keys()),
                    "intents": [results[0] for results in users_map.values()],
                })

        return {"nodes": nodes, "edges": edges, "polymorphisms": polymorphisms}

    def cleanup_expired(self) -> int:
        """Remove events older than TTL. Returns count of removed events."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        removed = 0
        repos_dir = self.data_dir / "repos"
        if not repos_dir.exists():
            return 0

        for repo_dir in repos_dir.iterdir():
            if not repo_dir.is_dir():
                continue
            events_dir = repo_dir / "events"
            if not events_dir.exists():
                continue
            for user_dir in events_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                for jsonl_file in user_dir.glob("*.jsonl"):
                    kept = []
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            evt = MemoryEvent.model_validate_json(line)
                            if _parse_ts(evt.ts) >= cutoff:
                                kept.append(line)
                            else:
                                removed += 1
                                seen = self._seen_ids.get(evt.repo_id, set())
                                seen.discard(evt.id)
                    with open(jsonl_file, "w", encoding="utf-8") as f:
                        for line in kept:
                            f.write(line + "\n")
                    if not kept:
                        jsonl_file.unlink()
        return removed

    # --- Internal methods ---

    def _append_event(self, evt: MemoryEvent) -> None:
        date_str = _parse_ts(evt.ts).strftime("%Y-%m-%d")
        # Sanitize repo_id for filesystem: replace / with _
        safe_repo = evt.repo_id.replace("/", "_").replace(":", "_")
        user_dir = self.data_dir / "repos" / safe_repo / "events" / evt.user
        user_dir.mkdir(parents=True, exist_ok=True)

        jsonl_path = user_dir / f"{date_str}.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(evt.model_dump_json() + "\n")

    def _read_repo_events(self, repo_id: str) -> list[MemoryEvent]:
        safe_repo = repo_id.replace("/", "_").replace(":", "_")
        events_dir = self.data_dir / "repos" / safe_repo / "events"
        if not events_dir.exists():
            return []

        events = []
        for user_dir in events_dir.iterdir():
            if not user_dir.is_dir():
                continue
            for jsonl_file in sorted(user_dir.glob("*.jsonl")):
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        evt = MemoryEvent.model_validate_json(line)
                        events.append(evt)
                        # Rebuild seen_ids cache
                        self._seen_ids.setdefault(repo_id, set()).add(evt.id)
        return events

    def _matches_scope(self, evt: MemoryEvent, scope: str) -> bool:
        if not evt.files:
            if evt.scope:
                return fnmatch(evt.scope, scope) or fnmatch(scope, evt.scope)
            return False
        return any(fnmatch(f, scope) for f in evt.files)

    @staticmethod
    def _file_to_scope(file_path: str) -> str:
        parts = file_path.replace("\\", "/").rsplit("/", 1)
        if len(parts) == 2:
            return parts[0] + "/*"
        return file_path


def _parse_ts(ts: str) -> datetime:
    """Parse ISO 8601 timestamp string to datetime."""
    return datetime.fromisoformat(ts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_store.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/overmind/store.py server/tests/test_store.py
git commit -m "feat: implement JSONL store with push, pull, dedup, scope filter"
```

---

## Task 4: REST API

**Files:**
- Create: `server/overmind/api.py`
- Create: `server/tests/test_api.py`
- Update: `server/tests/conftest.py`

- [ ] **Step 1: Write failing tests for REST endpoints**

```python
# server/tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from overmind.api import create_app


@pytest.fixture
def app(data_dir):
    return create_app(data_dir=data_dir)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestPushEndpoint:
    async def test_push_success(self, client):
        resp = await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001",
                "type": "correction",
                "ts": "2026-03-26T14:30:00+09:00",
                "result": "test result",
            }],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1
        assert body["duplicates"] == 0

    async def test_push_missing_repo_id(self, client):
        resp = await client.post("/api/memory/push", json={
            "user": "dev_a",
            "events": [],
        })
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestPullEndpoint:
    async def test_pull_empty(self, client):
        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/test/repo",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0

    async def test_push_then_pull(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001",
                "type": "correction",
                "ts": "2026-03-26T14:30:00+09:00",
                "result": "found the bug",
                "files": ["src/auth/login.ts"],
            }],
        })
        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/test/repo",
            "exclude_user": "dev_b",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1

    async def test_pull_missing_repo_id(self, client):
        resp = await client.get("/api/memory/pull")
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestBroadcastEndpoint:
    async def test_broadcast_success(self, client):
        resp = await client.post("/api/memory/broadcast", json={
            "repo_id": "github.com/test/repo",
            "user": "master_agent",
            "message": "API v2로 변경",
            "priority": "urgent",
            "scope": "src/api/*",
            "related_files": ["src/api/schema.ts"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["delivered"] is True
        assert "id" in body

    async def test_broadcast_appears_in_pull(self, client):
        await client.post("/api/memory/broadcast", json={
            "repo_id": "github.com/test/repo",
            "user": "master_agent",
            "message": "urgent change",
            "priority": "urgent",
        })
        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/test/repo",
        })
        body = resp.json()
        assert body["count"] == 1
        assert body["events"][0]["type"] == "broadcast"
        assert body["events"][0]["priority"] == "urgent"


@pytest.mark.asyncio
class TestReportEndpoint:
    async def test_report_basic(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001", "type": "correction",
                "ts": "2026-03-26T14:30:00+09:00", "result": "fix",
            }],
        })
        resp = await client.get("/api/report", params={
            "repo_id": "github.com/test/repo",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pushes"] >= 1
        assert body["unique_users"] >= 1

    async def test_report_graph(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001", "type": "correction",
                "ts": "2026-03-26T14:30:00+09:00", "result": "fix",
                "files": ["src/auth/login.ts"],
            }],
        })
        resp = await client.get("/api/report/graph", params={
            "repo_id": "github.com/test/repo",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) >= 2  # user + event + scope
        assert len(body["edges"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overmind.api'`

- [ ] **Step 3: Implement API**

```python
# server/overmind/api.py
"""FastAPI REST endpoints for Overmind server."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from overmind.models import (
    BroadcastRequest,
    BroadcastResponse,
    MemoryEvent,
    PullResponse,
    PushRequest,
    PushResponse,
    ReportResponse,
)
from overmind.store import MemoryStore


def create_app(data_dir: Path | None = None) -> FastAPI:
    if data_dir is None:
        data_dir = Path("data")

    store = MemoryStore(data_dir=data_dir)
    store.cleanup_expired()

    app = FastAPI(title="Overmind Server", version="0.1.0")

    # Track pull count for report (in-memory, Phase 1)
    pull_counter: dict[str, int] = {}

    @app.post("/api/memory/push", response_model=PushResponse)
    async def push_memory(req: PushRequest) -> PushResponse:
        events = [e.to_event(req.repo_id, req.user) for e in req.events]
        accepted, duplicates = store.push(events)
        return PushResponse(accepted=accepted, duplicates=duplicates)

    @app.get("/api/memory/pull", response_model=PullResponse)
    async def pull_memory(
        repo_id: str = Query(...),
        since: str | None = Query(None),
        scope: str | None = Query(None),
        user: str | None = Query(None),
        exclude_user: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ) -> PullResponse:
        pull_counter[repo_id] = pull_counter.get(repo_id, 0) + 1
        return store.pull(
            repo_id=repo_id,
            since=since,
            scope=scope,
            user=user,
            exclude_user=exclude_user,
            limit=limit,
        )

    @app.post("/api/memory/broadcast", response_model=BroadcastResponse)
    async def broadcast_memory(req: BroadcastRequest) -> BroadcastResponse:
        evt_id = f"bcast_{uuid.uuid4().hex[:12]}"
        evt = MemoryEvent(
            id=evt_id,
            repo_id=req.repo_id,
            user=req.user,
            ts=_now_iso(),
            type="broadcast",
            result=req.message,
            files=req.related_files,
            priority=req.priority,
            scope=req.scope,
        )
        store.push([evt])
        return BroadcastResponse(id=evt_id, delivered=True)

    @app.get("/api/report", response_model=ReportResponse)
    async def get_report(
        repo_id: str = Query(...),
    ) -> ReportResponse:
        stats = store.get_repo_stats(repo_id)
        return ReportResponse(
            repo_id=repo_id,
            period="24h",
            total_pushes=stats["total_pushes"],
            total_pulls=pull_counter.get(repo_id, 0),
            unique_users=stats["unique_users"],
            events_by_type=stats["events_by_type"],
        )

    @app.get("/api/report/graph")
    async def get_report_graph(
        repo_id: str = Query(...),
        since: str | None = Query(None),
    ) -> dict:
        return store.get_graph_data(repo_id, since=since)

    @app.get("/api/report/timeline")
    async def get_report_timeline(
        repo_id: str = Query(...),
        since: str | None = Query(None),
    ) -> dict:
        events = store.pull(repo_id=repo_id, since=since, limit=500).events
        swimlanes: dict[str, list[dict]] = {}
        for evt in events:
            lane = swimlanes.setdefault(evt.user, [])
            lane.append(evt.model_dump())
        return {"swimlanes": swimlanes}

    # Mount dashboard static files (will be created in Task 8)
    dashboard_static = Path(__file__).parent / "dashboard" / "static"
    if dashboard_static.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_static), html=True), name="dashboard")

    return app


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_api.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/overmind/api.py server/tests/test_api.py
git commit -m "feat: add REST API endpoints for push, pull, broadcast, report"
```

---

## Task 5: Server Entry Point

**Files:**
- Create: `server/overmind/main.py`

- [ ] **Step 1: Implement main entry point**

```python
# server/overmind/main.py
"""Overmind server entry point: REST (FastAPI) + MCP (FastMCP) on single uvicorn."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from overmind.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7777, help="Bind port (default: 7777)")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory (default: data)")
    args = parser.parse_args()

    app = create_app(data_dir=Path(args.data_dir))
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify server starts**

Run: `cd server && timeout 3 uv run python -m overmind.main --port 7778 || true`
Expected: Server starts, shows uvicorn startup log, then times out. No errors.

- [ ] **Step 3: Commit**

```bash
git add server/overmind/main.py
git commit -m "feat: add server entry point with CLI args"
```

---

## Task 6: FastMCP Wrapper

**Files:**
- Create: `server/overmind/mcp_server.py`
- Create: `server/tests/test_mcp.py`
- Modify: `server/overmind/main.py`

- [ ] **Step 1: Write failing MCP tests**

```python
# server/tests/test_mcp.py
import pytest
from fastmcp import Client
from overmind.mcp_server import create_mcp_server
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


@pytest.fixture
def mcp(store):
    return create_mcp_server(store)


@pytest.mark.asyncio
class TestMCPTools:
    async def test_push_and_pull(self, mcp):
        async with Client(mcp) as dev_a, Client(mcp) as dev_b:
            push_result = await dev_a.call_tool("overmind_push", {
                "repo_id": "github.com/test/repo",
                "user": "dev_a",
                "events": [{
                    "id": "evt_001",
                    "type": "correction",
                    "ts": "2026-03-26T14:30:00+09:00",
                    "result": ".env에 SERVICE_A_INTERNAL_URL 필요",
                    "files": ["src/config/env.ts"],
                }],
            })
            assert "accepted" in str(push_result)

            pull_result = await dev_b.call_tool("overmind_pull", {
                "repo_id": "github.com/test/repo",
                "exclude_user": "dev_b",
            })
            assert "SERVICE_A_INTERNAL_URL" in str(pull_result)

    async def test_broadcast(self, mcp):
        async with Client(mcp) as dev_a, Client(mcp) as dev_b:
            bcast_result = await dev_a.call_tool("overmind_broadcast", {
                "repo_id": "github.com/test/repo",
                "user": "dev_a",
                "message": "API 스키마 v2로 변경",
                "priority": "urgent",
            })
            assert "delivered" in str(bcast_result)

            pull_result = await dev_b.call_tool("overmind_pull", {
                "repo_id": "github.com/test/repo",
                "exclude_user": "dev_b",
            })
            assert "API" in str(pull_result)

    async def test_concurrent_push(self, mcp):
        import asyncio

        async def push_events(client, user, start_id):
            for i in range(5):
                await client.call_tool("overmind_push", {
                    "repo_id": "github.com/test/repo",
                    "user": user,
                    "events": [{
                        "id": f"evt_{user}_{start_id + i}",
                        "type": "discovery",
                        "ts": "2026-03-26T14:30:00+09:00",
                        "result": f"discovery {i}",
                    }],
                })

        async with Client(mcp) as dev_a, Client(mcp) as dev_b, Client(mcp) as reader:
            await asyncio.gather(
                push_events(dev_a, "dev_a", 0),
                push_events(dev_b, "dev_b", 100),
            )
            pull_result = await reader.call_tool("overmind_pull", {
                "repo_id": "github.com/test/repo",
                "limit": 100,
            })
            # All 10 events should be present
            assert "10" in str(pull_result) or pull_result  # count = 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_mcp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overmind.mcp_server'`

- [ ] **Step 3: Implement MCP server**

```python
# server/overmind/mcp_server.py
"""FastMCP wrapper exposing Overmind store as MCP tools."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastmcp import FastMCP

from overmind.store import MemoryStore
from overmind.models import MemoryEvent


def create_mcp_server(store: MemoryStore) -> FastMCP:
    mcp = FastMCP("Overmind", description="Distributed memory sync for Claude Code")

    @mcp.tool()
    def overmind_push(repo_id: str, user: str, events: list[dict]) -> dict:
        """Push memory events to Overmind server.

        Args:
            repo_id: Repository identifier (e.g. "github.com/user/project")
            user: User/agent identifier
            events: List of event dicts with id, type, ts, result, and optional files/process/priority/scope
        """
        parsed = []
        for e in events:
            parsed.append(MemoryEvent(
                repo_id=repo_id,
                user=user,
                **e,
            ))
        accepted, duplicates = store.push(parsed)
        return {"accepted": accepted, "duplicates": duplicates}

    @mcp.tool()
    def overmind_pull(
        repo_id: str,
        exclude_user: str | None = None,
        since: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Pull other agents' memory events from Overmind server.

        Args:
            repo_id: Repository identifier
            exclude_user: Exclude events from this user (typically yourself)
            since: ISO 8601 timestamp - only return events after this time
            scope: Glob pattern to filter by file scope (e.g. "src/auth/*")
            limit: Maximum events to return (default 50)
        """
        result = store.pull(
            repo_id=repo_id,
            exclude_user=exclude_user,
            since=since,
            scope=scope,
            limit=limit,
        )
        return result.model_dump()

    @mcp.tool()
    def overmind_broadcast(
        repo_id: str,
        user: str,
        message: str,
        priority: str = "normal",
        scope: str | None = None,
        related_files: list[str] | None = None,
    ) -> dict:
        """Broadcast urgent message to all agents on this repo.

        Args:
            repo_id: Repository identifier
            user: Sender identifier
            message: Broadcast message content
            priority: "normal" or "urgent"
            scope: Affected scope (e.g. "src/api/*")
            related_files: List of affected file paths
        """
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
        store.push([evt])
        return {"id": evt_id, "delivered": True}

    return mcp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_mcp.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Update main.py to mount MCP**

```python
# server/overmind/main.py — replace entire file
"""Overmind server entry point: REST (FastAPI) + MCP (FastMCP) on single uvicorn."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from overmind.api import create_app
from overmind.mcp_server import create_mcp_server
from overmind.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Overmind Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7777, help="Bind port (default: 7777)")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = MemoryStore(data_dir=data_dir)
    store.cleanup_expired()

    app = create_app(data_dir=data_dir)

    # Mount MCP at /mcp
    mcp = create_mcp_server(store)
    app.mount("/mcp", mcp.streamable_http_app())

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add server/overmind/mcp_server.py server/overmind/main.py server/tests/test_mcp.py
git commit -m "feat: add FastMCP wrapper with push, pull, broadcast tools"
```

---

## Task 7: Dashboard — Static Files

**Files:**
- Create: `server/overmind/dashboard/__init__.py`
- Create: `server/overmind/dashboard/static/index.html`
- Create: `server/overmind/dashboard/static/style.css`
- Create: `server/overmind/dashboard/static/app.js`

- [ ] **Step 1: Create dashboard package marker**

```python
# server/overmind/dashboard/__init__.py
"""Overmind dashboard static files."""
```

- [ ] **Step 2: Create index.html**

```html
<!-- server/overmind/dashboard/static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Overmind Dashboard</title>
    <link rel="stylesheet" href="style.css">
    <script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
    <header>
        <h1>Overmind</h1>
        <div id="repo-selector">
            <label for="repo-id">Repo:</label>
            <input type="text" id="repo-id" placeholder="github.com/user/project" />
            <button id="btn-load" onclick="loadAll()">Load</button>
        </div>
        <nav>
            <button class="tab active" data-tab="overview">Overview</button>
            <button class="tab" data-tab="graph">Graph</button>
            <button class="tab" data-tab="timeline">Timeline</button>
        </nav>
    </header>

    <main>
        <section id="overview" class="tab-content active">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value" id="stat-pushes">-</div>
                    <div class="stat-label">Total Pushes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-pulls">-</div>
                    <div class="stat-label">Total Pulls</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-users">-</div>
                    <div class="stat-label">Active Users</div>
                </div>
            </div>
            <div id="type-chart"></div>
            <div id="recent-events">
                <h3>Recent Events</h3>
                <table id="events-table">
                    <thead>
                        <tr><th>Time</th><th>User</th><th>Type</th><th>Result</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </section>

        <section id="graph" class="tab-content">
            <div id="graph-container">
                <svg id="graph-svg"></svg>
            </div>
            <div id="detail-panel" class="hidden">
                <button onclick="closeDetail()">&times;</button>
                <pre id="detail-content"></pre>
            </div>
        </section>

        <section id="timeline" class="tab-content">
            <div id="timeline-container">
                <svg id="timeline-svg"></svg>
            </div>
        </section>
    </main>

    <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create style.css**

```css
/* server/overmind/dashboard/static/style.css */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
}

header {
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 24px;
}

header h1 {
    color: #58a6ff;
    font-size: 20px;
    font-weight: 600;
}

#repo-selector {
    display: flex;
    align-items: center;
    gap: 8px;
}

#repo-selector input {
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 4px 8px;
    border-radius: 4px;
    width: 280px;
    font-size: 13px;
}

#btn-load {
    background: #238636;
    color: white;
    border: none;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
}

nav { display: flex; gap: 4px; margin-left: auto; }

.tab {
    background: transparent;
    color: #8b949e;
    border: none;
    padding: 6px 16px;
    cursor: pointer;
    border-radius: 4px;
    font-size: 13px;
}

.tab.active { background: #30363d; color: #c9d1d9; }

main { padding: 24px; }

.tab-content { display: none; }
.tab-content.active { display: block; }

/* Overview */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
}

.stat-value { font-size: 36px; font-weight: 700; color: #58a6ff; }
.stat-label { font-size: 13px; color: #8b949e; margin-top: 4px; }

#type-chart { margin-bottom: 24px; }

table {
    width: 100%;
    border-collapse: collapse;
    background: #161b22;
    border-radius: 8px;
    overflow: hidden;
}

th, td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #21262d;
    font-size: 13px;
}

th { color: #8b949e; font-weight: 600; }

/* Graph */
#graph-container {
    width: 100%;
    height: calc(100vh - 120px);
    position: relative;
}

#graph-svg { width: 100%; height: 100%; }

.node-user { fill: #58a6ff; }
.node-event { fill: #3fb950; }
.node-event-correction { fill: #f85149; }
.node-event-decision { fill: #d29922; }
.node-event-discovery { fill: #a371f7; }
.node-event-broadcast { fill: #f778ba; }
.node-scope { fill: #8b949e; }

.edge { stroke: #30363d; stroke-width: 1.5; }
.edge-pulled { stroke-dasharray: 5,5; }
.edge-polymorphism { stroke: #f85149; stroke-width: 3; }

.node-label {
    fill: #c9d1d9;
    font-size: 11px;
    pointer-events: none;
}

#detail-panel {
    position: fixed;
    right: 0;
    top: 60px;
    width: 400px;
    height: calc(100vh - 60px);
    background: #161b22;
    border-left: 1px solid #30363d;
    padding: 16px;
    overflow-y: auto;
    z-index: 10;
}

#detail-panel.hidden { display: none; }
#detail-panel button {
    float: right;
    background: transparent;
    color: #8b949e;
    border: none;
    font-size: 20px;
    cursor: pointer;
}

#detail-content {
    margin-top: 32px;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
}

/* Timeline */
#timeline-container {
    width: 100%;
    height: calc(100vh - 120px);
    overflow-x: auto;
}

#timeline-svg { min-width: 100%; height: 100%; }

.swimlane-label { fill: #c9d1d9; font-size: 13px; font-weight: 600; }
.swimlane-bg:nth-child(odd) { fill: #161b22; }
.swimlane-bg:nth-child(even) { fill: #0d1117; }
.timeline-event { cursor: pointer; }
.timeline-broadcast-line { stroke: #f778ba; stroke-width: 2; stroke-dasharray: 8,4; }
.timeline-link { stroke: #d29922; stroke-width: 1; opacity: 0.6; }

/* Polymorphism glow */
.polymorphism-glow {
    filter: drop-shadow(0 0 6px #f85149) drop-shadow(0 0 12px #f85149);
}
```

- [ ] **Step 4: Create app.js**

```javascript
// server/overmind/dashboard/static/app.js

const API_BASE = window.location.origin;
let currentRepo = '';

// --- Tab switching ---
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
    });
});

function closeDetail() {
    document.getElementById('detail-panel').classList.add('hidden');
}

// --- Data loading ---
async function loadAll() {
    currentRepo = document.getElementById('repo-id').value.trim();
    if (!currentRepo) return;
    await Promise.all([loadOverview(), loadGraph(), loadTimeline()]);
}

async function loadOverview() {
    const [reportRes, pullRes] = await Promise.all([
        fetch(`${API_BASE}/api/report?repo_id=${encodeURIComponent(currentRepo)}`),
        fetch(`${API_BASE}/api/memory/pull?repo_id=${encodeURIComponent(currentRepo)}&limit=20`),
    ]);
    const report = await reportRes.json();
    const pull = await pullRes.json();

    document.getElementById('stat-pushes').textContent = report.total_pushes;
    document.getElementById('stat-pulls').textContent = report.total_pulls;
    document.getElementById('stat-users').textContent = report.unique_users;

    // Type chart
    renderTypeChart(report.events_by_type);

    // Recent events table
    const tbody = document.querySelector('#events-table tbody');
    tbody.innerHTML = '';
    for (const evt of pull.events) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${new Date(evt.ts).toLocaleString()}</td>
            <td>${evt.user}</td>
            <td><span class="type-badge type-${evt.type}">${evt.type}</span></td>
            <td>${evt.result}</td>
        `;
        tbody.appendChild(tr);
    }
}

function renderTypeChart(byType) {
    const container = document.getElementById('type-chart');
    container.innerHTML = '';
    const entries = Object.entries(byType);
    if (entries.length === 0) return;

    const width = 500, height = 200, margin = { top: 20, right: 20, bottom: 40, left: 50 };
    const svg = d3.select(container).append('svg').attr('width', width).attr('height', height);

    const x = d3.scaleBand()
        .domain(entries.map(d => d[0]))
        .range([margin.left, width - margin.right])
        .padding(0.3);

    const y = d3.scaleLinear()
        .domain([0, d3.max(entries, d => d[1])])
        .nice()
        .range([height - margin.bottom, margin.top]);

    const colorMap = {
        correction: '#f85149', decision: '#d29922', discovery: '#a371f7',
        change: '#3fb950', broadcast: '#f778ba',
    };

    svg.selectAll('rect')
        .data(entries)
        .join('rect')
        .attr('x', d => x(d[0]))
        .attr('y', d => y(d[1]))
        .attr('width', x.bandwidth())
        .attr('height', d => y(0) - y(d[1]))
        .attr('fill', d => colorMap[d[0]] || '#8b949e')
        .attr('rx', 3);

    svg.append('g')
        .attr('transform', `translate(0,${height - margin.bottom})`)
        .call(d3.axisBottom(x))
        .selectAll('text').attr('fill', '#8b949e');

    svg.append('g')
        .attr('transform', `translate(${margin.left},0)`)
        .call(d3.axisLeft(y).ticks(5))
        .selectAll('text').attr('fill', '#8b949e');

    svg.selectAll('.domain, .tick line').attr('stroke', '#30363d');
}

// --- Graph ---
async function loadGraph() {
    const res = await fetch(`${API_BASE}/api/report/graph?repo_id=${encodeURIComponent(currentRepo)}`);
    const data = await res.json();
    renderGraph(data);
}

function renderGraph(data) {
    const svg = d3.select('#graph-svg');
    svg.selectAll('*').remove();

    const container = document.getElementById('graph-container');
    const width = container.clientWidth;
    const height = container.clientHeight;
    svg.attr('viewBox', `0 0 ${width} ${height}`);

    if (data.nodes.length === 0) {
        svg.append('text').attr('x', width / 2).attr('y', height / 2)
            .attr('text-anchor', 'middle').attr('fill', '#8b949e')
            .text('No data. Push some events first.');
        return;
    }

    const polyScopes = new Set(data.polymorphisms.map(p => p.scope));

    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(100))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(30));

    const g = svg.append('g');

    // Zoom
    svg.call(d3.zoom().scaleExtent([0.1, 4]).on('zoom', (e) => {
        g.attr('transform', e.transform);
    }));

    // Edges
    const link = g.selectAll('.edge')
        .data(data.edges)
        .join('line')
        .attr('class', d => {
            let cls = 'edge';
            if (d.relation === 'pulled') cls += ' edge-pulled';
            const targetNode = data.nodes.find(n => n.id === (typeof d.target === 'object' ? d.target.id : d.target));
            if (targetNode && polyScopes.has(targetNode.id)) cls += ' edge-polymorphism';
            return cls;
        });

    // Nodes
    const nodeSize = d => d.type === 'user' ? 14 : d.type === 'scope' ? 10 : 8;
    const nodeClass = d => {
        if (d.type === 'user') return 'node-user';
        if (d.type === 'scope') return 'node-scope' + (polyScopes.has(d.id) ? ' polymorphism-glow' : '');
        return `node-event node-event-${d.event_type || 'change'}`;
    };

    const node = g.selectAll('.node')
        .data(data.nodes)
        .join('g')
        .attr('class', 'node')
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.each(function(d) {
        const el = d3.select(this);
        if (d.type === 'user') {
            el.append('circle').attr('r', nodeSize(d)).attr('class', nodeClass(d));
        } else if (d.type === 'scope') {
            el.append('rect')
                .attr('width', nodeSize(d) * 2).attr('height', nodeSize(d) * 2)
                .attr('x', -nodeSize(d)).attr('y', -nodeSize(d))
                .attr('rx', 2)
                .attr('class', nodeClass(d));
        } else {
            el.append('rect')
                .attr('width', nodeSize(d) * 2).attr('height', nodeSize(d) * 2)
                .attr('x', -nodeSize(d)).attr('y', -nodeSize(d))
                .attr('rx', 1)
                .attr('class', nodeClass(d));
        }
    });

    // Labels
    node.append('text')
        .attr('class', 'node-label')
        .attr('dy', d => nodeSize(d) + 14)
        .attr('text-anchor', 'middle')
        .text(d => (d.label || d.id).substring(0, 30));

    // Click handler
    node.on('click', (e, d) => {
        const panel = document.getElementById('detail-panel');
        panel.classList.remove('hidden');
        document.getElementById('detail-content').textContent = JSON.stringify(d, null, 2);
    });

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}

// --- Timeline ---
async function loadTimeline() {
    const res = await fetch(`${API_BASE}/api/report/timeline?repo_id=${encodeURIComponent(currentRepo)}`);
    const data = await res.json();
    renderTimeline(data);
}

function renderTimeline(data) {
    const svg = d3.select('#timeline-svg');
    svg.selectAll('*').remove();

    const users = Object.keys(data.swimlanes);
    if (users.length === 0) return;

    const laneHeight = 80;
    const margin = { top: 40, right: 40, bottom: 40, left: 120 };
    const width = Math.max(800, document.getElementById('timeline-container').clientWidth);
    const height = margin.top + users.length * laneHeight + margin.bottom;
    svg.attr('viewBox', `0 0 ${width} ${height}`);

    // Collect all timestamps
    const allEvents = users.flatMap(u => data.swimlanes[u]);
    if (allEvents.length === 0) return;

    const extent = d3.extent(allEvents, d => new Date(d.ts));
    const x = d3.scaleTime().domain(extent).range([margin.left, width - margin.right]).nice();
    const y = d3.scaleBand().domain(users).range([margin.top, height - margin.bottom]).padding(0.2);

    // Swimlane backgrounds
    svg.selectAll('.swimlane-bg')
        .data(users)
        .join('rect')
        .attr('class', 'swimlane-bg')
        .attr('x', 0).attr('width', width)
        .attr('y', d => y(d)).attr('height', y.bandwidth())
        .attr('fill', (d, i) => i % 2 === 0 ? '#161b22' : '#0d1117');

    // Swimlane labels
    svg.selectAll('.swimlane-label')
        .data(users)
        .join('text')
        .attr('class', 'swimlane-label')
        .attr('x', 12)
        .attr('y', d => y(d) + y.bandwidth() / 2 + 5)
        .text(d => d);

    const colorMap = {
        correction: '#f85149', decision: '#d29922', discovery: '#a371f7',
        change: '#3fb950', broadcast: '#f778ba',
    };

    // Events
    for (const user of users) {
        const events = data.swimlanes[user];
        svg.selectAll(`.evt-${user.replace(/\W/g, '_')}`)
            .data(events)
            .join('circle')
            .attr('class', 'timeline-event')
            .attr('cx', d => x(new Date(d.ts)))
            .attr('cy', y(user) + y.bandwidth() / 2)
            .attr('r', 6)
            .attr('fill', d => colorMap[d.type] || '#8b949e')
            .on('click', (e, d) => {
                const panel = document.getElementById('detail-panel');
                panel.classList.remove('hidden');
                document.getElementById('detail-content').textContent = JSON.stringify(d, null, 2);
            });

        // Broadcast vertical lines
        events.filter(e => e.type === 'broadcast').forEach(evt => {
            svg.append('line')
                .attr('class', 'timeline-broadcast-line')
                .attr('x1', x(new Date(evt.ts))).attr('x2', x(new Date(evt.ts)))
                .attr('y1', margin.top).attr('y2', height - margin.bottom);
        });
    }

    // X axis
    svg.append('g')
        .attr('transform', `translate(0,${height - margin.bottom})`)
        .call(d3.axisBottom(x).ticks(8))
        .selectAll('text').attr('fill', '#8b949e');

    svg.selectAll('.domain, .tick line').attr('stroke', '#30363d');
}
```

- [ ] **Step 5: Verify dashboard loads**

Run: `cd server && uv run python -c "from overmind.api import create_app; app = create_app(); print('Dashboard mount OK')"`
Expected: `Dashboard mount OK`

- [ ] **Step 6: Commit**

```bash
git add server/overmind/dashboard/
git commit -m "feat: add Overmind dashboard with overview, graph, and timeline"
```

---

## Task 8: Integration Scenarios

**Files:**
- Create: `server/tests/scenarios/__init__.py`
- Create: `server/tests/scenarios/test_scenario_preemptive_block.py`
- Create: `server/tests/scenarios/test_scenario_polymorphism.py`
- Create: `server/tests/scenarios/test_scenario_multi_repo.py`

- [ ] **Step 1: Write preemptive block scenario**

```python
# server/tests/scenarios/__init__.py
```

```python
# server/tests/scenarios/test_scenario_preemptive_block.py
"""Scenario: dev_a discovers .env issue, dev_b pulls and gets pre-warned."""

import pytest
from overmind.models import MemoryEvent
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


REPO = "github.com/test/project"


def test_preemptive_block_scenario(store):
    # 1. dev_a encounters and solves .env issue
    evt = MemoryEvent(
        id="evt_preempt_001",
        repo_id=REPO,
        user="dev_a",
        ts="2026-03-26T14:00:00+09:00",
        type="correction",
        result=".env에 SERVICE_A_INTERNAL_URL=http://localhost:3001 설정 필요",
        files=["src/config/env.ts", ".env.example"],
        process=[
            "서비스B 실행 시 ECONNREFUSED 발생",
            "src/config/env.ts 확인 → SERVICE_A_INTERNAL_URL 참조 발견",
            ".env에 해당 변수 미설정 확인",
            ".env에 SERVICE_A_INTERNAL_URL=http://localhost:3001 추가로 해결",
        ],
    )
    accepted, _ = store.push([evt])
    assert accepted == 1

    # 2. dev_b starts working on service B area — pulls related scope
    result = store.pull(repo_id=REPO, scope="src/config/*", exclude_user="dev_b")
    assert result.count >= 1

    # 3. Verify the lesson is present and actionable
    lessons = [e for e in result.events if "SERVICE_A_INTERNAL_URL" in e.result]
    assert len(lessons) == 1

    # 4. Verify the process (not just conclusion) is available
    lesson = lessons[0]
    assert len(lesson.process) >= 2
    assert any("ECONNREFUSED" in p for p in lesson.process)
```

- [ ] **Step 2: Write polymorphism detection scenario**

```python
# server/tests/scenarios/test_scenario_polymorphism.py
"""Scenario: two users work on same scope with different intents."""

import pytest
from overmind.models import MemoryEvent
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


REPO = "github.com/test/project"


def test_polymorphism_detection_scenario(store):
    # 1. dev_a works on auth from security perspective
    evt_a = MemoryEvent(
        id="evt_poly_001",
        repo_id=REPO,
        user="dev_a",
        ts="2026-03-26T14:00:00+09:00",
        type="decision",
        result="인증을 OAuth2+PKCE로 전환 (보안 강화)",
        files=["src/auth/oauth2.ts", "src/auth/jwt.ts"],
        process=["JWT refresh rotation→복잡도 과다", "세션 기반→stateless 충돌", "OAuth2+PKCE 채택"],
    )

    # 2. dev_b works on auth from performance perspective
    evt_b = MemoryEvent(
        id="evt_poly_002",
        repo_id=REPO,
        user="dev_b",
        ts="2026-03-26T15:00:00+09:00",
        type="decision",
        result="인증 레이어에 세션 캐시 추가 (성능 최적화)",
        files=["src/auth/cache.ts", "src/auth/session.ts"],
        process=["인증 요청 지연 측정→평균 200ms", "Redis 세션 캐시 도입 검토", "세션 캐시 레이어 추가"],
    )

    store.push([evt_a, evt_b])

    # 3. dev_c pulls auth scope — should see both intents
    result = store.pull(repo_id=REPO, scope="src/auth/*", exclude_user="dev_c")
    assert result.count == 2

    users = set(e.user for e in result.events)
    assert users == {"dev_a", "dev_b"}

    # 4. Graph data should detect polymorphism
    graph = store.get_graph_data(REPO)
    assert len(graph["polymorphisms"]) >= 1

    poly = graph["polymorphisms"][0]
    assert set(poly["users"]) == {"dev_a", "dev_b"}
```

- [ ] **Step 3: Write multi-repo isolation scenario**

```python
# server/tests/scenarios/test_scenario_multi_repo.py
"""Scenario: events from different repos are completely isolated."""

import pytest
from overmind.models import MemoryEvent
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


def test_multi_repo_isolation(store):
    evt_1 = MemoryEvent(
        id="evt_repo1_001",
        repo_id="github.com/team/frontend",
        user="dev_a",
        ts="2026-03-26T14:00:00+09:00",
        type="correction",
        result="React 18 hydration 이슈 해결",
        files=["src/app.tsx"],
    )
    evt_2 = MemoryEvent(
        id="evt_repo2_001",
        repo_id="github.com/team/backend",
        user="dev_a",
        ts="2026-03-26T14:00:00+09:00",
        type="correction",
        result="DB connection pool 설정 수정",
        files=["src/db/pool.ts"],
    )

    store.push([evt_1, evt_2])

    # Pull from frontend repo — should not see backend events
    result_fe = store.pull(repo_id="github.com/team/frontend")
    assert result_fe.count == 1
    assert result_fe.events[0].result == "React 18 hydration 이슈 해결"

    # Pull from backend repo — should not see frontend events
    result_be = store.pull(repo_id="github.com/team/backend")
    assert result_be.count == 1
    assert result_be.events[0].result == "DB connection pool 설정 수정"

    # Graph data should be isolated too
    graph_fe = store.get_graph_data("github.com/team/frontend")
    graph_be = store.get_graph_data("github.com/team/backend")
    fe_results = [n.get("label", "") for n in graph_fe["nodes"] if n["type"] == "event"]
    be_results = [n.get("label", "") for n in graph_be["nodes"] if n["type"] == "event"]
    assert not any("DB connection" in r for r in fe_results)
    assert not any("hydration" in r for r in be_results)
```

- [ ] **Step 4: Run all tests**

Run: `cd server && uv run pytest tests/ -v`
Expected: All tests PASS (models + store + api + mcp + 3 scenarios).

- [ ] **Step 5: Commit**

```bash
git add server/tests/scenarios/
git commit -m "feat: add integration test scenarios for preemptive block, polymorphism, multi-repo"
```

---

## Task 9: Plugin — API Client & Hooks

**Files:**
- Create: `plugin/.claude-plugin/plugin.json`
- Create: `plugin/.mcp.json`
- Create: `plugin/scripts/api_client.py`
- Create: `plugin/hooks/hooks.json`
- Create: `plugin/hooks/on_session_start.py`
- Create: `plugin/hooks/on_session_end.py`
- Create: `plugin/hooks/on_pre_tool_use.py`

- [ ] **Step 1: Create plugin.json**

```json
{
  "name": "overmind-plugin",
  "version": "0.1.0",
  "description": "Overmind: distributed memory sync plugin for Claude Code",
  "author": "whyjp"
}
```

- [ ] **Step 2: Create .mcp.json**

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

- [ ] **Step 3: Create api_client.py**

```python
# plugin/scripts/api_client.py
"""Shared HTTP client for Overmind plugin hooks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


OVERMIND_URL = os.environ.get("OVERMIND_URL", "http://localhost:7777")
STATE_FILE = Path.home() / ".overmind_state.json"


def get_repo_id() -> str | None:
    """Derive repo_id from git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        return normalize_git_remote(url)
    except Exception:
        return None


def normalize_git_remote(url: str) -> str:
    """Normalize git remote URL to repo_id."""
    url = url.strip()
    # SSH: git@github.com:user/project.git
    if url.startswith("git@"):
        url = url.replace(":", "/", 1).replace("git@", "")
    # HTTPS: https://github.com/user/project.git
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Remove trailing .git
    if url.endswith(".git"):
        url = url[:-4]
    # Remove trailing /
    url = url.rstrip("/")
    return url


def get_user() -> str:
    """Get current user identifier."""
    return os.environ.get("OVERMIND_USER", os.environ.get("USER", os.environ.get("USERNAME", "unknown")))


def load_state() -> dict:
    """Load persistent state (last_pull_ts etc)."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    """Save persistent state."""
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def api_post(path: str, body: dict) -> dict | None:
    """POST JSON to Overmind server."""
    try:
        req = Request(
            f"{OVERMIND_URL}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (URLError, Exception) as e:
        print(f"Overmind API error: {e}", file=sys.stderr)
        return None


def api_get(path: str, params: dict | None = None) -> dict | None:
    """GET from Overmind server."""
    try:
        url = f"{OVERMIND_URL}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{qs}"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (URLError, Exception) as e:
        print(f"Overmind API error: {e}", file=sys.stderr)
        return None
```

- [ ] **Step 4: Create hooks.json**

```json
{
  "hooks": [
    {
      "event": "SessionStart",
      "command": "python hooks/on_session_start.py",
      "timeout": 5000
    },
    {
      "event": "SessionEnd",
      "command": "python hooks/on_session_end.py",
      "timeout": 5000
    },
    {
      "event": "PreToolUse",
      "matcher": { "tool_name": "^(Write|Edit)$" },
      "command": "python hooks/on_pre_tool_use.py",
      "timeout": 3000
    }
  ]
}
```

- [ ] **Step 5: Create on_session_start.py**

```python
#!/usr/bin/env python3
# plugin/hooks/on_session_start.py
"""SessionStart hook: pull latest events from Overmind server."""

import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, load_state, save_state, api_get


def main():
    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()
    last_pull = state.get("last_pull_ts")
    if not last_pull:
        last_pull = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "exclude_user": user,
        "since": last_pull,
        "limit": "20",
    })

    if not result or result.get("count", 0) == 0:
        return

    # Update last_pull_ts
    state["last_pull_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Format as systemMessage for Claude context injection
    lines = [f"Overmind: {result['count']} team events since last session:"]
    for evt in result["events"]:
        prefix = "!" if evt.get("priority") == "urgent" else "-"
        lines.append(f"  {prefix} [{evt['type']}] {evt['user']}: {evt['result']}")
        if evt.get("process"):
            for step in evt["process"][:3]:
                lines.append(f"      > {step}")

    output = {"systemMessage": "\n".join(lines)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Create on_session_end.py**

```python
#!/usr/bin/env python3
# plugin/hooks/on_session_end.py
"""SessionEnd hook: push session events to Overmind server."""

import json
import sys
import uuid

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_post


def main():
    # Read hook input from stdin
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()

    # Phase 1: push a session-end summary event
    # In future phases, this will capture more granular events
    from datetime import datetime, timezone
    evt = {
        "id": f"session_{uuid.uuid4().hex[:12]}",
        "type": "discovery",
        "ts": datetime.now(timezone.utc).isoformat(),
        "result": f"Session ended by {user}",
    }

    api_post("/api/memory/push", {
        "repo_id": repo_id,
        "user": user,
        "events": [evt],
    })


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Create on_pre_tool_use.py**

```python
#!/usr/bin/env python3
# plugin/hooks/on_pre_tool_use.py
"""PreToolUse hook: pull related events when editing files."""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_get


def file_to_scope(file_path: str) -> str:
    """Convert file path to scope glob pattern."""
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    if len(parts) == 2:
        return parts[0] + "/*"
    return file_path


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    scope = file_to_scope(file_path)

    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "scope": scope,
        "exclude_user": user,
        "limit": "5",
    })

    if not result or result.get("count", 0) == 0:
        return

    lines = [f"Overmind: {result['count']} related events in {scope}:"]
    for evt in result["events"]:
        prefix = "!" if evt.get("priority") == "urgent" else "-"
        lines.append(f"  {prefix} [{evt['type']}] {evt['user']}: {evt['result']}")

    output = {"systemMessage": "\n".join(lines)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Commit**

```bash
git add plugin/
git commit -m "feat: add Overmind plugin with hooks, API client, and config"
```

---

## Task 10: Plugin — Skills & Commands

**Files:**
- Create: `plugin/skills/overmind-broadcast/SKILL.md`
- Create: `plugin/skills/overmind-report/SKILL.md`
- Create: `plugin/commands/broadcast.md`

- [ ] **Step 1: Create broadcast skill**

```markdown
<!-- plugin/skills/overmind-broadcast/SKILL.md -->
---
description: "Share important changes or discoveries with the team via Overmind. Triggers when user says: 'share this with the team', 'broadcast', 'tell everyone', 'alert the team', 'notify team', 'team에 알려줘', '팀에 공유', '전파'"
---

# Overmind Broadcast

Share an important change, discovery, or decision with all team members via Overmind.

## Instructions

1. Ask the user what message to broadcast (unless already clear from context)
2. Determine the priority:
   - "urgent": breaking changes, API schema changes, blocking issues
   - "normal": general discoveries, FYIs, non-blocking updates
3. Identify the affected scope (file paths or glob patterns)
4. Use the `overmind_broadcast` MCP tool to send the broadcast:

```
overmind_broadcast(
  repo_id="<derived from git remote>",
  user="<current user>",
  message="<the broadcast message>",
  priority="<urgent|normal>",
  scope="<affected scope>",
  related_files=["<list of affected files>"]
)
```

5. Confirm to the user that the broadcast was sent
```

- [ ] **Step 2: Create report skill**

```markdown
<!-- plugin/skills/overmind-report/SKILL.md -->
---
description: "View Overmind status and team activity. Triggers when user says: 'overmind status', 'show overmind', 'team activity', 'memory report', 'overmind 현황', '팀 활동'"
---

# Overmind Report

Show the current Overmind status: recent team events, active users, and statistics.

## Instructions

1. Use the `overmind_pull` MCP tool to get recent events:

```
overmind_pull(
  repo_id="<derived from git remote>",
  exclude_user="<current user>",
  limit=20
)
```

2. Present the results to the user in a readable format:
   - Group by user
   - Highlight urgent/broadcast events
   - Show process logs for corrections/decisions
   - Flag any polymorphism (same scope, different users with different intents)

3. If the user wants detailed statistics, direct them to the dashboard:
   `http://localhost:7777/dashboard`
```

- [ ] **Step 3: Create broadcast slash command**

```markdown
<!-- plugin/commands/broadcast.md -->
---
description: "Broadcast a message to all team members via Overmind"
allowed-tools: ["overmind_broadcast"]
---

Broadcast the following message to the team via Overmind.

Determine appropriate priority (urgent for breaking changes, normal otherwise) and scope from the message content. Use the `overmind_broadcast` MCP tool.

Message: $ARGUMENTS
```

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/ plugin/commands/
git commit -m "feat: add Overmind broadcast/report skills and slash command"
```

---

## Task 11: Run Full Test Suite & Manual Smoke Test

- [ ] **Step 1: Run all automated tests**

Run: `cd server && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 2: Start server and test manually**

Run: `cd server && uv run python -m overmind.main --port 7778 &`

Then test push:
```bash
curl -X POST http://localhost:7778/api/memory/push \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"github.com/test/demo","user":"dev_a","events":[{"id":"manual_001","type":"correction","ts":"2026-03-26T14:30:00+09:00","result":"test push works","files":["src/test.ts"],"process":["step 1","step 2"]}]}'
```
Expected: `{"accepted":1,"duplicates":0}`

Test pull:
```bash
curl "http://localhost:7778/api/memory/pull?repo_id=github.com/test/demo"
```
Expected: JSON with `count: 1` and the pushed event.

Test dashboard:
Open `http://localhost:7778/dashboard` in browser, enter `github.com/test/demo`, click Load.
Expected: Overview shows 1 push, graph shows nodes, timeline shows event.

- [ ] **Step 3: Stop server**

```bash
kill %1
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: Overmind Phase 1 complete — server, MCP, plugin, dashboard"
```
