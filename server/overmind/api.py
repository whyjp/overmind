"""FastAPI application for Overmind memory sync server."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from overmind.models import (
    BroadcastRequest,
    BroadcastResponse,
    FeedbackRequest,
    FeedbackResponse,
    MemoryEvent,
    PullResponse,
    PushRequest,
    PushResponse,
    ReportResponse,
)
from overmind.store import SQLiteStore


def create_app(data_dir: Optional[Path] = None, store: Optional[SQLiteStore] = None, lifespan=None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if data_dir is None:
        data_dir = Path("data")

    data_dir = Path(data_dir)
    if store is None:
        store = SQLiteStore(data_dir=data_dir)

    outer_lifespan = lifespan

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        await store.init_db()
        if outer_lifespan:
            async with outer_lifespan(app):
                yield
        else:
            yield
        await store.close()

    app = FastAPI(title="Overmind Memory Sync Server", lifespan=app_lifespan)

    # Mount dashboard static files if directory exists
    dashboard_dir = Path(__file__).parent / "dashboard" / "static"
    if dashboard_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    @app.get("/api/repos")
    async def list_repos() -> list[str]:
        return await store.list_repos()

    @app.post("/api/memory/push", response_model=PushResponse)
    async def push_memory(request: PushRequest) -> PushResponse:
        events = [evt.to_event(request.repo_id, request.user) for evt in request.events]
        accepted, duplicates = await store.push(events)
        return PushResponse(accepted=accepted, duplicates=duplicates)

    @app.get("/api/memory/pull", response_model=PullResponse)
    async def pull_memory(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        scope: Optional[str] = Query(default=None),
        user: Optional[str] = Query(default=None),
        exclude_user: Optional[str] = Query(default=None),
        limit: int = Query(default=100),
        detail: str = Query(default="full"),
    ) -> PullResponse:
        return await store.pull(
            repo_id,
            since=since,
            scope=scope,
            user=user,
            exclude_user=exclude_user,
            limit=limit,
            detail=detail,
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
        await store.push([event])

        return BroadcastResponse(id=bcast_id, delivered=True)

    @app.post("/api/memory/feedback", response_model=FeedbackResponse)
    async def record_feedback(request: FeedbackRequest) -> FeedbackResponse:
        was_new, count = await store.record_feedback(
            request.repo_id, request.event_id, request.user, request.type,
        )
        return FeedbackResponse(recorded=was_new, prevented_count=count)

    @app.get("/api/report", response_model=ReportResponse)
    async def get_report(
        repo_id: str = Query(...),
        since: Optional[str] = Query(default=None),
        until: Optional[str] = Query(default=None),
        period: str = Query(default="7d"),
    ) -> ReportResponse:
        return await store.get_repo_stats(repo_id, since=since, until=until, period=period)

    @app.get("/api/report/graph")
    async def get_report_graph(repo_id: str = Query(...)):
        return await store.get_graph_data(repo_id)

    @app.get("/api/report/flow")
    async def get_report_flow(repo_id: str = Query(...)):
        return await store.get_flow_data(repo_id)

    @app.get("/api/report/timeline")
    async def get_report_timeline(repo_id: str = Query(...)):
        pull_resp = await store.pull(repo_id, limit=1000)
        swimlanes: dict[str, list] = defaultdict(list)
        for evt in pull_resp.events:
            swimlanes[evt.user].append(evt.model_dump())
        return {"swimlanes": swimlanes}

    @app.get("/api/stream")
    async def event_stream(repo_id: Optional[str] = Query(default=None)):
        """SSE endpoint: sends 'update' on repo data changes, 'repos' on new repo discovery."""
        async def generate():
            try:
                last_repo_version = store.get_version(repo_id) if repo_id else 0
                last_global_version = store.get_global_version()
                last_repos = set(await store.list_repos())

                yield f"data: {json.dumps({'type': 'connected', 'repos': sorted(last_repos)})}\n\n"

                while True:
                    await asyncio.sleep(1)

                    current_global = store.get_global_version()
                    if current_global == last_global_version:
                        continue  # nothing changed anywhere
                    last_global_version = current_global

                    # Check for new repos
                    current_repos = set(await store.list_repos())
                    new_repos = current_repos - last_repos
                    if new_repos:
                        yield f"data: {json.dumps({'type': 'repos', 'new': sorted(new_repos), 'all': sorted(current_repos)})}\n\n"
                        last_repos = current_repos

                    # Check repo-specific version (independent of new_repos)
                    if repo_id:
                        current_repo_v = store.get_version(repo_id)
                        if current_repo_v != last_repo_version:
                            last_repo_version = current_repo_v
                            yield f"data: {json.dumps({'type': 'update', 'version': current_repo_v})}\n\n"
            except asyncio.CancelledError:
                return  # client disconnected — clean exit

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
