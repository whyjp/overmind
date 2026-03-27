# Phase 2-A (Part 1): SQLite Store 이관 + `?detail` Pull 파라미터

**Date**: 2026-03-27
**Status**: Approved

## 배경

Phase 1의 JSONL file-based store는 기능적으로 완전하지만, 이벤트가 증가하면 `_read_repo_events()`의 전체 파일 스캔이 병목이 된다. 또한 pull 응답에서 불필요한 필드(process, prompt)가 컨텍스트 토큰을 소모한다.

Phase 2-A Part 1은 세 가지를 해결한다:
1. JSONL → SQLite 완전 교체 (인덱스 쿼리, 단일 파일 관리)
2. `?detail=summary|full` 파라미터로 pull 응답 경량화
3. 비동기 DB 드라이버(aiosqlite)로 이벤트 루프 블로킹 방지

기존 JSONL 데이터는 폐기한다 (개발 단계, 마이그레이션 불필요).

## 설계 원칙

- SOLID 원칙 준수: StoreProtocol로 인터페이스 분리, 향후 벡터DB 이관 대비
- 기존 53개 서버 테스트가 regression guard — 인터페이스 유지로 최소 변경
- Bottom-Up: 스키마 → Store 교체 → API 확장 → cleanup 어댑트
- 비동기 우선: FastAPI async 핸들러와 자연스럽게 결합, DB I/O가 이벤트 루프를 블로킹하지 않도록

## 1. SQLite 스키마

DB 파일: `{data_dir}/overmind.db`

```sql
CREATE TABLE events (
    id          TEXT PRIMARY KEY,
    repo_id     TEXT NOT NULL,
    user        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    result      TEXT NOT NULL,
    prompt      TEXT,
    files       TEXT DEFAULT '[]',
    process     TEXT DEFAULT '[]',
    priority    TEXT DEFAULT 'normal',
    scope       TEXT
);

CREATE INDEX idx_events_repo      ON events(repo_id);
CREATE INDEX idx_events_repo_ts   ON events(repo_id, ts DESC);
CREATE INDEX idx_events_repo_user ON events(repo_id, user);
CREATE INDEX idx_events_repo_scope ON events(repo_id, scope);

CREATE TABLE pull_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     TEXT NOT NULL,
    puller      TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    event_user  TEXT NOT NULL,
    ts          TEXT NOT NULL
);

CREATE INDEX idx_pull_repo   ON pull_log(repo_id);
CREATE UNIQUE INDEX idx_pull_dedup ON pull_log(repo_id, puller, event_id);
```

설계 결정:
- `files`, `process`는 JSON 문자열로 저장 (SQLite JSON 함수 활용 가능)
- `ts`는 ISO 8601 TEXT 유지 (현재 모델 호환, 문자열 비교로 정렬 가능)
- `pull_log`에 UNIQUE 제약으로 중복 pull 방지 (현재 인메모리 set 대체)

## 2. StoreProtocol + SQLiteStore

### 비동기 드라이버: aiosqlite

`aiosqlite`는 sqlite3 위의 async wrapper로, `async with aiosqlite.connect()` + `await conn.execute()` 패턴을 지원한다. pyproject.toml에 `aiosqlite >= 0.20.0` 의존성 추가.

모든 store 퍼블릭 메서드를 `async def`로 정의한다. 이에 따라:
- API 핸들러에서 `await store.pull(...)` 호출
- 테스트에서 `await` 또는 `pytest-asyncio` 사용

### StoreProtocol

```python
from typing import Protocol

class StoreProtocol(Protocol):
    """Storage backend contract. 모든 store 구현체가 준수해야 할 인터페이스.
    향후 벡터DB 등으로 교체 시 이 Protocol을 구현한다."""

    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]: ...
    async def pull(self, repo_id: str, *, user=None, exclude_user=None,
                   since=None, scope=None, limit=100,
                   detail="full") -> PullResponse: ...
    async def list_repos(self) -> list[str]: ...
    async def get_repo_stats(self, repo_id: str, *, since=None, until=None,
                             period="7d") -> ReportResponse: ...
    async def get_graph_data(self, repo_id: str) -> GraphResponse: ...
    async def get_flow_data(self, repo_id: str) -> dict: ...
    def get_version(self, repo_id: str) -> int: ...
    def get_global_version(self) -> int: ...
    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int: ...
```

`get_version`, `get_global_version`은 인메모리 카운터 접근만이므로 동기 유지.

### 메서드 매핑

| 현재 (JSONL) | SQLite 구현 |
|---|---|
| `__init__(data_dir)` | DB 경로만 저장. 실제 연결은 `async def init_db()`에서 `aiosqlite.connect()` + CREATE TABLE |
| `push(events)` | `await conn.execute("INSERT OR IGNORE ...")` (PK dedup, `_seen_ids` 제거) |
| `pull(repo_id, ...)` | `await conn.execute("SELECT ...")` + 파이썬 fnmatch scope 필터 |
| `get_version(repo_id)` | 인메모리 카운터 (동기, SSE용) |
| `get_global_version()` | 인메모리 카운터 (동기) |
| `list_repos()` | `await conn.execute("SELECT DISTINCT repo_id FROM events")` |
| `get_repo_stats(...)` | `await conn.execute("SELECT COUNT(*) ...")` + GROUP BY 집계 |
| `get_graph_data(repo_id)` | `await` 이벤트 SELECT 후 기존 그래프 로직 유지 |
| `get_flow_data(repo_id)` | 동일 패턴 |
| `cleanup_expired(...)` | `await conn.execute("DELETE FROM events WHERE ...")` |

### DB 초기화 패턴

```python
class SQLiteStore:
    def __init__(self, data_dir: Path):
        self._db_path = data_dir / "overmind.db"
        self._conn: aiosqlite.Connection | None = None

    async def init_db(self):
        """앱 시작 시 호출. FastAPI lifespan에서 await store.init_db()."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.executescript(SCHEMA_SQL)

    async def close(self):
        """앱 종료 시 호출."""
        if self._conn:
            await self._conn.close()
```

FastAPI lifespan에서 `init_db()` / `close()` 호출.

### 삭제되는 코드

- `_seen_ids` dict (DB PK가 dedup)
- `_pull_log` dict (DB 테이블이 대체)
- `_read_repo_events()` 전체 스캔 (쿼리로 대체)
- `_event_file()`, `_repo_dir()`, `_safe_repo_id()` 파일 경로 헬퍼
- `_append_pull_log()`, `_load_pull_log()`, `_ensure_pull_log_loaded()`

### 유지되는 코드

- `_version`, `_global_version` 인메모리 카운터 (SSE용)
- `_matches_scope()` (pull 필터링에 재사용)
- `_file_to_scope()` 모듈 레벨 함수

### scope 매칭 전략

SQL에서 `WHERE repo_id=?`로 후보를 좁힌 뒤, 파이썬 `fnmatch`로 scope 필터링.
초기 구현은 안전하게 파이썬 fnmatch 유지. SQL LIKE 최적화는 성능 문제 발생 시 추가.

## 3. `?detail` Pull 파라미터

### API 변경

```python
@app.get("/api/memory/pull")
async def pull_memory(
    repo_id: str = Query(...),
    since: Optional[str] = Query(default=None),
    scope: Optional[str] = Query(default=None),
    user: Optional[str] = Query(default=None),
    exclude_user: Optional[str] = Query(default=None),
    limit: int = Query(default=100),
    detail: str = Query(default="full"),    # NEW
) -> PullResponse:
```

### detail 레벨 정의

| 필드 | summary | full |
|------|---------|------|
| id, repo_id, user, ts | O | O |
| type, result, priority | O | O |
| scope | O | O |
| files | O | O |
| process | X (빈 배열) | O |
| prompt | X (null) | O |

summary에서 제외되는 건 `process`와 `prompt` 두 필드뿐. `files`는 엔티티 분석에 핵심이므로 summary에도 포함.

### Store 내부 구현

- `detail="full"`: `SELECT * FROM events WHERE ...`
- `detail="summary"`: `SELECT id, repo_id, user, ts, type, result, priority, scope, files FROM events WHERE ...` (process, prompt 제외)

### 플러그인 측 활용 (향후)

- SessionStart hook: `detail=summary`로 pull (컨텍스트 절약)
- PreToolUse hook: `detail=full`로 pull (충돌 판단에 process 필요할 수 있음)

## 4. `db_cleanup.py` 어댑트

CLI 인터페이스 유지, 내부를 SQLite 쿼리로 교체.

| 명령어 | SQLite 구현 |
|--------|------------|
| `status` | `SELECT COUNT(*), COUNT(DISTINCT user), COUNT(DISTINCT repo_id) FROM events` |
| `ttl --days N` | `DELETE FROM events WHERE ts < ?` |
| `purge --repo` | `DELETE FROM events WHERE repo_id=?` + `DELETE FROM pull_log WHERE repo_id=?` |
| `vacuum` (기존 compact) | `VACUUM` |
| `export <repo_id>` | `SELECT * FROM events WHERE repo_id=?` → JSONL stdout 출력 |

DB 경로: `{data_dir}/overmind.db`, 인자 또는 환경변수로 지정.
store를 import하지 않고 `sqlite3`로 직접 접속 (스크립트 독립성).

## 5. 테스트 전략

### 기존 테스트 변경

| 파일 | 변경 |
|------|------|
| `test_store.py` (11개) | import 변경 + `async def` + `@pytest.mark.asyncio`. fixture에서 `await store.init_db()` |
| `test_api.py` (11개) | create_app이 lifespan에서 init_db 호출 → httpx AsyncClient 사용 시 자동 처리 |
| `test_mcp.py` (3개) | 동일 — create_app 경유 |
| scenarios (19개) | ServerThread 내에서 lifespan이 init_db 호출 → 변경 최소 |
| `test_models.py` (7개) | 변경 없음 — 모델만 테스트 |

### 추가 테스트

| 테스트 | 내용 |
|--------|------|
| `test_store.py::test_pull_detail_summary` | `await pull(detail="summary")`에서 process=[], prompt=None 확인 |
| `test_api.py::test_pull_detail_param` | `GET /api/memory/pull?detail=summary` API 레벨 확인 |

### 성공 기준

기존 53개 테스트 전부 pass + 추가 테스트 pass = 이관 성공.

## 6. 변경 파일 요약

| 변경 | 파일 |
|------|------|
| 재작성 | `server/overmind/store.py` |
| 수정 | `server/overmind/api.py` (detail 파라미터 1줄 추가 + 전달) |
| 수정 | `server/tests/test_store.py` (import + detail 테스트) |
| 수정 | `server/tests/test_api.py` (detail 테스트 추가) |
| 수정 | `server/scripts/db_cleanup.py` (SQLite 쿼리로 교체) |
| 수정 | `server/pyproject.toml` (aiosqlite 의존성 추가) |
| 수정 | `server/overmind/main.py` (lifespan에서 store.init_db/close 호출) |

변경 없는 파일: models.py, mcp_server.py, plugin/ 전체, dashboard/ 전체.
