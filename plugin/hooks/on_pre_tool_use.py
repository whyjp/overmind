#!/usr/bin/env python3
"""PreToolUse hook: pull related events when editing files.

Uses conflict_detector to compare structured lessons against tool input.
Deny/warn/ignore based on lesson action and target matching.
"""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_get, api_post, file_to_scope
from conflict_detector import detect_conflict
from formatter import format_pre_tool_use


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()

    # Pull WITHOUT scope filter — scope matching uses absolute paths which
    # differ between agents. Pull all recent events and let detector decide.
    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "exclude_user": user,
        "limit": "10",
    })

    if not result or result.get("count", 0) == 0:
        return

    events = result["events"]

    # Conflict detection: structured lessons + legacy high_priority fallback
    verdict, matching = detect_conflict(tool_name, tool_input, events)

    if verdict == "deny":
        # Auto-feedback: these rules prevented an error
        for evt in matching:
            api_post("/api/memory/feedback", {
                "repo_id": repo_id,
                "event_id": evt["id"],
                "user": user,
                "type": "prevented_error",
            })

        reasons = [evt["result"] for evt in matching]
        reason = " | ".join(reasons)
        scope = file_to_scope(file_path)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"[OVERMIND BLOCK] Team rule for {scope}: {reason}",
            }
        }
        print(json.dumps(output))
        return

    if verdict == "warn":
        reasons = [evt["result"] for evt in matching]
        scope = file_to_scope(file_path)
        warning = (
            f"[OVERMIND WARNING] Potential conflict with team lessons for {scope}:\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )
        print(json.dumps({"systemMessage": warning}))
        return

    # No conflict: inject general context
    scope = file_to_scope(file_path)
    message = format_pre_tool_use(events, scope)
    if message:
        print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    main()
