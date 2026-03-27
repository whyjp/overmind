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
from api_client import get_repo_id, get_user, load_state, save_state, api_get
from context_writer import write_context_file
from formatter import format_session_start


CONTEXT_FILE = Path.cwd() / ".claude" / "overmind-context.md"


def main():
    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()
    last_pull = state.get("last_pull_ts")
    if not last_pull:
        last_pull = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "exclude_user": user,
        "since": last_pull,
        "limit": "20",
    })

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
