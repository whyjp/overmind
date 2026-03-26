"""FastAPI application for Overmind memory sync server."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from overmind.models import (
    BroadcastRequest,
    BroadcastResponse,
    MemoryEvent,
    PullResponse,
    PushRequest,
    PushResponse,
    ReportResponse,
)
from overmind.store import MemoryStore


def create_app(data_dir: Optional[Path] = None, store: Optional[MemoryStore] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if data_dir is None:
        data_dir = Path("data")

    data_dir = Path(data_dir)
    if store is None:
        store = MemoryStore(data_dir=data_dir)

    # Attempt cleanup on startup (best-effort, no repo_id required here)
    # cleanup_expired requires repo_id, so we skip global cleanup at startup

    # In-memory pull counter per repo
    pull_counts: dict[str, int] = defaultdict(int)

    app = FastAPI(title="Overmind Memory Sync Server")

    # Mount dashboard static files if directory exists
    dashboard_dir = Path(__file__).parent / "dashboard" / "static"
    if dashboard_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    @app.get("/api/repos")
    async def list_repos() -> list[str]:
        return store.list_repos()

    @app.post("/api/memory/push", response_model=PushResponse)
    async def push_memory(request: PushRequest) -> PushResponse:
        events = [evt.to_event(request.repo_id, request.user) for evt in request.events]
        accepted, duplicates = store.push(events)
        return PushResponse(accepted=accepted, duplicates=duplicates)

    @app.get("/api/memory/pull", response_model=PullResponse)
    async def pull_memory(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        scope: Optional[str] = Query(default=None),
        user: Optional[str] = Query(default=None),
        exclude_user: Optional[str] = Query(default=None),
        limit: int = Query(default=100),
    ) -> PullResponse:
        pull_counts[repo_id] += 1
        return store.pull(
            repo_id,
            since=since,
            scope=scope,
            user=user,
            exclude_user=exclude_user,
            limit=limit,
        )

    @app.post("/api/memory/broadcast", response_model=BroadcastResponse)
    async def broadcast_memory(request: BroadcastRequest) -> BroadcastResponse:
        bcast_id = f"bcast_{uuid.uuid4().hex[:12]}"
        ts = datetime.now(timezone.utc).isoformat()

        event = MemoryEvent(
            id=bcast_id,
            repo_id=request.repo_id,
            user=request.user,
            ts=ts,
            type="broadcast",
            result=request.message,
            priority=request.priority,
            scope=request.scope,
            files=request.related_files,
        )
        store.push([event])

        return BroadcastResponse(id=bcast_id, delivered=True)

    @app.get("/api/report", response_model=ReportResponse)
    async def get_report(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        until: Optional[str] = Query(default=None),
        period: str = Query(default="7d"),
    ) -> ReportResponse:
        stats = store.get_repo_stats(repo_id, since=since, until=until, period=period)
        # Inject tracked pull count
        stats.total_pulls = pull_counts.get(repo_id, 0)
        return stats

    @app.get("/api/report/graph")
    async def get_report_graph(repo_id: str = Query(...)):
        return store.get_graph_data(repo_id)

    @app.get("/api/report/timeline")
    async def get_report_timeline(repo_id: str = Query(...)):
        pull_resp = store.pull(repo_id, limit=1000)
        swimlanes: dict[str, list] = defaultdict(list)
        for evt in pull_resp.events:
            swimlanes[evt.user].append(evt.model_dump())
        return {"swimlanes": swimlanes}

    return app
