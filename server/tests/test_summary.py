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
