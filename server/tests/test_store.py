import pytest
from overmind.models import MemoryEvent
from overmind.store import MemoryStore


@pytest.fixture
def store(data_dir):
    return MemoryStore(data_dir=data_dir)


def _make_event(id: str, user: str = "dev_a", repo_id: str = "github.com/test/repo",
                type: str = "correction", files: list[str] | None = None,
                ts: str = "2026-03-26T05:30:00Z", result: str = "test result",
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
        evt_old = _make_event("evt_001", ts="2026-03-25T01:00:00Z")
        evt_new = _make_event("evt_002", ts="2026-03-26T06:00:00Z")
        store.push([evt_old, evt_new])
        result = store.pull(repo_id="github.com/test/repo", since="2026-03-25T15:00:00Z")
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
        evt_normal = _make_event("evt_001", priority="normal", ts="2026-03-26T05:00:00Z")
        evt_urgent = _make_event("evt_002", priority="urgent", ts="2026-03-26T04:00:00Z")
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
