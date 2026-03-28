import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from overmind.api import create_app
from overmind.store import SQLiteStore


@pytest_asyncio.fixture
async def client(data_dir):
    store = SQLiteStore(data_dir=data_dir)
    await store.init_db()
    app = create_app(data_dir=data_dir, store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
class TestPushEndpoint:
    async def test_push_success(self, client):
        resp = await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001",
                "type": "correction",
                "ts": "2026-03-26T05:30:00Z",
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
                "ts": "2026-03-26T05:30:00Z",
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
            "priority": "high_priority",
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
            "message": "high priority change",
            "priority": "high_priority",
        })
        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/test/repo",
        })
        body = resp.json()
        assert body["count"] == 1
        assert body["events"][0]["type"] == "broadcast"
        assert body["events"][0]["priority"] == "high_priority"


@pytest.mark.asyncio
class TestReportEndpoint:
    async def test_report_basic(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_001", "type": "correction",
                "ts": "2026-03-26T05:30:00Z", "result": "fix",
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
                "ts": "2026-03-26T05:30:00Z", "result": "fix",
                "files": ["src/auth/login.ts"],
            }],
        })
        resp = await client.get("/api/report/graph", params={
            "repo_id": "github.com/test/repo",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) >= 2
        assert len(body["edges"]) >= 1


@pytest.mark.asyncio
class TestFeedbackEndpoint:
    async def test_feedback_prevented_error(self, client):
        await client.post("/api/memory/push", json={
            "repo_id": "github.com/test/repo",
            "user": "dev_a",
            "events": [{
                "id": "evt_fb_001",
                "type": "correction",
                "ts": "2026-03-26T05:30:00Z",
                "result": "found a critical bug",
            }],
        })
        resp = await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_001",
            "user": "dev_b",
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
                "id": "evt_fb_002",
                "type": "correction",
                "ts": "2026-03-26T05:30:00Z",
                "result": "another bug fix",
            }],
        })
        await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_002",
            "user": "dev_b",
            "type": "prevented_error",
        })
        resp = await client.post("/api/memory/feedback", json={
            "repo_id": "github.com/test/repo",
            "event_id": "evt_fb_002",
            "user": "dev_b",
            "type": "prevented_error",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["recorded"] is False
        assert body["prevented_count"] == 1


import asyncio


@pytest.mark.asyncio
class TestConcurrentPush:
    """Concurrent push tests via asyncio.gather.

    NOTE: These use ASGI in-process transport (no real network), so asyncio.gather
    serializes under the GIL. This validates functional correctness (no data loss,
    dedup works) but not true thread-safety under multi-process concurrent writes.
    The JSONL store uses single-threaded append-only writes, so real concurrency
    issues would only appear with actual multi-process access to the same files.
    """

    async def test_concurrent_push_no_data_loss(self, client):
        """Multiple agents pushing concurrently should not lose events."""
        async def push_batch(user: str, start: int, count: int):
            for i in range(count):
                await client.post("/api/memory/push", json={
                    "repo_id": "github.com/stress/test",
                    "user": user,
                    "events": [{
                        "id": f"stress_{user}_{start + i}",
                        "type": "change",
                        "ts": "2026-03-27T10:00:00Z",
                        "result": f"change {i} by {user}",
                        "files": [f"src/{user}/file_{i}.ts"],
                    }],
                })

        # 5 agents push 10 events each concurrently
        await asyncio.gather(
            push_batch("agent_a", 0, 10),
            push_batch("agent_b", 100, 10),
            push_batch("agent_c", 200, 10),
            push_batch("agent_d", 300, 10),
            push_batch("agent_e", 400, 10),
        )

        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/stress/test",
            "limit": 100,
        })
        body = resp.json()
        assert body["count"] == 50

        # Verify all agents present
        users = {e["user"] for e in body["events"]}
        assert users == {"agent_a", "agent_b", "agent_c", "agent_d", "agent_e"}

    async def test_concurrent_push_dedup(self, client):
        """Same event ID pushed concurrently should be deduped."""
        async def push_same(user: str):
            await client.post("/api/memory/push", json={
                "repo_id": "github.com/stress/dedup",
                "user": user,
                "events": [{
                    "id": "shared_event_001",
                    "type": "correction",
                    "ts": "2026-03-27T10:00:00Z",
                    "result": "shared fix",
                }],
            })

        await asyncio.gather(
            push_same("agent_a"),
            push_same("agent_b"),
            push_same("agent_c"),
        )

        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/stress/dedup",
        })
        body = resp.json()
        # Only 1 event should exist (dedup by id)
        assert body["count"] == 1
