"""Shared HTTP client for Overmind plugin hooks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError


OVERMIND_URL = os.environ.get("OVERMIND_URL", "http://localhost:7777")
STATE_FILE = Path(os.environ.get("OVERMIND_STATE_FILE", str(Path.home() / ".overmind_state.json")))


def get_repo_id() -> str | None:
    """Derive repo_id from git remote origin URL, or OVERMIND_REPO_ID env var."""
    env_repo = os.environ.get("OVERMIND_REPO_ID")
    if env_repo:
        return env_repo
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        return normalize_git_remote(url)
    except Exception:
        return None


def normalize_git_remote(url: str) -> str:
    """Normalize git remote URL to repo_id."""
    url = url.strip()
    if url.startswith("git@"):
        url = url.replace(":", "/", 1).replace("git@", "")
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    if url.endswith(".git"):
        url = url[:-4]
    url = url.rstrip("/")
    return url


def file_to_scope(file_path: str) -> str:
    """Convert file path to scope glob pattern. e.g. 'src/auth/login.ts' -> 'src/auth/*'."""
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    if len(parts) == 2:
        return parts[0] + "/*"
    return file_path


def get_user() -> str:
    """Get current user identifier."""
    return os.environ.get("OVERMIND_USER", os.environ.get("USER", os.environ.get("USERNAME", "unknown")))


def load_state() -> dict:
    """Load persistent state (last_pull_ts etc)."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    """Save persistent state."""
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def api_post(path: str, body: dict) -> dict | None:
    """POST JSON to Overmind server."""
    try:
        req = Request(
            f"{OVERMIND_URL}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (URLError, Exception) as e:
        print(f"Overmind API error: {e}", file=sys.stderr)
        return None


def api_get(path: str, params: dict | None = None) -> dict | None:
    """GET from Overmind server."""
    try:
        url = f"{OVERMIND_URL}{path}"
        if params:
            qs = urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{qs}"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (URLError, Exception) as e:
        print(f"Overmind API error: {e}", file=sys.stderr)
        return None


# ------------------------------------------------------------------
# Flush logic: accumulate pending changes → scope-grouped events
# ------------------------------------------------------------------

FLUSH_THRESHOLD = int(os.environ.get("OVERMIND_FLUSH_THRESHOLD", "5"))
FLUSH_INTERVAL = int(os.environ.get("OVERMIND_FLUSH_INTERVAL", "1800"))


def build_change_events(pending: list[dict]) -> list[dict]:
    """Group pending changes by scope into change event dicts."""
    if not pending:
        return []

    scope_files: dict[str, list[str]] = defaultdict(list)
    for entry in pending:
        scope = entry["scope"]
        f = entry["file"]
        if f not in scope_files[scope]:
            scope_files[scope].append(f)

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for scope, files in scope_files.items():
        basenames = [f.replace("\\", "/").rsplit("/", 1)[-1] for f in files]
        count = len(files)
        file_label = "file" if count == 1 else "files"
        result = f"Modified {scope} ({count} {file_label}: {', '.join(sorted(basenames))})"
        events.append({
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "type": "change",
            "ts": now,
            "result": result,
            "files": files,
            "scope": scope,
        })

    return events


def flush_pending_changes(state: dict, repo_id: str, user: str) -> dict:
    """Flush all pending_changes → push scope-grouped change events. Returns updated state."""
    pending = state.get("pending_changes", [])
    if not pending:
        return state

    events = build_change_events(pending)
    if events:
        api_post("/api/memory/push", {
            "repo_id": repo_id,
            "user": user,
            "events": events,
        })

    state["pending_changes"] = []
    state["last_push_ts"] = datetime.now(timezone.utc).isoformat()
    return state
