"""Full push-pull cycle test: simulates 2+ agents exchanging events.

Scenario:
  1. dev_a pushes 3 events (auth refactoring)
  2. dev_b pulls → sees dev_a's 3 events
  3. dev_b pushes 2 events (cache layer)
  4. dev_a pulls → sees dev_b's 2 events (not own)
  5. master_agent broadcasts urgent message
  6. All agents pull → each sees broadcast + others' events
  7. Graph has cross-edges (pushed + consumed/pulled)
  8. Report stats match expected counts
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from overmind.api import create_app
from overmind.store import SQLiteStore


REPO = "github.com/cycle/test"


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
class TestPushPullCycle:
    """Full round-trip cycle between two agents + broadcast."""

    async def test_full_cycle(self, client):
        # ── Step 1: dev_a pushes 3 auth events ──
        resp = await client.post("/api/memory/push", json={
            "repo_id": REPO,
            "user": "dev_a",
            "events": [
                {
                    "id": "cyc_a1", "type": "decision",
                    "ts": "2026-03-26T00:00:00Z",
                    "result": "JWT를 OAuth2+PKCE로 전환",
                    "files": ["src/auth/oauth2.ts", "src/auth/jwt.ts"],
                    "process": ["JWT refresh rotation 복잡", "OAuth2+PKCE 채택"],
                },
                {
                    "id": "cyc_a2", "type": "correction",
                    "ts": "2026-03-26T00:30:00Z",
                    "result": "passport-oauth2 v3.x PKCE 미지원, v4.x 필요",
                    "files": ["package.json", "src/auth/oauth2.ts"],
                },
                {
                    "id": "cyc_a3", "type": "discovery",
                    "ts": "2026-03-26T01:00:00Z",
                    "result": "token response에 id_token 포함, userinfo 불필요",
                    "files": ["src/auth/oauth2.ts"],
                },
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 3

        # ── Step 2: dev_b pulls → sees dev_a's 3 events ──
        resp = await client.get("/api/memory/pull", params={
            "repo_id": REPO,
            "exclude_user": "dev_b",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        assert all(e["user"] == "dev_a" for e in body["events"])

        # ── Step 3: dev_b pushes 2 cache events ──
        resp = await client.post("/api/memory/push", json={
            "repo_id": REPO,
            "user": "dev_b",
            "events": [
                {
                    "id": "cyc_b1", "type": "decision",
                    "ts": "2026-03-26T01:30:00Z",
                    "result": "Redis 세션 캐시 도입",
                    "files": ["src/cache/redis.ts"],
                    "process": ["인증 API p99=450ms", "Redis 도입 결정"],
                },
                {
                    "id": "cyc_b2", "type": "correction",
                    "ts": "2026-03-26T02:00:00Z",
                    "result": "Redis KEYS 블로킹 → SET+TTL 패턴으로 변경",
                    "files": ["src/cache/redis.ts"],
                },
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 2

        # ── Step 4: dev_a pulls → sees dev_b's 2 events only ──
        resp = await client.get("/api/memory/pull", params={
            "repo_id": REPO,
            "exclude_user": "dev_a",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert all(e["user"] == "dev_b" for e in body["events"])

        # ── Step 5: master_agent broadcasts ──
        resp = await client.post("/api/memory/broadcast", json={
            "repo_id": REPO,
            "user": "master_agent",
            "message": "API 통합 테스트 12:30 시작",
            "priority": "urgent",
            "scope": "src/*",
            "related_files": ["src/auth/", "src/cache/"],
        })
        assert resp.status_code == 200
        bcast_id = resp.json()["id"]
        assert bcast_id.startswith("bcast_")

        # ── Step 6: Each agent pulls → sees broadcast + others' events ──
        for user, expected_min in [("dev_a", 3), ("dev_b", 4), ("agent_c", 6)]:
            resp = await client.get("/api/memory/pull", params={
                "repo_id": REPO,
                "exclude_user": user,
            })
            body = resp.json()
            assert body["count"] >= expected_min, (
                f"{user} expected >= {expected_min} events, got {body['count']}"
            )
            # Broadcast should be first (urgent priority)
            assert body["events"][0]["priority"] == "urgent"
            assert body["events"][0]["type"] == "broadcast"

        # ── Step 7: Graph has cross-edges ──
        resp = await client.get("/api/report/graph", params={"repo_id": REPO})
        assert resp.status_code == 200
        graph = resp.json()

        # Nodes: at least dev_a, dev_b, master_agent + their events
        user_nodes = [n for n in graph["nodes"] if n["type"] == "user"]
        event_nodes = [n for n in graph["nodes"] if n["type"] == "event"]
        assert len(user_nodes) >= 3  # dev_a, dev_b, master_agent
        assert len(event_nodes) >= 6  # 3 + 2 + 1 broadcast + ghosts

        # Edge types
        edges_by_rel = {}
        for e in graph["edges"]:
            edges_by_rel.setdefault(e["relation"], []).append(e)

        assert len(edges_by_rel.get("pushed", [])) >= 6  # 3+2+1 original pushes
        assert len(edges_by_rel.get("pulled", [])) >= 1   # at least some consumed
        assert len(edges_by_rel.get("consumed", [])) >= 1

        # Ghost nodes exist (consumed events shown under consuming agent)
        ghost_nodes = [
            n for n in graph["nodes"]
            if n.get("data") and n["data"].get("ghost") is True
        ]
        assert len(ghost_nodes) >= 1

        # ── Step 8: Report stats ──
        resp = await client.get("/api/report", params={"repo_id": REPO})
        assert resp.status_code == 200
        report = resp.json()
        assert report["total_pushes"] == 6  # 3 + 2 + 1 broadcast
        assert report["unique_users"] >= 3
        assert report["events_by_type"]["decision"] == 2
        assert report["events_by_type"]["correction"] == 2
        assert report["events_by_type"]["discovery"] == 1
        assert report["events_by_type"]["broadcast"] == 1

    async def test_scope_filtered_cycle(self, client):
        """dev_b pulls only auth scope → sees only dev_a's auth events."""
        # Push from dev_a (auth) and dev_b (cache)
        await client.post("/api/memory/push", json={
            "repo_id": REPO,
            "user": "dev_a",
            "events": [{
                "id": "scope_a1", "type": "correction",
                "ts": "2026-03-26T00:00:00Z",
                "result": "auth fix",
                "files": ["src/auth/login.ts"],
            }],
        })
        await client.post("/api/memory/push", json={
            "repo_id": REPO,
            "user": "dev_b",
            "events": [{
                "id": "scope_b1", "type": "correction",
                "ts": "2026-03-26T00:00:00Z",
                "result": "cache fix",
                "files": ["src/cache/redis.ts"],
            }],
        })

        # dev_c pulls auth scope only
        resp = await client.get("/api/memory/pull", params={
            "repo_id": REPO,
            "scope": "src/auth/*",
            "exclude_user": "dev_c",
        })
        body = resp.json()
        assert body["count"] == 1
        assert body["events"][0]["user"] == "dev_a"

    async def test_since_delta_pull(self, client):
        """Pull with since only returns newer events."""
        await client.post("/api/memory/push", json={
            "repo_id": REPO,
            "user": "dev_a",
            "events": [
                {
                    "id": "delta_old", "type": "decision",
                    "ts": "2026-03-25T00:00:00Z",
                    "result": "old decision",
                },
                {
                    "id": "delta_new", "type": "decision",
                    "ts": "2026-03-26T06:00:00Z",
                    "result": "new decision",
                },
            ],
        })

        resp = await client.get("/api/memory/pull", params={
            "repo_id": REPO,
            "since": "2026-03-25T15:00:00Z",
            "exclude_user": "dev_b",
        })
        body = resp.json()
        assert body["count"] == 1
        assert body["events"][0]["id"] == "delta_new"

    async def test_duplicate_push_idempotent(self, client):
        """Pushing same event twice doesn't create duplicates in pull."""
        event = {
            "id": "dup_001", "type": "correction",
            "ts": "2026-03-26T00:00:00Z",
            "result": "same event",
        }
        await client.post("/api/memory/push", json={
            "repo_id": REPO, "user": "dev_a", "events": [event],
        })
        resp = await client.post("/api/memory/push", json={
            "repo_id": REPO, "user": "dev_a", "events": [event],
        })
        assert resp.json()["duplicates"] == 1

        resp = await client.get("/api/memory/pull", params={"repo_id": REPO})
        assert resp.json()["count"] == 1
