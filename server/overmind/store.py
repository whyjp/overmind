"""JSONL-backed memory store for Overmind events."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

from overmind.models import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryEvent,
    PolymorphismAlert,
    PullResponse,
    ReportResponse,
)


def _safe_repo_id(repo_id: str) -> str:
    """Convert repo_id to a filesystem-safe string."""
    return repo_id.replace("/", "_").replace(":", "_")


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    return datetime.fromisoformat(ts)


def _file_to_scope(file_path: str) -> str:
    """Convert a file path like 'src/auth/login.ts' to 'src/auth/*'."""
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return "*"
    return "/".join(parts[:-1]) + "/*"


class MemoryStore:
    """Append-only JSONL store for MemoryEvent objects."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        # Per-repo in-memory dedup sets: {repo_id -> set of event ids}
        self._seen_ids: dict[str, set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Repo listing
    # ------------------------------------------------------------------

    def list_repos(self) -> list[str]:
        """Return all known repo_ids by scanning the data directory."""
        repos_dir = self.data_dir / "repos"
        if not repos_dir.exists():
            return []
        result = []
        for d in sorted(repos_dir.iterdir()):
            if d.is_dir():
                # Reverse the _safe_repo_id transform: _ back to /
                # e.g. "github.com_user_project" -> "github.com/user/project"
                name = d.name
                # First underscore segment is the domain (github.com)
                # We need to restore the slashes. Convention: domain_org_repo
                parts = name.split("_")
                if len(parts) >= 3 and "." in parts[0]:
                    # domain.com_org_repo -> domain.com/org/repo
                    repo_id = parts[0] + "/" + "/".join(parts[1:])
                else:
                    repo_id = name.replace("_", "/")
                result.append(repo_id)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repo_dir(self, repo_id: str) -> Path:
        return self.data_dir / "repos" / _safe_repo_id(repo_id)

    def _event_file(self, repo_id: str, user: str, ts: str) -> Path:
        dt = _parse_ts(ts)
        date_str = dt.strftime("%Y-%m-%d")
        return self._repo_dir(repo_id) / "events" / user / f"{date_str}.jsonl"

    def _read_repo_events(self, repo_id: str) -> list[MemoryEvent]:
        """Read all events for a repo from disk, rebuilding _seen_ids cache."""
        repo_dir = self._repo_dir(repo_id)
        events_root = repo_dir / "events"
        events: list[MemoryEvent] = []

        if not events_root.exists():
            return events

        # Reset seen ids for this repo so we rebuild fresh from disk
        self._seen_ids[repo_id] = set()

        for jsonl_file in events_root.rglob("*.jsonl"):
            try:
                text = jsonl_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    evt = MemoryEvent(**data)
                    self._seen_ids[repo_id].add(evt.id)
                    events.append(evt)
                except Exception:
                    continue

        return events

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push(self, events: list[MemoryEvent]) -> tuple[int, int]:
        """Append new events to JSONL files. Returns (accepted, duplicates)."""
        accepted = 0
        duplicates = 0

        for evt in events:
            repo_id = evt.repo_id
            seen = self._seen_ids[repo_id]

            if evt.id in seen:
                duplicates += 1
                continue

            # Write to disk
            file_path = self._event_file(repo_id, evt.user, evt.ts)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("a", encoding="utf-8") as f:
                f.write(evt.model_dump_json() + "\n")

            seen.add(evt.id)
            accepted += 1

        return accepted, duplicates

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    def _matches_scope(self, evt: MemoryEvent, scope: Optional[str]) -> bool:
        """Return True if the event matches the given scope glob."""
        if scope is None:
            return True
        # Check event.scope field directly
        if evt.scope and fnmatch(evt.scope, scope):
            return True
        # Check each file in evt.files
        for f in evt.files:
            if fnmatch(f, scope):
                return True
        return False

    def pull(
        self,
        repo_id: str,
        *,
        user: Optional[str] = None,
        exclude_user: Optional[str] = None,
        since: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> PullResponse:
        """Return events for a repo, sorted urgent-first then newest-first."""
        all_events = self._read_repo_events(repo_id)

        since_dt = _parse_ts(since) if since else None

        filtered: list[MemoryEvent] = []
        for evt in all_events:
            if user is not None and evt.user != user:
                continue
            if exclude_user is not None and evt.user == exclude_user:
                continue
            if since_dt is not None:
                evt_dt = _parse_ts(evt.ts)
                if evt_dt <= since_dt:
                    continue
            if not self._matches_scope(evt, scope):
                continue
            filtered.append(evt)

        # Sort: urgent first, then newest first within each priority group
        urgent = sorted(
            [e for e in filtered if e.priority == "urgent"],
            key=lambda e: _parse_ts(e.ts),
            reverse=True,
        )
        normal = sorted(
            [e for e in filtered if e.priority != "urgent"],
            key=lambda e: _parse_ts(e.ts),
            reverse=True,
        )
        sorted_events = urgent + normal

        has_more = len(sorted_events) > limit
        result_events = sorted_events[:limit]

        return PullResponse(
            events=result_events,
            count=len(result_events),
            has_more=has_more,
        )

    # ------------------------------------------------------------------
    # Stats / Graph
    # ------------------------------------------------------------------

    def get_repo_stats(
        self,
        repo_id: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        period: str = "7d",
    ) -> ReportResponse:
        """Return aggregate statistics for a repo."""
        all_events = self._read_repo_events(repo_id)

        since_dt = _parse_ts(since) if since else None
        until_dt = _parse_ts(until) if until else None

        filtered = []
        for evt in all_events:
            evt_dt = _parse_ts(evt.ts)
            if since_dt and evt_dt < since_dt:
                continue
            if until_dt and evt_dt > until_dt:
                continue
            filtered.append(evt)

        unique_users = len({e.user for e in filtered})
        events_by_type: dict[str, int] = defaultdict(int)
        for evt in filtered:
            events_by_type[evt.type] += 1

        return ReportResponse(
            repo_id=repo_id,
            period=period,
            total_pushes=len(filtered),
            total_pulls=0,
            unique_users=unique_users,
            events_by_type=dict(events_by_type),
        )

    def get_graph_data(self, repo_id: str) -> GraphResponse:
        """Return graph nodes, edges, and polymorphism alerts for a repo."""
        all_events = self._read_repo_events(repo_id)

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_users: set[str] = set()
        seen_scopes: set[str] = set()
        # scope -> set of users
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
                    label=evt.id,
                    event_type=evt.type,
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

        # Polymorphism alerts: scopes touched by multiple users
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

        return GraphResponse(nodes=nodes, edges=edges, polymorphisms=polymorphisms)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_expired(self, repo_id: str, ttl_days: int = 30) -> int:
        """Remove events older than ttl_days. Returns count of removed events."""
        repo_dir = self._repo_dir(repo_id)
        events_root = repo_dir / "events"
        if not events_root.exists():
            return 0

        now = datetime.now(tz=timezone.utc)
        removed = 0

        for jsonl_file in list(events_root.rglob("*.jsonl")):
            try:
                text = jsonl_file.read_text(encoding="utf-8")
            except OSError:
                continue

            kept_lines = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    evt = MemoryEvent(**data)
                    evt_dt = _parse_ts(evt.ts)
                    age = (now - evt_dt).days
                    if age <= ttl_days:
                        kept_lines.append(line)
                    else:
                        removed += 1
                except Exception:
                    kept_lines.append(line)

            if removed > 0:
                if kept_lines:
                    jsonl_file.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
                else:
                    jsonl_file.unlink(missing_ok=True)

        # Rebuild cache for this repo
        self._seen_ids.pop(repo_id, None)
        self._read_repo_events(repo_id)

        return removed
