#!/usr/bin/env python3
"""SessionStart hook: pull latest events from Overmind server.

Writes team context to .claude/overmind-context.md for persistent awareness,
and outputs systemMessage for immediate visibility.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, load_state, save_state, api_get, get_current_branch, get_base_branch
from context_writer import write_context_file
from formatter import format_session_start


CONTEXT_FILE = Path.cwd() / ".claude" / "overmind-context.md"


def main():
    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()

    # Detect and cache branch info (explicit cwd for robustness)
    project_dir = str(Path.cwd())
    current_branch = get_current_branch(cwd=project_dir)
    base_branch = get_base_branch(cwd=project_dir)
    state["current_branch"] = current_branch
    state["base_branch"] = base_branch
    # Save branch info immediately so PostToolUse can use it even if pull returns 0
    save_state(state)

    last_pull = state.get("last_pull_ts")
    if not last_pull:
        last_pull = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    pull_params: dict = {
        "repo_id": repo_id,
        "exclude_user": user,
        "since": last_pull,
        "limit": "20",
    }
    if current_branch:
        pull_params["current_branch"] = current_branch
    if base_branch:
        pull_params["base_branch"] = base_branch

    result = api_get("/api/memory/pull", pull_params)

    if not result or result.get("count", 0) == 0:
        return

    events = result["events"]

    state["last_pull_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Write persistent context file
    write_context_file(events, CONTEXT_FILE)

    # Output systemMessage for immediate visibility
    message = format_session_start(events)
    if message:
        print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    main()
