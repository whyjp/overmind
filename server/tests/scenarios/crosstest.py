"""Cross-agent integration test: rich push-pull cycles for dashboard testing."""

import json
from urllib.request import Request, urlopen

API = "http://localhost:7777"
REPO = "github.com/overmind/crosstest"


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
    # ================================================================
    print("=== Round 1: Initial pushes ===")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": "r1_a1", "type": "decision",
                "ts": "2026-03-26T00:00:00Z",
                "result": "JWT 인증을 OAuth2+PKCE로 전환 결정",
                "files": ["src/auth/oauth2.ts", "src/auth/jwt.ts"],
                "process": ["JWT refresh rotation 위험 분석",
                            "OAuth2+PKCE가 보안+stateless 모두 만족"],
            },
            {
                "id": "r1_a2", "type": "correction",
                "ts": "2026-03-26T00:30:00Z",
                "result": "passport-oauth2 v3.x PKCE 미지원 → v4.x 업그레이드",
                "files": ["package.json", "src/auth/oauth2.ts"],
                "process": ["PKCE challenge 실패", "v3→v4 업그레이드로 해결"],
            },
        ],
    })
    print("  dev_a pushed: decision + correction (auth)")

    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": "r1_b1", "type": "decision",
                "ts": "2026-03-26T00:15:00Z",
                "result": "Redis 세션 캐시 도입 결정 (인증 응답 최적화)",
                "files": ["src/cache/redis.ts", "src/auth/session.ts"],
                "process": ["p99=450ms 문제", "Redis 분산 캐시 도입"],
            },
        ],
    })
    print("  dev_b pushed: decision (cache)")

    # ================================================================
    # Round 2: Cross-pulls — agents discover each other's work
    # ================================================================
    print("\n=== Round 2: Cross-pulls ===")

    # dev_b pulls auth scope → discovers dev_a's OAuth2 decision
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/auth/*", "exclude_user": "dev_b",
    })
    print(f"  dev_b pulled {result['count']} auth events (discovers OAuth2 전환)")

    # dev_a pulls cache scope → discovers dev_b's Redis decision
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/cache/*", "exclude_user": "dev_a",
    })
    print(f"  dev_a pulled {result['count']} cache events (discovers Redis 도입)")

    # ================================================================
    # Round 3: Informed pushes — work influenced by pulled info
    # ================================================================
    print("\n=== Round 3: Informed pushes (after pulling) ===")

    # dev_b adjusts cache design based on dev_a's OAuth2 decision
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": "r3_b1", "type": "change",
                "ts": "2026-03-26T01:00:00Z",
                "result": "OAuth2 토큰을 Redis 캐시 키로 사용하도록 변경 (dev_a의 OAuth2 전환 반영)",
                "files": ["src/cache/redis.ts", "src/auth/session.ts"],
                "process": ["dev_a가 JWT→OAuth2 전환 결정",
                            "캐시 키 구조를 oauth_sub 기반으로 변경",
                            "기존 JWT sid 기반 키 마이그레이션 추가"],
            },
            {
                "id": "r3_b2", "type": "correction",
                "ts": "2026-03-26T01:30:00Z",
                "result": "Redis KEYS 명령 production 블로킹 → SCAN+TTL 패턴으로 변경",
                "files": ["src/cache/redis.ts"],
                "process": ["KEYS auth:* 로 조회 구현",
                            "10만건에서 블로킹 확인",
                            "SCAN + TTL 패턴으로 교체"],
            },
        ],
    })
    print("  dev_b pushed: change + correction (cache, informed by auth pull)")

    # dev_a adjusts auth based on dev_b's Redis decision
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": "r3_a1", "type": "discovery",
                "ts": "2026-03-26T01:15:00Z",
                "result": "id_token에서 직접 사용자 정보 추출 가능 → Redis 캐시 부하 40% 감소",
                "files": ["src/auth/oauth2.ts", "src/auth/user-info.ts"],
                "process": ["dev_b Redis 캐시 도입 확인",
                            "id_token decode → userinfo API 호출 제거",
                            "캐시 히트율 필요 감소"],
            },
        ],
    })
    print("  dev_a pushed: discovery (auth, informed by cache pull)")

    # ================================================================
    # Round 4: agent_1 joins, pulls everything, does DB work
    # ================================================================
    print("\n=== Round 4: agent_1 joins ===")

    # agent_1 pulls all to catch up
    result = get("/api/memory/pull", {
        "repo_id": REPO, "exclude_user": "agent_1",
    })
    print(f"  agent_1 pulled {result['count']} events (full catch-up)")

    # agent_1 pushes DB migration informed by both auth and cache changes
    post("/api/memory/push", {
        "repo_id": REPO, "user": "agent_1",
        "events": [
            {
                "id": "r4_c1", "type": "change",
                "ts": "2026-03-26T02:00:00Z",
                "result": "users 테이블 oauth_provider, oauth_sub 컬럼 추가 + 인덱스",
                "files": ["src/db/migrations/004_oauth.sql", "src/db/models/user.ts"],
                "process": ["dev_a OAuth2 전환 → oauth_provider 필요",
                            "dev_b Redis 캐시 → oauth_sub 인덱스 필요",
                            "GENERATED ALWAYS AS IDENTITY 적용"],
            },
            {
                "id": "r4_c2", "type": "discovery",
                "ts": "2026-03-26T02:15:00Z",
                "result": "PG14 IDENTITY가 SERIAL보다 SQL 표준 호환 — 점진 전환 권장",
                "files": ["src/db/migrations/004_oauth.sql"],
                "process": ["SERIAL 패턴 발견", "IDENTITY가 SQL 표준", "점진적 전환"],
            },
        ],
    })
    print("  agent_1 pushed: change + discovery (DB, informed by auth+cache)")

    # ================================================================
    # Round 5: dev_a pulls DB changes, dev_b pulls updated auth+DB
    # ================================================================
    print("\n=== Round 5: More cross-pulls ===")

    # dev_a pulls DB scope — sees agent_1's migration
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/db/*", "exclude_user": "dev_a",
    })
    print(f"  dev_a pulled {result['count']} DB events")

    # dev_b pulls all — catches up with dev_a's discovery + agent_1's DB
    result = get("/api/memory/pull", {
        "repo_id": REPO, "exclude_user": "dev_b",
    })
    print(f"  dev_b pulled {result['count']} events (full sync)")

    # ================================================================
    # Round 6: Final fixes after cross-pollination
    # ================================================================
    print("\n=== Round 6: Final fixes ===")

    # dev_a fixes auth middleware after seeing DB schema
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": "r6_a1", "type": "correction",
                "ts": "2026-03-26T02:30:00Z",
                "result": "auth middleware에서 user.id 대신 user.oauth_sub 사용하도록 수정",
                "files": ["src/auth/middleware.ts", "src/auth/oauth2.ts"],
                "process": ["agent_1 DB 마이그레이션에서 oauth_sub 확인",
                            "middleware의 user lookup을 oauth_sub 기반으로 변경"],
            },
        ],
    })
    print("  dev_a pushed: correction (auth middleware, informed by DB pull)")

    # dev_b fixes cache invalidation
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": "r6_b1", "type": "correction",
                "ts": "2026-03-26T02:45:00Z",
                "result": "Redis 캐시 키를 oauth_sub 기반으로 통일 (DB 스키마 반영)",
                "files": ["src/cache/redis.ts", "src/cache/invalidation.ts"],
                "process": ["agent_1 DB에 oauth_sub 추가 확인",
                            "캐시 키 prefix를 oauth_sub로 통일",
                            "기존 세션 캐시 마이그레이션 로직 추가"],
            },
        ],
    })
    print("  dev_b pushed: correction (cache key, informed by DB pull)")

    # ================================================================
    # Round 7: Broadcast + final sync
    # ================================================================
    print("\n=== Round 7: Broadcast + final sync ===")

    post("/api/memory/broadcast", {
        "repo_id": REPO, "user": "master_agent",
        "message": "API 통합 테스트 12:30 시작. auth+cache+DB 모두 완료 상태 필요.",
        "priority": "urgent", "scope": "src/*",
        "related_files": ["src/auth/", "src/cache/", "src/db/"],
    })
    print("  master_agent broadcast: urgent 통합 테스트 알림")

    # All agents pull broadcast
    for user in ["dev_a", "dev_b", "agent_1"]:
        result = get("/api/memory/pull", {
            "repo_id": REPO, "exclude_user": user,
        })
        print(f"  {user} pulled {result['count']} events (broadcast 수신)")

    # ================================================================
    # Verification
    # ================================================================
    print("\n=== Graph verification ===")
    graph = get("/api/report/graph", {"repo_id": REPO})
    users = sum(1 for n in graph["nodes"] if n["type"] == "user")
    events = sum(1 for n in graph["nodes"] if n["type"] == "event" and not (n.get("data") or {}).get("ghost"))
    ghosts = sum(1 for n in graph["nodes"] if n["type"] == "event" and (n.get("data") or {}).get("ghost"))
    print(f"  Users: {users}, Events: {events}, Ghosts: {ghosts}")
    pushed = sum(1 for e in graph["edges"] if e["relation"] == "pushed")
    pulled = sum(1 for e in graph["edges"] if e["relation"] == "pulled")
    consumed = sum(1 for e in graph["edges"] if e["relation"] == "consumed")
    affects = sum(1 for e in graph["edges"] if e["relation"] == "affects")
    print(f"  Edges: pushed={pushed}, pulled={pulled}, consumed={consumed}, affects={affects}")
    print(f"  Polymorphisms: {len(graph['polymorphisms'])}")

    report = get("/api/report", {"repo_id": REPO})
    print(f"  Total pushes: {report['total_pushes']}, pulls: {report['total_pulls']}")

    print("\nDone! Open http://localhost:7777/dashboard")


if __name__ == "__main__":
    main()
