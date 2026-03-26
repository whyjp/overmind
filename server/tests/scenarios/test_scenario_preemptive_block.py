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
