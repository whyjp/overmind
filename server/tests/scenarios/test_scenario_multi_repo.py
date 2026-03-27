"""Scenario: events from different repos are completely isolated."""

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


@pytest.mark.asyncio
async def test_multi_repo_isolation(store):
    evt_1 = MemoryEvent(
        id="evt_repo1_001",
        repo_id="github.com/team/frontend",
        user="dev_a",
        ts="2026-03-26T05:00:00Z",
        type="correction",
        result="React 18 hydration 이슈 해결",
        files=["src/app.tsx"],
    )
    evt_2 = MemoryEvent(
        id="evt_repo2_001",
        repo_id="github.com/team/backend",
        user="dev_a",
        ts="2026-03-26T05:00:00Z",
        type="correction",
        result="DB connection pool 설정 수정",
        files=["src/db/pool.ts"],
    )

    await store.push([evt_1, evt_2])

    # Pull from frontend repo — should not see backend events
    result_fe = await store.pull(repo_id="github.com/team/frontend")
    assert result_fe.count == 1
    assert result_fe.events[0].result == "React 18 hydration 이슈 해결"

    # Pull from backend repo — should not see frontend events
    result_be = await store.pull(repo_id="github.com/team/backend")
    assert result_be.count == 1
    assert result_be.events[0].result == "DB connection pool 설정 수정"

    # Graph data should be isolated too
    graph_fe = await store.get_graph_data("github.com/team/frontend")
    graph_be = await store.get_graph_data("github.com/team/backend")
    fe_results = [n.label or "" for n in graph_fe.nodes if n.type == "event"]
    be_results = [n.label or "" for n in graph_be.nodes if n.type == "event"]
    assert not any("DB connection" in r for r in fe_results)
    assert not any("hydration" in r for r in be_results)
