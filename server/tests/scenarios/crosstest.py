"""Cross-agent integration test: rich push-pull cycles for dashboard testing.

Event timestamps use relative offsets from 'now' so that push→pull→push
ordering is naturally reflected in pull_log.ts values.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

API = "http://localhost:7777"
REPO = "github.com/overmind/crosstest"

# Base time: 1 hour ago, so events aren't in the future
_base = datetime.now(timezone.utc) - timedelta(hours=1)
# Unique run prefix so IDs never collide with previous runs
_run = datetime.now(timezone.utc).strftime("%H%M%S")

def ts(minutes_offset: int) -> str:
    """Return an ISO timestamp at base + offset minutes."""
    return (_base + timedelta(minutes=minutes_offset)).isoformat()

def eid(name: str) -> str:
    """Return a unique event ID for this run."""
    return f"{name}_{_run}"


def post(path, body):
    req = Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urlopen(req).read())


def get(path, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v)
    return json.loads(urlopen(url).read())


def main():
    # ================================================================
    # Round 1: dev_a starts auth work, dev_b starts cache work
    # Events at T+0..5 minutes (independent, parallel work)
    # ================================================================
    print("=== Round 1: Initial pushes ===")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": eid("r1_a1"), "type": "decision",
                "ts": ts(0),
                "result": "JWT 인증을 OAuth2+PKCE로 전환 결정",
                "files": ["src/auth/oauth2.ts", "src/auth/jwt.ts"],
                "process": ["JWT refresh rotation 위험 분석",
                            "OAuth2+PKCE가 보안+stateless 모두 만족"],
            },
            {
                "id": eid("r1_a2"), "type": "correction",
                "ts": ts(3),
                "result": "passport-oauth2 v3.x PKCE 미지원 → v4.x 업그레이드",
                "files": ["package.json", "src/auth/oauth2.ts"],
                "process": ["PKCE challenge 실패", "v3→v4 업그레이드로 해결"],
            },
        ],
    })
    print("  dev_a pushed: decision(T+0) + correction(T+3)")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": eid("r1_b1"), "type": "decision",
                "ts": ts(1),
                "result": "Redis 세션 캐시 도입 결정 (인증 응답 최적화)",
                "files": ["src/cache/redis.ts", "src/auth/session.ts"],
                "process": ["p99=450ms 문제", "Redis 분산 캐시 도입"],
            },
        ],
    })
    print("  dev_b pushed: decision(T+1)")

    # Small delay so pull_log.ts > all Round 1 event timestamps
    time.sleep(0.3)

    # ================================================================
    # Round 2: Cross-pulls — agents discover each other's work
    # pull_log.ts will be ~T+5..6 (between Round 1 and Round 3 events)
    # ================================================================
    print("\n=== Round 2: Cross-pulls ===")

    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/auth/*", "exclude_user": "dev_b",
    })
    print(f"  dev_b pulled {result['count']} auth events")

    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/cache/*", "exclude_user": "dev_a",
    })
    print(f"  dev_a pulled {result['count']} cache events")

    # Small delay
    time.sleep(0.3)

    # ================================================================
    # Round 3: Informed pushes — work influenced by pulled info
    # Events at T+8..12 minutes (AFTER pull timestamps)
    # ================================================================
    print("\n=== Round 3: Informed pushes ===")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": eid("r3_b1"), "type": "change",
                "ts": ts(8),
                "result": "OAuth2 토큰을 Redis 캐시 키로 사용 (dev_a의 OAuth2 전환 반영)",
                "files": ["src/cache/redis.ts", "src/auth/session.ts"],
                "process": ["dev_a가 JWT→OAuth2 전환 결정",
                            "캐시 키 구조를 oauth_sub 기반으로 변경"],
            },
            {
                "id": eid("r3_b2"), "type": "correction",
                "ts": ts(11),
                "result": "Redis KEYS 명령 production 블로킹 → SCAN+TTL 패턴으로 변경",
                "files": ["src/cache/redis.ts"],
                "process": ["KEYS auth:* 로 조회 → 블로킹",
                            "SCAN + TTL 패턴으로 교체"],
            },
        ],
    })
    print("  dev_b pushed: change(T+8) + correction(T+11)")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": eid("r3_a1"), "type": "discovery",
                "ts": ts(9),
                "result": "id_token에서 사용자 정보 추출 → Redis 캐시 부하 40% 감소",
                "files": ["src/auth/oauth2.ts", "src/auth/user-info.ts"],
                "process": ["dev_b Redis 캐시 도입 확인",
                            "id_token decode → userinfo 호출 제거"],
            },
        ],
    })
    print("  dev_a pushed: discovery(T+9)")

    time.sleep(0.3)

    # ================================================================
    # Round 4: agent_1 joins, pulls everything, does DB work
    # Events at T+16..18
    # ================================================================
    print("\n=== Round 4: agent_1 joins ===")

    result = get("/api/memory/pull", {
        "repo_id": REPO, "exclude_user": "agent_1",
    })
    print(f"  agent_1 pulled {result['count']} events (full catch-up)")

    time.sleep(0.3)

    post("/api/memory/push", {
        "repo_id": REPO, "user": "agent_1",
        "events": [
            {
                "id": eid("r4_c1"), "type": "change",
                "ts": ts(16),
                "result": "users 테이블 oauth_provider, oauth_sub 컬럼 추가 + 인덱스",
                "files": ["src/db/migrations/004_oauth.sql", "src/db/models/user.ts"],
                "process": ["dev_a OAuth2 전환 → oauth_provider 필요",
                            "dev_b Redis 캐시 → oauth_sub 인덱스 필요"],
            },
            {
                "id": eid("r4_c2"), "type": "discovery",
                "ts": ts(18),
                "result": "PG14 IDENTITY가 SERIAL보다 SQL 표준 호환 — 점진 전환 권장",
                "files": ["src/db/migrations/004_oauth.sql"],
                "process": ["SERIAL 패턴 발견", "IDENTITY가 SQL 표준"],
            },
        ],
    })
    print("  agent_1 pushed: change(T+16) + discovery(T+18)")

    time.sleep(0.3)

    # ================================================================
    # Round 5: dev_a, dev_b pull DB changes
    # ================================================================
    print("\n=== Round 5: More cross-pulls ===")

    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/db/*", "exclude_user": "dev_a",
    })
    print(f"  dev_a pulled {result['count']} DB events")

    result = get("/api/memory/pull", {
        "repo_id": REPO, "exclude_user": "dev_b",
    })
    print(f"  dev_b pulled {result['count']} events (full sync)")

    time.sleep(0.3)

    # ================================================================
    # Round 6: Final fixes after cross-pollination
    # Events at T+24..26
    # ================================================================
    print("\n=== Round 6: Final fixes ===")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": eid("r6_a1"), "type": "correction",
                "ts": ts(24),
                "result": "auth middleware에서 user.oauth_sub 사용하도록 수정",
                "files": ["src/auth/middleware.ts", "src/auth/oauth2.ts"],
                "process": ["agent_1 DB 마이그레이션에서 oauth_sub 확인",
                            "middleware user lookup을 oauth_sub 기반으로 변경"],
            },
        ],
    })
    print("  dev_a pushed: correction(T+24)")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": eid("r6_b1"), "type": "correction",
                "ts": ts(25),
                "result": "Redis 캐시 키를 oauth_sub 기반으로 통일 (DB 스키마 반영)",
                "files": ["src/cache/redis.ts", "src/cache/invalidation.ts"],
                "process": ["agent_1 DB에 oauth_sub 추가 확인",
                            "캐시 키 prefix를 oauth_sub로 통일"],
            },
        ],
    })
    print("  dev_b pushed: correction(T+25)")

    time.sleep(0.3)

    # ================================================================
    # Round 7: Broadcast + final sync
    # ================================================================
    print("\n=== Round 7: Broadcast + final sync ===")

    post("/api/memory/broadcast", {
        "repo_id": REPO, "user": "master_agent",
        "message": "API 통합 테스트 시작. auth+cache+DB 모두 완료 상태 필요.",
        "priority": "urgent", "scope": "src/*",
        "related_files": ["src/auth/", "src/cache/", "src/db/"],
    })
    print("  master_agent broadcast: urgent 통합 테스트 알림")

    time.sleep(0.2)

    for user in ["dev_a", "dev_b", "agent_1"]:
        result = get("/api/memory/pull", {
            "repo_id": REPO, "exclude_user": user,
        })
        print(f"  {user} pulled {result['count']} events")

    # ================================================================
    # Verification
    # ================================================================
    print("\n=== Verification ===")
    graph = get("/api/report/graph", {"repo_id": REPO})
    flow = get("/api/report/flow", {"repo_id": REPO})
    users = sum(1 for n in graph["nodes"] if n["type"] == "user")
    events_count = len(flow["events"])
    pulls_count = len(flow["pull_links"])
    print(f"  Events: {events_count}, Pull links: {pulls_count}, Agents: {users}")

    report = get("/api/report", {"repo_id": REPO})
    print(f"  Total pushes: {report['total_pushes']}, pulls: {report['total_pulls']}")

    print("\nDone! Open http://localhost:7777/dashboard")


if __name__ == "__main__":
    main()
