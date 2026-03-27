#!/usr/bin/env python3
"""PostToolUse hook: accumulate file changes, batch push when flush conditions met.

Also captures Bash error context for enriching subsequent change events.
"""

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

_ERROR_INDICATORS = [
    "error", "Error", "ERROR", "failed", "Failed", "FAILED",
    "exception", "Exception", "traceback", "Traceback",
    "KeyError", "TypeError", "ValueError", "FileNotFoundError",
    "ModuleNotFoundError", "ImportError", "SyntaxError",
]


def _extract_bash_context(input_data: dict) -> str | None:
    """Extract error context from a Bash tool result, if present."""
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        return None
    tool_result = input_data.get("tool_result", "")
    if not tool_result:
        return None
    result_str = str(tool_result)
    if any(indicator in result_str for indicator in _ERROR_INDICATORS):
        return result_str[:200]
    return None


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        input_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()

    # Capture Bash error context for enriching next file change
    bash_context = _extract_bash_context(input_data)
    if bash_context:
        state["last_bash_context"] = bash_context
        save_state(state)

    # Only accumulate file changes for Write/Edit
    if not file_path:
        return

    scope = file_to_scope(file_path)
    now = datetime.now(timezone.utc).isoformat()

    # Check flush before adding new change
    if should_flush(state, scope):
        state = flush_pending_changes(state, repo_id, user)

    # Accumulate this change with context from last Bash error
    context = state.pop("last_bash_context", None)
    pending = state.get("pending_changes", [])
    pending.append({
        "file": file_path,
        "scope": scope,
        "ts": now,
        "action": tool_name or "Edit",
        "lesson": None,
        "context": context,
    })
    state["pending_changes"] = pending
    state["current_scope"] = scope

    save_state(state)


if __name__ == "__main__":
    main()
