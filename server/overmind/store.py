"""Async SQLite-backed memory store for Overmind events."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, Optional, Protocol, runtime_checkable

import aiosqlite

from overmind.models import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryEvent,
    PolymorphismAlert,
    PullResponse,
    ReportResponse,
)

DetailLevel = Literal["summary", "full"]


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    return datetime.fromisoformat(ts)


def _file_to_scope(file_path: str) -> str:
    """Convert a file path like 'src/auth/login.ts' to 'src/auth/*'."""
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return "*"
    return "/".join(parts[:-1]) + "/*"


# ---------------------------------------------------------------------------
# StoreProtocol
# ---------------------------------------------------------------------------


@runtime_checkable
class StoreProtocol(Protocol):
    """Async interface every Overmind store must implement."""

    async def init_db(self) -> None: ...
    async def close(self) -> None: ...
    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]: ...
    async def pull(
        self,
        repo_id: str,
        *,
        user: Optional[str] = None,
        exclude_user: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        detail: DetailLevel = "full",
    ) -> PullResponse: ...
    async def list_repos(self) -> list[str]: ...
    def get_version(self, repo_id: str) -> int: ...
    def get_global_version(self) -> int: ...
    async def get_repo_stats(
        self,
        repo_id: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        period: str = "7d",
    ) -> ReportResponse: ...
    async def get_graph_data(self, repo_id: str) -> GraphResponse: ...
    async def get_flow_data(self, repo_id: str) -> dict: ...
    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int: ...


# ---------------------------------------------------------------------------
# SQLiteStore
# ---------------------------------------------------------------------------


class SQLiteStore:
    """Async SQLite-backed store for MemoryEvent objects."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "overmind.db"
        self._db: aiosqlite.Connection | None = None
        # In-memory version counters for SSE change detection
        self._version: dict[str, int] = defaultdict(int)
        self._global_version: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init_db(self) -> None:
        """Create the database connection and tables."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Call init_db() first"
        return self._db

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    async def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """INSERT new events with dedup. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0
        accepted_repos: set[str] = set()

        for evt in events:
            async with self.db.execute(
                """INSERT OR IGNORE INTO events (id, repo_id, user, ts, type, result, prompt, files, process, priority, scope)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evt.id,
                    evt.repo_id,
                    evt.user,
                    evt.ts,
                    evt.type,
                    evt.result,
                    evt.prompt,
                    json.dumps(evt.files),
                    json.dumps(evt.process),
                    evt.priority,
                    evt.scope,
                ),
            ) as cur:
                if cur.rowcount > 0:
                    accepted += 1
                    accepted_repos.add(evt.repo_id)
                else:
                    duplicates += 1

        if accepted > 0:
            await self.db.commit()
            self._global_version += 1
            for rid in accepted_repos:
                self._version[rid] += 1

        return accepted, duplicates

    def get_version(self, repo_id: str) -> int:
        """Return current version counter for a repo."""
        return self._version[repo_id]

    def get_global_version(self) -> int:
        """Return global version counter."""
        return self._global_version

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    def _matches_scope(
        self, evt_scope: str | None, evt_files: list[str], scope: str | None
    ) -> bool:
        """Return True if event matches the given scope glob."""
        if scope is None:
            return True
        if evt_scope and fnmatch(evt_scope, scope):
            return True
        for f in evt_files:
            if fnmatch(f, scope):
                return True
        return False

    def _row_to_event(self, row: aiosqlite.Row, detail: DetailLevel = "full") -> MemoryEvent:
        """Convert an aiosqlite.Row to a MemoryEvent, respecting detail level."""
        files = json.loads(row["files"]) if row["files"] else []
        process = json.loads(row["process"]) if row["process"] else []
        prompt = row["prompt"]

        if detail == "summary":
            process = []
            prompt = None

        return MemoryEvent(
            id=row["id"],
            repo_id=row["repo_id"],
            user=row["user"],
            ts=row["ts"],
            type=row["type"],
            result=row["result"],
            prompt=prompt,
            files=files,
            process=process,
            priority=row["priority"],
            scope=row["scope"],
        )

    async def pull(
        self,
        repo_id: str,
        *,
        user: Optional[str] = None,
        exclude_user: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        detail: DetailLevel = "full",
    ) -> PullResponse:
        """Return events for a repo, sorted urgent-first then newest-first."""
        # Build query
        conditions = ["repo_id = ?"]
        params: list[str] = [repo_id]

        if user is not None:
            conditions.append("user = ?")
            params.append(user)
        if exclude_user is not None:
            conditions.append("user != ?")
            params.append(exclude_user)
        if since is not None:
            conditions.append("ts > ?")
            params.append(since)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM events WHERE {where}"

        rows: list[aiosqlite.Row] = []
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()

        # Filter by scope in Python (fnmatch)
        filtered: list[aiosqlite.Row] = []
        for row in rows:
            evt_files = json.loads(row["files"]) if row["files"] else []
            if self._matches_scope(row["scope"], evt_files, scope):
                filtered.append(row)

        # Sort: urgent first (newest within), then normal (newest within)
        urgent = sorted(
            [r for r in filtered if r["priority"] == "urgent"],
            key=lambda r: _parse_ts(r["ts"]),
            reverse=True,
        )
        normal = sorted(
            [r for r in filtered if r["priority"] != "urgent"],
            key=lambda r: _parse_ts(r["ts"]),
            reverse=True,
        )
        sorted_rows = urgent + normal

        has_more = len(sorted_rows) > limit
        result_rows = sorted_rows[:limit]
        result_events = [self._row_to_event(r, detail) for r in result_rows]

        # Record pull history (only when exclude_user is set)
        puller = exclude_user
        if puller:
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            for r in result_rows:
                await self.db.execute(
                    "INSERT OR IGNORE INTO pull_log (repo_id, puller, event_id, event_user, ts) VALUES (?, ?, ?, ?, ?)",
                    (repo_id, puller, r["id"], r["user"], now_iso),
                )
            await self.db.commit()

        return PullResponse(
            events=result_events,
            count=len(result_events),
            has_more=has_more,
        )

    # ------------------------------------------------------------------
    # Repo listing
    # ------------------------------------------------------------------

    async def list_repos(self) -> list[str]:
        """Return all known repo_ids."""
        async with self.db.execute("SELECT DISTINCT repo_id FROM events ORDER BY repo_id") as cur:
            rows = await cur.fetchall()
        return [row["repo_id"] for row in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_repo_stats(
        self,
        repo_id: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        period: str = "7d",
    ) -> ReportResponse:
        """Return aggregate statistics for a repo."""
        conditions = ["repo_id = ?"]
        params: list[str] = [repo_id]

        if since:
            conditions.append("ts >= ?")
            params.append(since)
        if until:
            conditions.append("ts <= ?")
            params.append(until)

        where = " AND ".join(conditions)

        # Total events
        async with self.db.execute(
            f"SELECT COUNT(*) as cnt FROM events WHERE {where}", params
        ) as cur:
            total_pushes = (await cur.fetchone())["cnt"]

        # Unique users
        async with self.db.execute(
            f"SELECT COUNT(DISTINCT user) as cnt FROM events WHERE {where}", params
        ) as cur:
            unique_users = (await cur.fetchone())["cnt"]

        # Events by type
        async with self.db.execute(
            f"SELECT type, COUNT(*) as cnt FROM events WHERE {where} GROUP BY type", params
        ) as cur:
            type_rows = await cur.fetchall()
        events_by_type = {row["type"]: row["cnt"] for row in type_rows}

        # Pull count: unique (puller, event_id) pairs for this repo
        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM pull_log WHERE repo_id = ?", (repo_id,)
        ) as cur:
            total_pulls = (await cur.fetchone())["cnt"]

        return ReportResponse(
            repo_id=repo_id,
            period=period,
            total_pushes=total_pushes,
            total_pulls=total_pulls,
            unique_users=unique_users,
            events_by_type=events_by_type,
        )

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    async def _fetch_all_events(self, repo_id: str) -> list[MemoryEvent]:
        """Fetch all events for a repo as MemoryEvent objects."""
        async with self.db.execute(
            "SELECT * FROM events WHERE repo_id = ?", (repo_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_event(r) for r in rows]

    async def _fetch_pull_log(self, repo_id: str) -> list[dict]:
        """Fetch all pull log entries for a repo."""
        async with self.db.execute(
            "SELECT puller, event_id, event_user, ts FROM pull_log WHERE repo_id = ?",
            (repo_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "puller": row["puller"],
                "event_id": row["event_id"],
                "event_user": row["event_user"],
                "ts": row["ts"],
            }
            for row in rows
        ]

    async def get_graph_data(self, repo_id: str) -> GraphResponse:
        """Return graph nodes, edges, and polymorphism alerts for a repo."""
        all_events = await self._fetch_all_events(repo_id)

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_users: set[str] = set()
        seen_scopes: set[str] = set()
        scope_users: dict[str, set[str]] = defaultdict(set)
        scope_intents: dict[str, list[str]] = defaultdict(list)

        for evt in all_events:
            # User node
            if evt.user not in seen_users:
                nodes.append(GraphNode(id=f"user:{evt.user}", type="user", label=evt.user))
                seen_users.add(evt.user)

            # Event node
            nodes.append(
                GraphNode(
                    id=f"event:{evt.id}",
                    type="event",
                    label=evt.result[:60] if evt.result else evt.id,
                    event_type=evt.type,
                    data={"result": evt.result, "process": evt.process, "ts": evt.ts},
                )
            )
            edges.append(
                GraphEdge(source=f"user:{evt.user}", target=f"event:{evt.id}", relation="pushed")
            )

            # Scope nodes from files
            scopes = {_file_to_scope(f) for f in evt.files}
            if evt.scope:
                scopes.add(evt.scope)

            for scope in scopes:
                if scope not in seen_scopes:
                    nodes.append(GraphNode(id=f"scope:{scope}", type="scope", label=scope))
                    seen_scopes.add(scope)
                edges.append(
                    GraphEdge(
                        source=f"event:{evt.id}", target=f"scope:{scope}", relation="affects"
                    )
                )
                scope_users[scope].add(evt.user)
                scope_intents[scope].append(evt.result)

        # Polymorphism alerts
        polymorphisms: list[PolymorphismAlert] = []
        for scope, users in scope_users.items():
            if len(users) > 1:
                polymorphisms.append(
                    PolymorphismAlert(
                        scope=scope,
                        users=sorted(users),
                        intents=scope_intents[scope],
                    )
                )

        # Pull edges: ghost nodes
        pull_log = await self._fetch_pull_log(repo_id)
        pull_seen: set[tuple[str, str]] = set()
        for entry in pull_log:
            puller = entry["puller"]
            evt_id = entry["event_id"]
            evt_user = entry.get("event_user", "")

            if puller == evt_user:
                continue

            key = (puller, evt_id)
            if key in pull_seen:
                continue
            pull_seen.add(key)

            if puller not in seen_users:
                nodes.append(GraphNode(id=f"user:{puller}", type="user", label=puller))
                seen_users.add(puller)

            orig_evt = next((e for e in all_events if e.id == evt_id), None)
            ghost_id = f"ghost:{puller}:{evt_id}"

            nodes.append(
                GraphNode(
                    id=ghost_id,
                    type="event",
                    label=orig_evt.result[:60] if orig_evt else evt_id,
                    event_type=orig_evt.type if orig_evt else None,
                    data={
                        "ghost": True,
                        "consumed_by": puller,
                        "original_user": evt_user,
                        "result": orig_evt.result if orig_evt else "",
                        "ts": entry.get("ts", ""),
                    },
                )
            )

            edges.append(
                GraphEdge(source=f"user:{puller}", target=ghost_id, relation="consumed")
            )
            edges.append(
                GraphEdge(source=f"event:{evt_id}", target=ghost_id, relation="pulled")
            )

        return GraphResponse(nodes=nodes, edges=edges, polymorphisms=polymorphisms)

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------

    async def get_flow_data(self, repo_id: str) -> dict:
        """Return chronological flow data: push events + pull links."""
        all_events = await self._fetch_all_events(repo_id)
        all_events.sort(key=lambda e: _parse_ts(e.ts))

        pull_log = await self._fetch_pull_log(repo_id)
        puller_set = {entry["puller"] for entry in pull_log}
        agents = sorted({e.user for e in all_events} | puller_set)

        events = [
            {
                "id": e.id,
                "user": e.user,
                "type": e.type,
                "result": e.result,
                "ts": e.ts,
                "scope": e.scope,
                "files": e.files,
                "process": e.process,
                "priority": e.priority,
            }
            for e in all_events
        ]

        # Pull links: deduplicated
        pull_seen: set[tuple[str, str]] = set()
        pull_links = []
        for entry in pull_log:
            key = (entry["puller"], entry["event_id"])
            if key in pull_seen:
                continue
            if entry["puller"] == entry.get("event_user", ""):
                continue
            pull_seen.add(key)
            pull_links.append({
                "puller": entry["puller"],
                "event_id": entry["event_id"],
                "event_user": entry.get("event_user", ""),
                "ts": entry.get("ts", ""),
            })

        # Polymorphism detection
        scope_users: dict[str, set[str]] = defaultdict(set)
        scope_intents: dict[str, list[str]] = defaultdict(list)
        for evt in all_events:
            scopes = {_file_to_scope(f) for f in evt.files}
            if evt.scope:
                scopes.add(evt.scope)
            for scope in scopes:
                scope_users[scope].add(evt.user)
                scope_intents[scope].append(evt.result)

        polymorphisms = [
            {"scope": scope, "users": sorted(users), "intents": scope_intents[scope]}
            for scope, users in scope_users.items()
            if len(users) > 1
        ]

        return {
            "agents": agents,
            "events": events,
            "pull_links": pull_links,
            "polymorphisms": polymorphisms,
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int:
        """Remove events older than ttl_days. Returns count of removed events."""
        now = datetime.now(tz=timezone.utc)
        cutoff = (now - timedelta(days=ttl_days)).isoformat()

        async with self.db.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE repo_id = ? AND ts <= ?",
            (repo_id, cutoff),
        ) as cur:
            removed = (await cur.fetchone())["cnt"]

        if removed > 0:
            await self.db.execute(
                "DELETE FROM events WHERE repo_id = ? AND ts <= ?",
                (repo_id, cutoff),
            )
            await self.db.commit()
            # Clear seen_ids is not needed — SQLite handles dedup via SELECT

        return removed


# ---------------------------------------------------------------------------
# SQL Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    user TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    result TEXT NOT NULL,
    prompt TEXT,
    files TEXT DEFAULT '[]',
    process TEXT DEFAULT '[]',
    priority TEXT DEFAULT 'normal',
    scope TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_id);
CREATE INDEX IF NOT EXISTS idx_events_repo_ts ON events(repo_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_repo_user ON events(repo_id, user);
CREATE INDEX IF NOT EXISTS idx_events_repo_scope ON events(repo_id, scope);

CREATE TABLE IF NOT EXISTS pull_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    puller TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_user TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pull_repo ON pull_log(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pull_dedup ON pull_log(repo_id, puller, event_id);
"""


# ---------------------------------------------------------------------------
# Backward-compatible alias (used by api.py, mcp_server.py, main.py)
# Will be removed once those modules are migrated to async.
# ---------------------------------------------------------------------------

MemoryStore = SQLiteStore
