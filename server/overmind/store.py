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
        # Pull history: {repo_id -> [(user, event_id, ts)]}
        self._pull_log: dict[str, list[dict]] = defaultdict(list)
        # Version counter per repo — increments on every push (for SSE change detection)
        self._version: dict[str, int] = defaultdict(int)
        # Global version — increments on any push to any repo (for new repo detection)
        self._global_version: int = 0

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

    def _pull_log_file(self, repo_id: str) -> Path:
        return self._repo_dir(repo_id) / "pull_log.jsonl"

    def _append_pull_log(self, repo_id: str, entry: dict) -> None:
        """Append a pull log entry to disk."""
        file_path = self._pull_log_file(repo_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _load_pull_log(self, repo_id: str) -> list[dict]:
        """Load pull log from disk for a repo."""
        file_path = self._pull_log_file(repo_id)
        if not file_path.exists():
            return []
        entries = []
        try:
            text = file_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        except OSError:
            pass
        return entries

    def _ensure_pull_log_loaded(self, repo_id: str) -> None:
        """Load pull log from disk into memory if not already loaded."""
        if repo_id not in self._pull_log:
            self._pull_log[repo_id] = self._load_pull_log(repo_id)

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

        # Bump version for SSE change detection
        if accepted > 0:
            self._global_version += 1
            repo_ids = {evt.repo_id for evt in events}
            for rid in repo_ids:
                self._version[rid] += 1

        return accepted, duplicates

    def get_version(self, repo_id: str) -> int:
        """Return current version counter for a repo (for SSE change detection)."""
        return self._version[repo_id]

    def get_global_version(self) -> int:
        """Return global version counter (for new repo detection via SSE)."""
        return self._global_version

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

        # Record pull history for graph visualization (persist to disk)
        puller = exclude_user  # the user who's pulling (they exclude themselves)
        if puller:
            self._ensure_pull_log_loaded(repo_id)
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            for evt in result_events:
                entry = {
                    "puller": puller,
                    "event_id": evt.id,
                    "event_user": evt.user,
                    "ts": now_iso,
                }
                self._pull_log[repo_id].append(entry)
                self._append_pull_log(repo_id, entry)

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

        # Count unique (puller, event_id) pairs from pull log
        self._ensure_pull_log_loaded(repo_id)
        pull_log_entries = self._pull_log.get(repo_id, [])
        unique_pulls = len({(e["puller"], e["event_id"]) for e in pull_log_entries})

        return ReportResponse(
            repo_id=repo_id,
            period=period,
            total_pushes=len(filtered),
            total_pulls=unique_pulls,
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

        # Pull edges: create ghost (replica) nodes for consumed events
        # Ghost node = a copy of the event shown under the consuming agent
        self._ensure_pull_log_loaded(repo_id)
        pull_seen: set[tuple[str, str]] = set()  # (puller, event_id) dedup
        for entry in self._pull_log.get(repo_id, []):
            puller = entry["puller"]
            evt_id = entry["event_id"]
            evt_user = entry.get("event_user", "")

            # Skip self-consumption (shouldn't happen, but safety)
            if puller == evt_user:
                continue

            key = (puller, evt_id)
            if key in pull_seen:
                continue
            pull_seen.add(key)

            # Ensure puller user node exists
            if puller not in seen_users:
                nodes.append(GraphNode(id=f"user:{puller}", type="user", label=puller))
                seen_users.add(puller)

            # Find original event to get its label/type
            orig_evt = next((e for e in all_events if e.id == evt_id), None)
            ghost_id = f"ghost:{puller}:{evt_id}"

            # Create ghost node (type="ghost")
            nodes.append(GraphNode(
                id=ghost_id,
                type="event",  # render as event but with ghost styling
                label=orig_evt.result[:60] if orig_evt else evt_id,
                event_type=orig_evt.type if orig_evt else None,
                data={
                    "ghost": True,
                    "consumed_by": puller,
                    "original_user": evt_user,
                    "result": orig_evt.result if orig_evt else "",
                    "ts": entry.get("ts", ""),
                },
            ))

            # Edge: puller user → ghost (consumed)
            edges.append(
                GraphEdge(source=f"user:{puller}", target=ghost_id, relation="consumed")
            )

            # Edge: original event → ghost (propagated)
            edges.append(
                GraphEdge(source=f"event:{evt_id}", target=ghost_id, relation="pulled")
            )

        return GraphResponse(nodes=nodes, edges=edges, polymorphisms=polymorphisms)

    def get_flow_data(self, repo_id: str) -> dict:
        """Return chronological flow data: push events + pull links (no ghosts).

        Returns:
            {
                "agents": ["dev_a", "dev_b", ...],
                "events": [{id, user, type, result, ts, scope, files}, ...],
                "pull_links": [{puller, event_id, event_user, ts}, ...],
                "polymorphisms": [...]
            }
        """
        all_events = self._read_repo_events(repo_id)

        # Sort events chronologically
        all_events.sort(key=lambda e: _parse_ts(e.ts))

        agents = sorted({e.user for e in all_events})
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

        # Pull links: deduplicated (puller, event_id) pairs
        self._ensure_pull_log_loaded(repo_id)
        pull_seen: set[tuple[str, str]] = set()
        pull_links = []
        for entry in self._pull_log.get(repo_id, []):
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
