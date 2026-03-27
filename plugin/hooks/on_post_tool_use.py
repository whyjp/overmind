#!/usr/bin/env python3
"""PostToolUse hook: accumulate file changes, batch push when flush conditions met."""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from datetime import datetime, timezone

from api_client import (
    file_to_scope,
    flush_pending_changes,
    get_repo_id,
    get_user,
    load_state,
    save_state,
    should_flush,
)


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    scope = file_to_scope(file_path)
    now = datetime.now(timezone.utc).isoformat()

    state = load_state()

    # Check flush before adding new change
    if should_flush(state, scope):
        state = flush_pending_changes(state, repo_id, user)

    # Accumulate this change
    pending = state.get("pending_changes", [])
    pending.append({
        "file": file_path,
        "scope": scope,
        "ts": now,
        "action": input_data.get("tool_name", "Edit"),
        "lesson": None,
    })
    state["pending_changes"] = pending
    state["current_scope"] = scope

    save_state(state)


if __name__ == "__main__":
    main()
