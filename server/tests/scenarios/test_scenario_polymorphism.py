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
    assert len(graph.polymorphisms) >= 1

    poly = graph.polymorphisms[0]
    assert set(poly.users) == {"dev_a", "dev_b"}
