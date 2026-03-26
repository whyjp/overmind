"""FastMCP wrapper exposing Overmind store as MCP tools."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastmcp import FastMCP

from overmind.store import MemoryStore
from overmind.models import MemoryEvent


def create_mcp_server(store: MemoryStore) -> FastMCP:
    mcp = FastMCP("Overmind", instructions="Distributed memory sync for Claude Code")

    @mcp.tool()
    def overmind_push(repo_id: str, user: str, events: list[dict]) -> dict:
        """Push memory events to Overmind server.

        Args:
            repo_id: Repository identifier (e.g. "github.com/user/project")
            user: User/agent identifier
            events: List of event dicts with id, type, ts, result, and optional files/process/priority/scope
        """
        parsed = []
        for e in events:
            parsed.append(MemoryEvent(
                repo_id=repo_id,
                user=user,
                **e,
            ))
        accepted, duplicates = store.push(parsed)
        return {"accepted": accepted, "duplicates": duplicates}

    @mcp.tool()
    def overmind_pull(
        repo_id: str,
        exclude_user: str | None = None,
        since: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Pull other agents' memory events from Overmind server.

        Args:
            repo_id: Repository identifier
            exclude_user: Exclude events from this user (typically yourself)
            since: ISO 8601 timestamp - only return events after this time
            scope: Glob pattern to filter by file scope (e.g. "src/auth/*")
            limit: Maximum events to return (default 50)
        """
        result = store.pull(
            repo_id=repo_id,
            exclude_user=exclude_user,
            since=since,
            scope=scope,
            limit=limit,
        )
        return result.model_dump()

    @mcp.tool()
    def overmind_broadcast(
        repo_id: str,
        user: str,
        message: str,
        priority: str = "normal",
        scope: str | None = None,
        related_files: list[str] | None = None,
    ) -> dict:
        """Broadcast urgent message to all agents on this repo.

        Args:
            repo_id: Repository identifier
            user: Sender identifier
            message: Broadcast message content
            priority: "normal" or "urgent"
            scope: Affected scope (e.g. "src/api/*")
            related_files: List of affected file paths
        """
        evt_id = f"bcast_{uuid.uuid4().hex[:12]}"
        evt = MemoryEvent(
            id=evt_id,
            repo_id=repo_id,
            user=user,
            ts=datetime.now(timezone.utc).isoformat(),
            type="broadcast",
            result=message,
            files=related_files or [],
            priority=priority,
            scope=scope,
        )
        store.push([evt])
        return {"id": evt_id, "delivered": True}

    return mcp
