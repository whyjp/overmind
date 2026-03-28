# Nightmare Config Scaffold Design

**Date**: 2026-03-29
**Status**: Approved
**Goal**: Overmind 가치를 증명할 수 있는 복잡한 AB test scaffold. 단계 수가 아닌 문제 복잡도(상호의존, misleading errors, 다단계 추론)로 차이를 만든다.

## Problem

기존 scaffold(simple 3단계, multistage 9단계)에서 Student와 Naive 간 차이가 없음. 에러 메시지가 솔루션을 직접 가리키고 각 트랩이 독립적이라 LLM이 iterative discovery로 충분히 해결. Overmind의 cross-agent knowledge sharing이 실질적 이점을 제공하려면, 에이전트 혼자서는 여러 번 실패해야 하는 복잡한 트랩이 필요.

## Architecture

Python 마이크로서비스. 설정이 3곳에 분산: `config.toml`, `.env`, `secrets/hmac.key`. 모듈 간 상호의존성이 핵심.

### 트랩 5종 혼합

| 유형 | 설명 | 왜 어려운가 |
|------|------|------------|
| Misleading errors | 에러 traceback이 실제 원인과 다른 파일을 가리킴 | 에러만 보고 수정하면 삽질 |
| 상호의존성 | A 값이 B 값에 의존, 한쪽만 고치면 다른 쪽이 깨짐 | 전체 관계를 파악해야 함 |
| 숨겨진 제약조건 | validation rule이 소스 코드에만 있음 | 에러 메시지로 유추 불가, 소스 읽기 필수 |
| 다단계 추론 (3-hop) | config → registry.json → .env 체인 | 3개 파일을 cross-reference |
| 순서 함정 | 일부만 수정하면 더 confusing한 에러 발생 | 부분 수정이 오히려 상황을 악화 |

## File Structure

```
hive-nightmare/
  config.toml            # 부분 존재: [database], [auth]만. 나머지 미설정
  .env                   # 존재하지만 placeholder 값
  secrets/hmac.key       # 존재하지만 잘못된 내용
  plugins/registry.json  # 플러그인 목록 (PLUGIN_PATH 참조)
  start.sh               # python src/server.py
  CLAUDE.md              # 규칙: config.toml, .env, secrets/hmac.key 만 수정 가능
  src/
    server.py            # entry point — 모듈 순차 로드
    config_loader.py     # config.toml + .env + secrets/ 통합 로더
    db.py                # TRAP 1: misleading error
    auth.py              # TRAP 2: cross-file 교차 검증
    cache.py             # TRAP 3: 상호의존 (cache.ttl < session.timeout)
    session.py           # TRAP 3 counterpart
    metrics.py           # TRAP 4: port 충돌 3-way
    plugins.py           # TRAP 5: 3-hop 추론
```

## Trap Details

### TRAP 1: Misleading Error (db.py)

**초기 상태**: `.env`에 `DATABASE_URL=changeme://localhost/db` (placeholder)

**에러**: `db.py`가 `ConnectionError: Failed to parse database URL scheme` 던짐. Traceback이 `db.py:parse_url()` 가리킴.

**함정**: 에이전트가 `db.py`를 수정하려 하지만, CLAUDE.md가 src/ 수정 금지. 실제 원인은 `.env`의 `DATABASE_URL` placeholder.

**해결**: `.env`에서 `DATABASE_URL=postgresql://localhost:5432/hive` 설정

**난이도**: 중. 에러 메시지에 "parse" 힌트가 있어 URL 자체를 의심할 수 있지만, traceback이 db.py를 가리키므로 혼란.

### TRAP 2: Cross-file Secret Validation (auth.py)

**초기 상태**:
- `.env`에 `SECRET_KEY=dev-placeholder-key`
- `secrets/hmac.key`에 `0000000000000000000000000000000000000000000000000000000000000000` (zero-filled 64 hex)
- `config.toml`에 `[auth] algorithm = "HS256"`

**에러**: `auth.py`가 `ValueError: HMAC key verification failed: key file digest does not match SECRET_KEY` 던짐.

**함정**: 에이전트가 `secrets/hmac.key`만 바꾸거나 `SECRET_KEY`만 바꾸면 계속 실패. 소스를 읽으면 `hmac.key` 내용이 `hashlib.sha256(SECRET_KEY.encode()).hexdigest()`와 일치해야 함을 발견.

**해결**: `.env`에서 `SECRET_KEY`를 설정하고, `secrets/hmac.key`를 그 SHA256 hex digest로 설정. (또는 소스에서 관계를 파악한 후 일관된 쌍을 생성)

**난이도**: 높. 두 파일 간 관계가 에러 메시지에 힌트되지만 정확한 관계(SHA256)는 소스에서만 확인 가능.

### TRAP 3: Mutual Dependency (cache.py ↔ session.py)

**초기 상태**: config.toml에 `[cache]`와 `[session]` 모두 없음.

**에러 순서**:
1. session.py가 먼저 로드: `KeyError: 'session'` — `[session]` 섹션 필요
2. `[session]` 추가 후: cache.py가 `ValueError: cache.ttl_seconds (300) must be less than session.timeout (300)` — 같거나 크면 에러
3. 추가 제약: `cache.backend`가 `"redis"`면 `cache.redis_url`이 필수, `"memory"`면 `cache.max_items`가 필수

**함정**: session을 먼저 추가하면 cache에서 의존성 에러. cache를 먼저 추가하면 session 미존재 에러. 둘 다 한 번에 추가해야 하는데, ttl < timeout 제약도 맞춰야 함.

**해결**: `[session] timeout = 3600` + `[cache] ttl_seconds = 1800, backend = "memory", max_items = 1000` (ttl < timeout)

**난이도**: 중-높. 상호의존 관계를 이해하고 값의 대소 관계를 맞춰야 함.

### TRAP 4: Three-way Port Conflict (metrics.py)

**초기 상태**: config.toml에 `[server]`, `[metrics]`, `[health]` 모두 없음.

**에러**: `metrics.py`가 `ValueError: port conflict: metrics.port (8080) == server.port (8080)` 또는 `health.port (8080) == server.port (8080)`

**함정**: 3개 포트가 모두 달라야 함. 에러는 한 번에 하나의 충돌만 보여줌. 첫 충돌을 해결하면 두 번째 충돌이 나타남.

**해결**: `[server] port = 8080`, `[metrics] port = 9090, enabled = true`, `[health] port = 9091, interval_seconds = 30`

**난이도**: 중. 포트 3개를 다르게 설정해야 하며, metrics와 health의 추가 필드도 소스에서 확인 필요.

### TRAP 5: Three-hop Plugin Chain (plugins.py)

**초기 상태**:
- `config.toml`에 `[plugins] enabled = true` 있지만 `registry_path` 없음
- `plugins/registry.json`에 `{"plugins": [{"name": "audit-log", "module": "audit"}]}` 있지만 `enabled` 필드 없음
- `.env`에 `PLUGIN_PATH` 없음

**에러 체인**:
1. `plugins.py`: `KeyError: 'registry_path'` — config에 경로 없음
2. registry_path 추가 후: `FileNotFoundError` — PLUGIN_PATH env var가 base path
3. PLUGIN_PATH 설정 후: `ValueError: plugin 'audit-log' missing 'enabled' field` — registry.json 수정 필요

**함정**: 3개 파일(config.toml → plugins/registry.json → .env)을 순차적으로 추적해야 함. 각 파일이 다른 파일을 참조.

**해결**: config.toml에 `[plugins] enabled = true, registry_path = "plugins/registry.json"` + `.env`에 `PLUGIN_PATH=./plugins` + registry.json에 `enabled: true` 추가

**CLAUDE.md 제약**: `config.toml`, `.env`, `secrets/hmac.key`만 수정 가능. `plugins/registry.json`도 수정 가능하도록 CLAUDE.md에 명시.

**난이도**: 높. 3-hop 추론 + 3개 파일 수정.

## Module Load Order

```python
# src/server.py
config = load_config()          # config.toml + .env + secrets/
validate_db(config)             # TRAP 1: misleading error
validate_auth(config)           # TRAP 2: cross-file secret
validate_session(config)        # TRAP 3a: session config
validate_cache(config)          # TRAP 3b: cache ↔ session dependency
validate_server_ports(config)   # TRAP 4: 3-way port conflict
validate_plugins(config)        # TRAP 5: 3-hop chain
# All passed → print success
```

에러는 첫 번째 실패에서 멈춤 (기존 scaffold와 동일). 한 트랩을 해결하면 다음 트랩이 나타남.

## Initial File Contents

### config.toml
```toml
# Hive Nightmare Service Configuration

[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600
```

`[server]`, `[session]`, `[cache]`, `[metrics]`, `[health]`, `[plugins]` 모두 없음. `[database]`에 `url` 없음 (`.env`에서 로드).

### .env
```
# Hive Environment Variables
DATABASE_URL=changeme://localhost/db
SECRET_KEY=dev-placeholder-key
NODE_ENV=development
```

`PLUGIN_PATH` 없음. `DATABASE_URL`은 placeholder. `SECRET_KEY`는 약한 값.

### secrets/hmac.key
```
0000000000000000000000000000000000000000000000000000000000000000
```

Zero-filled. auth.py가 이것이 SECRET_KEY의 SHA256 digest인지 검증.

### plugins/registry.json
```json
{
  "plugins": [
    {"name": "audit-log", "module": "audit"}
  ]
}
```

`enabled` 필드 누락.

### CLAUDE.md
```markdown
# Hive Nightmare Service

## Start
Run `bash start.sh` to start the server.

## Rules
- You may edit: config.toml, .env, secrets/hmac.key, plugins/registry.json
- Do NOT modify files under src/ or any .py files.
- Do NOT create new files.
```

## Expected Agent Behavior

### Pioneer (6-10 cycles)
```
run → db error (traceback: db.py) → db.py 읽기 → .env 발견 → .env 수정
run → auth error (key mismatch) → auth.py 읽기 → SHA256 관계 발견 → .env + secrets 수정
run → session missing → config 수정
run → cache error (ttl ≥ timeout) → cache.py 읽기 → 의존관계 발견 → config 재수정
run → port conflict → config 수정
run → port conflict (2nd) → config 재수정
run → plugin error → plugins.py 읽기 → 3-hop 추적 → config + .env + registry 수정
run → OK
```

### Student (1-2 cycles, with Overmind)
Pioneer의 diff에서:
- `.env` DATABASE_URL + SECRET_KEY 변경 내역
- `secrets/hmac.key` 변경 내역 (+ "SHA256 of SECRET_KEY" context)
- `config.toml` 전체 section 추가 내역 (ttl < timeout 관계 포함)
- `plugins/registry.json` enabled 추가

→ 3-4개 파일을 한 번에 수정 → 1-2회 실행으로 완료

### Naive (6-10 cycles)
Pioneer와 동일한 iterative discovery. Overmind 없으므로 모든 트랩을 처음부터 탐색.

## Integration

### Scaffold Module
`server/tests/fixtures/ab_scaffolds/nightmare.py`:
- `SCAFFOLD_FILES`, `create_scaffold`, `SHARED_PROMPT`, `REPO_ID`, `MAX_TURNS`
- `REPO_NAME = "hive-nightmare"`, `REPO_ID = "github.com/test/hive-nightmare"`, `MAX_TURNS = 40`

### Registry Update
`server/tests/fixtures/ab_scaffolds/__init__.py`에 `nightmare` 추가.

### SHARED_PROMPT
```
Get the Hive Nightmare service running.
Run `bash start.sh` to start it.
If it fails, investigate and fix the issue, then retry.
You may edit config.toml, .env, secrets/hmac.key, and plugins/registry.json only.
```

### Statistical Test
기존 `test_live_agents_AB_statistical.py`의 parametrize에 자동 포함 (SCAFFOLDS registry 기반).

## Success Criteria

Statistical AB test에서:
- **Student의 `server_run_attempts` mean이 Naive보다 30%+ 적음**
- **Student의 `proactive_config_fix` 비율이 50%+** (Pioneer diff로 사전 수정)
- 또는 **Student elapsed time이 Naive보다 20%+ 빠름**

N=3, M=3 이상에서 일관된 차이가 나타나면 성공.
