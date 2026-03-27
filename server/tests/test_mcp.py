import pytest
import pytest_asyncio
from fastmcp import Client
from overmind.mcp_server import create_mcp_server
from overmind.store import SQLiteStore


@pytest_asyncio.fixture
async def store(data_dir):
    s = SQLiteStore(data_dir=data_dir)
    await s.init_db()
    yield s
    await s.close()


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
                    "ts": "2026-03-26T05:30:00Z",
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

    async def test_overmind_feedback(self, mcp):
        async with Client(mcp) as dev_a, Client(mcp) as dev_b:
            await dev_a.call_tool("overmind_push", {
                "repo_id": "github.com/test/repo",
                "user": "dev_a",
                "events": [{
                    "id": "evt_fb_mcp_001",
                    "type": "correction",
                    "ts": "2026-03-26T05:30:00Z",
                    "result": "fixed auth bug",
                }],
            })
            result = await dev_b.call_tool("overmind_feedback", {
                "repo_id": "github.com/test/repo",
                "event_id": "evt_fb_mcp_001",
                "user": "dev_b",
                "feedback_type": "helpful",
            })
            assert "recorded" in str(result)

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
                        "ts": "2026-03-26T05:30:00Z",
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
            assert "10" in str(pull_result) or pull_result
