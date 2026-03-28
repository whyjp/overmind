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


def _git_root() -> str | None:
    """Get git repository root directory, cached."""
    if not hasattr(_git_root, "_cache"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            _git_root._cache = result.stdout.strip().replace("\\", "/") if result.returncode == 0 else None
        except Exception:
            _git_root._cache = None
    return _git_root._cache


def file_to_scope(file_path: str) -> str:
    """Convert file path to scope glob pattern relative to git root.

    e.g. '/abs/path/repo/src/auth/login.ts' -> 'src/auth/*'
         'config.toml' -> '*'
    """
    path = file_path.replace("\\", "/")

    # Make relative to git root if absolute
    root = _git_root()
    if root and path.startswith(root):
        path = path[len(root):].lstrip("/")
    elif root:
        # Try case-insensitive match (Windows)
        root_lower = root.lower()
        path_lower = path.lower()
        if path_lower.startswith(root_lower):
            path = path[len(root):].lstrip("/")

    parts = path.rsplit("/", 1)
    if len(parts) == 2 and parts[0]:
        return parts[0] + "/*"
    return "*"


def get_user() -> str:
    """Get current user identifier."""
    return os.environ.get("OVERMIND_USER", os.environ.get("USER", os.environ.get("USERNAME", "unknown")))


def get_current_branch() -> str | None:
    """Get current git branch name. Returns None if detached HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
        return None if branch == "HEAD" else branch
    except Exception:
        return None


def get_base_branch() -> str | None:
    """Detect the base branch this branch forked from.

    Checks OVERMIND_BASE_BRANCH env var first, then tries main/master
    by looking for a common ancestor.
    """
    env_base = os.environ.get("OVERMIND_BASE_BRANCH")
    if env_base:
        return env_base
    for candidate in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "merge-base", candidate, "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


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


def should_flush(state: dict, new_scope: str) -> bool:
    """Check if pending_changes should be flushed based on count/time/scope-change."""
    pending = state.get("pending_changes", [])
    if not pending:
        return False

    # Count trigger
    if len(pending) >= FLUSH_THRESHOLD:
        return True

    # Time trigger
    last_push = state.get("last_push_ts")
    if not last_push:
        # First accumulation — initialize timestamp, don't flush yet
        state["last_push_ts"] = datetime.now(timezone.utc).isoformat()
        return False
    try:
        last_dt = datetime.fromisoformat(last_push)
        now = datetime.now(timezone.utc)
        if (now - last_dt).total_seconds() >= FLUSH_INTERVAL:
            return True
    except (ValueError, TypeError):
        return True

    # Scope change trigger
    current_scope = state.get("current_scope")
    if current_scope and current_scope != new_scope:
        return True

    return False


_LESSON_TYPE_MAP = {
    "prohibit": "correction",
    "require": "correction",
    "replace": "decision",
    "prefer": "decision",
    "avoid": "discovery",
}


def build_change_events(
    pending: list[dict],
    diff_summary: str = "",
    current_branch: str | None = None,
    base_branch: str | None = None,
) -> list[dict]:
    """Group pending changes by scope into change event dicts.

    If any pending entry has a lesson, the event type is derived from
    the lesson action instead of defaulting to 'change'.
    """
    if not pending:
        return []

    scope_files: dict[str, list[str]] = defaultdict(list)
    scope_contexts: dict[str, list[str]] = defaultdict(list)
    for entry in pending:
        scope = entry["scope"]
        f = entry["file"]
        if f not in scope_files[scope]:
            scope_files[scope].append(f)
        ctx = entry.get("context")
        if ctx and ctx not in scope_contexts[scope]:
            scope_contexts[scope].append(ctx)

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for scope, files in scope_files.items():
        basenames = [f.replace("\\", "/").rsplit("/", 1)[-1] for f in files]
        count = len(files)
        file_label = "file" if count == 1 else "files"
        what = f"Modified {scope} ({count} {file_label}: {', '.join(sorted(basenames))})"

        parts = [what]
        contexts = scope_contexts.get(scope, [])
        if contexts:
            parts.append(f"Context: {'; '.join(contexts)}")
        if diff_summary:
            parts.append(f"Diff:\n{diff_summary}")

        result = "\n".join(parts)

        # Derive event type from lesson if any pending entry has one
        evt_type = "change"
        for entry in pending:
            if entry.get("scope") == scope and entry.get("lesson"):
                action = entry["lesson"].get("action", "")
                evt_type = _LESSON_TYPE_MAP.get(action, "change")
                break

        evt: dict = {
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "type": evt_type,
            "ts": now,
            "result": result,
            "files": files,
            "scope": scope,
        }
        if current_branch:
            evt["current_branch"] = current_branch
        if base_branch:
            evt["base_branch"] = base_branch
        events.append(evt)

    return events


def flush_pending_changes(state: dict, repo_id: str, user: str) -> dict:
    """Flush all pending_changes → push scope-grouped change events. Returns updated state."""
    from diff_collector import collect_diff_summary

    pending = state.get("pending_changes", [])
    if not pending:
        return state

    all_files = list({e["file"] for e in pending})
    diff_summary = collect_diff_summary(all_files)
    events = build_change_events(
        pending,
        diff_summary=diff_summary,
        current_branch=state.get("current_branch"),
        base_branch=state.get("base_branch"),
    )
    if events:
        api_post("/api/memory/push", {
            "repo_id": repo_id,
            "user": user,
            "events": events,
        })

    state["pending_changes"] = []
    state["last_push_ts"] = datetime.now(timezone.utc).isoformat()
    return state
