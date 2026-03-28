import pytest
import pytest_asyncio
from overmind.models import MemoryEvent
from overmind.store import SQLiteStore
from overmind.summary import MockSummaryGenerator


@pytest_asyncio.fixture
async def store(data_dir):
    s = SQLiteStore(data_dir=data_dir, summary_generator=MockSummaryGenerator())
    await s.init_db()
    yield s
    await s.close()


def _make_event(
    id: str,
    user: str = "dev_a",
    repo_id: str = "github.com/test/repo",
    type: str = "correction",
    files: list[str] | None = None,
    ts: str = "2026-03-26T05:30:00Z",
    result: str = "test result",
    priority: str = "normal",
    process: list[str] | None = None,
    prompt: str | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        id=id,
        repo_id=repo_id,
        user=user,
        ts=ts,
        type=type,
        result=result,
        files=files or [],
        priority=priority,
        process=process or [],
        prompt=prompt,
    )


class TestInit:
    @pytest.mark.asyncio
    async def test_init_creates_db(self, store, data_dir):
        db_path = data_dir / "overmind.db"
        assert db_path.exists()


class TestPush:
    @pytest.mark.asyncio
    async def test_push_single_event(self, store):
        evt = _make_event("evt_001")
        accepted, duplicates = await store.push([evt])
        assert accepted == 1
        assert duplicates == 0

    @pytest.mark.asyncio
    async def test_push_duplicate_ignored(self, store):
        evt = _make_event("evt_001")
        await store.push([evt])
        accepted, duplicates = await store.push([evt])
        assert accepted == 0
        assert duplicates == 1

    @pytest.mark.asyncio
    async def test_push_multiple_events(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(5)]
        accepted, duplicates = await store.push(events)
        assert accepted == 5
        assert duplicates == 0


class TestPullBasic:
    @pytest.mark.asyncio
    async def test_pull_returns_pushed_events(self, store):
        evt = _make_event("evt_001")
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"

    @pytest.mark.asyncio
    async def test_pull_excludes_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        await store.push([evt_a, evt_b])
        result = await store.pull(repo_id="github.com/test/repo", exclude_user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_b"

    @pytest.mark.asyncio
    async def test_pull_filters_by_user(self, store):
        evt_a = _make_event("evt_001", user="dev_a")
        evt_b = _make_event("evt_002", user="dev_b")
        await store.push([evt_a, evt_b])
        result = await store.pull(repo_id="github.com/test/repo", user="dev_a")
        assert len(result.events) == 1
        assert result.events[0].user == "dev_a"

    @pytest.mark.asyncio
    async def test_pull_with_since(self, store):
        evt_old = _make_event("evt_001", ts="2026-03-25T01:00:00Z")
        evt_new = _make_event("evt_002", ts="2026-03-26T06:00:00Z")
        await store.push([evt_old, evt_new])
        result = await store.pull(repo_id="github.com/test/repo", since="2026-03-25T15:00:00Z")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_002"

    @pytest.mark.asyncio
    async def test_pull_with_limit(self, store):
        events = [_make_event(f"evt_{i:03d}") for i in range(10)]
        await store.push(events)
        result = await store.pull(repo_id="github.com/test/repo", limit=3)
        assert len(result.events) == 3
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_pull_empty_repo(self, store):
        result = await store.pull(repo_id="github.com/nonexistent/repo")
        assert len(result.events) == 0
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_pull_broadcast_high_priority_first(self, store):
        evt_normal = _make_event("evt_001", priority="normal", ts="2026-03-26T05:00:00Z")
        evt_high = _make_event("evt_002", priority="high_priority", ts="2026-03-26T04:00:00Z")
        await store.push([evt_normal, evt_high])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].id == "evt_002"  # high_priority first despite older ts

    @pytest.mark.asyncio
    async def test_pull_different_repos_isolated(self, store):
        evt_1 = _make_event("evt_001", repo_id="github.com/test/repo1")
        evt_2 = _make_event("evt_002", repo_id="github.com/test/repo2")
        await store.push([evt_1, evt_2])
        result = await store.pull(repo_id="github.com/test/repo1")
        assert len(result.events) == 1
        assert result.events[0].id == "evt_001"


class TestPullDetail:
    @pytest.mark.asyncio
    async def test_pull_detail_summary(self, store):
        """detail='summary' excludes process and prompt fields."""
        evt = _make_event(
            "evt_001",
            process=["step 1", "step 2"],
            prompt="do something",
        )
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo", detail="summary")
        assert len(result.events) == 1
        assert result.events[0].process == []
        assert result.events[0].prompt is None

    @pytest.mark.asyncio
    async def test_pull_detail_full(self, store):
        """detail='full' preserves all fields."""
        evt = _make_event(
            "evt_001",
            process=["step 1", "step 2"],
            prompt="do something",
        )
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo", detail="full")
        assert len(result.events) == 1
        assert result.events[0].process == ["step 1", "step 2"]
        assert result.events[0].prompt == "do something"


class TestSummary:
    @pytest.mark.asyncio
    async def test_push_generates_summary_when_process_exists(self, store):
        """MockSummaryGenerator returns result as summary when process exists."""
        evt = _make_event("evt_sum_1", process=["step 1"], result="found bug in auth")
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].summary == "found bug in auth"

    @pytest.mark.asyncio
    async def test_push_no_summary_when_no_process(self, store):
        """MockSummaryGenerator returns None when process is empty."""
        evt = _make_event("evt_sum_2", process=[], result="some result")
        await store.push([evt])
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].summary is None


class TestFeedback:
    @pytest.mark.asyncio
    async def test_record_feedback(self, store):
        """Basic feedback recording."""
        evt = _make_event("evt_fb_1")
        await store.push([evt])
        was_new, count = await store.record_feedback(
            "github.com/test/repo", "evt_fb_1", "dev_b", "helpful"
        )
        assert was_new is True

    @pytest.mark.asyncio
    async def test_feedback_increments_prevented_count(self, store):
        """prevented_error feedback increments prevented_count on the event."""
        evt = _make_event("evt_fb_2")
        await store.push([evt])
        was_new, count = await store.record_feedback(
            "github.com/test/repo", "evt_fb_2", "dev_b", "prevented_error"
        )
        assert was_new is True
        assert count == 1
        # Verify via pull
        result = await store.pull(repo_id="github.com/test/repo")
        assert result.events[0].prevented_count == 1

    @pytest.mark.asyncio
    async def test_feedback_dedup(self, store):
        """Duplicate feedback is ignored (same event_id, user, type)."""
        evt = _make_event("evt_fb_3")
        await store.push([evt])
        await store.record_feedback("github.com/test/repo", "evt_fb_3", "dev_b", "prevented_error")
        was_new, count = await store.record_feedback(
            "github.com/test/repo", "evt_fb_3", "dev_b", "prevented_error"
        )
        assert was_new is False
        assert count == 1  # Not incremented again

    @pytest.mark.asyncio
    async def test_helpful_feedback_no_prevented_count(self, store):
        """helpful feedback does NOT increment prevented_count."""
        evt = _make_event("evt_fb_4")
        await store.push([evt])
        was_new, count = await store.record_feedback(
            "github.com/test/repo", "evt_fb_4", "dev_b", "helpful"
        )
        assert was_new is True
        assert count == 0

    @pytest.mark.asyncio
    async def test_feedback_in_repo_stats(self, store):
        """Feedback counts appear in get_repo_stats."""
        evt = _make_event("evt_fb_5")
        await store.push([evt])
        await store.record_feedback("github.com/test/repo", "evt_fb_5", "dev_b", "prevented_error")
        await store.record_feedback("github.com/test/repo", "evt_fb_5", "dev_c", "helpful")
        stats = await store.get_repo_stats("github.com/test/repo")
        assert stats.total_feedback == 2
        assert stats.prevented_errors == 1
