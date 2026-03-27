#!/usr/bin/env python3
"""SessionEnd hook: flush any remaining pending changes to Overmind server."""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import flush_pending_changes, get_repo_id, get_user, load_state, save_state


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        input_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()

    # Flush remaining pending changes
    if state.get("pending_changes"):
        state = flush_pending_changes(state, repo_id, user)

    # Clear session tracking state
    state.pop("current_scope", None)
    save_state(state)


if __name__ == "__main__":
    main()
