"""Cross-agent integration test: push + pull + graph with pulled edges."""

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
    # === dev_a: auth 리팩토링 ===
    print("=== dev_a: auth 리팩토링 ===")
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_a",
        "events": [
            {
                "id": "xa_001", "type": "decision",
                "ts": "2026-03-26T09:00:00+09:00",
                "result": "JWT 인증을 OAuth2+PKCE로 전환 결정",
                "files": ["src/auth/oauth2.ts", "src/auth/jwt.ts", "src/auth/middleware.ts"],
                "process": ["JWT refresh rotation 검토->토큰 탈취 위험",
                            "세션 기반->stateless 요구사항 충돌",
                            "OAuth2+PKCE가 보안+stateless 모두 만족"],
            },
            {
                "id": "xa_002", "type": "correction",
                "ts": "2026-03-26T09:30:00+09:00",
                "result": "passport-oauth2 v3.x PKCE 미지원, v4.x로 업그레이드",
                "files": ["package.json", "src/auth/oauth2.ts"],
                "process": ["PKCE challenge 실패", "v3.x PKCE 미지원 확인", "v4.0.0 업그레이드 후 해결"],
            },
            {
                "id": "xa_003", "type": "discovery",
                "ts": "2026-03-26T10:00:00+09:00",
                "result": "OAuth2 token response에 id_token 포함, userinfo 호출 불필요 (200ms 절감)",
                "files": ["src/auth/oauth2.ts", "src/auth/user-info.ts"],
                "process": ["userinfo endpoint 구현 중 발견",
                            "id_token JWT가 이미 포함",
                            "id_token decode로 호출 제거"],
            },
        ],
    })
    print("  pushed 3 events")

    # === dev_b: 캐시 레이어 ===
    print("\n=== dev_b: 캐시 레이어 ===")
    post("/api/memory/push", {
        "repo_id": REPO, "user": "dev_b",
        "events": [
            {
                "id": "xb_001", "type": "decision",
                "ts": "2026-03-26T10:30:00+09:00",
                "result": "Redis 세션 캐시 도입 (인증 응답시간 최적화)",
                "files": ["src/auth/cache.ts", "src/cache/redis.ts"],
                "process": ["인증 API p99=450ms", "in-memory->서버 재시작 유실",
                            "Redis->영속성+분산 지원"],
            },
            {
                "id": "xb_002", "type": "correction",
                "ts": "2026-03-26T11:00:00+09:00",
                "result": "Redis KEYS 명령 production 블로킹 -> SET+TTL 패턴으로 변경",
                "files": ["src/cache/redis.ts"],
                "process": ["KEYS auth:* 명령으로 조회 구현",
                            "production 10만건에서 블로킹",
                            "SET auth:{user_id} + TTL 패턴으로 변경"],
            },
        ],
    })
    print("  pushed 2 events")

    # === agent_1: DB 마이그레이션 ===
    print("\n=== agent_1: DB 마이그레이션 ===")
    post("/api/memory/push", {
        "repo_id": REPO, "user": "agent_1",
        "events": [
            {
                "id": "x1_001", "type": "change",
                "ts": "2026-03-26T11:30:00+09:00",
                "result": "users 테이블에 oauth_provider, oauth_sub 컬럼 추가",
                "files": ["src/db/migrations/004_oauth.sql", "src/db/models/user.ts"],
                "process": ["OAuth2 전환에 필요한 스키마 변경",
                            "oauth_provider, oauth_sub 추가",
                            "jwt_secret deprecated 표시"],
            },
            {
                "id": "x1_002", "type": "discovery",
                "ts": "2026-03-26T12:00:00+09:00",
                "result": "PG14 GENERATED ALWAYS AS IDENTITY가 SERIAL보다 표준 호환",
                "files": ["src/db/migrations/004_oauth.sql"],
                "process": ["SERIAL 패턴 발견", "IDENTITY가 SQL 표준", "점진적 전환 권장"],
            },
        ],
    })
    print("  pushed 2 events")

    # === Cross pulls: 교차 소비 ===
    print("\n=== dev_b pulls auth scope (dev_a의 이력 소비) ===")
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/auth/*", "exclude_user": "dev_b",
    })
    print(f"  pulled {result['count']} events:")
    for e in result["events"]:
        print(f"    [{e['type']}] {e['user']}: {e['result'][:50]}")

    print("\n=== dev_a pulls cache scope (dev_b의 이력 소비) ===")
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/cache/*", "exclude_user": "dev_a",
    })
    print(f"  pulled {result['count']} events:")
    for e in result["events"]:
        print(f"    [{e['type']}] {e['user']}: {e['result'][:50]}")

    print("\n=== agent_1 pulls all (전체 소비) ===")
    result = get("/api/memory/pull", {
        "repo_id": REPO, "exclude_user": "agent_1",
    })
    print(f"  pulled {result['count']} events")

    print("\n=== dev_a pulls DB scope (agent_1의 이력 소비) ===")
    result = get("/api/memory/pull", {
        "repo_id": REPO, "scope": "src/db/*", "exclude_user": "dev_a",
    })
    print(f"  pulled {result['count']} events:")
    for e in result["events"]:
        print(f"    [{e['type']}] {e['user']}: {e['result'][:50]}")

    # === Broadcast ===
    print("\n=== master_agent: urgent broadcast ===")
    post("/api/memory/broadcast", {
        "repo_id": REPO, "user": "master_agent",
        "message": "API 통합 테스트 12:30 시작. auth+cache+DB 모두 완료 상태 필요.",
        "priority": "urgent", "scope": "src/*",
        "related_files": ["src/auth/", "src/cache/", "src/db/"],
    })
    print("  broadcast sent")

    # All agents pull broadcast
    print("\n=== All agents pull (broadcast 포함) ===")
    for user in ["dev_a", "dev_b", "agent_1"]:
        result = get("/api/memory/pull", {
            "repo_id": REPO, "exclude_user": user,
        })
        print(f"  {user} pulled {result['count']} events")

    # === Verify graph ===
    print("\n=== Graph verification ===")
    graph = get("/api/report/graph", {"repo_id": REPO})
    print(f"  Nodes: {len(graph['nodes'])}")
    pushed = sum(1 for e in graph["edges"] if e["relation"] == "pushed")
    affects = sum(1 for e in graph["edges"] if e["relation"] == "affects")
    pulled = sum(1 for e in graph["edges"] if e["relation"] == "pulled")
    print(f"  Edges: pushed={pushed}, affects={affects}, pulled={pulled}")
    print(f"  Polymorphisms: {len(graph['polymorphisms'])}")
    for p in graph["polymorphisms"]:
        print(f"    scope={p['scope']}, users={p['users']}")

    print("\n  Pull edges detail:")
    for e in graph["edges"]:
        if e["relation"] == "pulled":
            print(f"    {e['source']} --> {e['target']} (consumed)")

    print("\nDone! Open http://localhost:7777/dashboard and select 'github.com/overmind/crosstest'")


if __name__ == "__main__":
    main()
