#!/usr/bin/env python3
"""PreToolUse hook: pull related events when editing files.

If urgent corrections exist for the target scope, BLOCK the tool use.
Otherwise, inject context as systemMessage.
"""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_get, api_post, file_to_scope
from formatter import format_pre_tool_use


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

    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "scope": scope,
        "exclude_user": user,
        "limit": "5",
    })

    if not result or result.get("count", 0) == 0:
        return

    events = result["events"]

    # Check for blocking rules: urgent corrections/decisions for this scope
    blocking_rules = [
        evt for evt in events
        if evt.get("priority") == "urgent"
        and evt.get("type") in ("correction", "decision")
    ]

    if blocking_rules:
        # Auto-feedback: these rules prevented an error
        for evt in blocking_rules:
            api_post("/api/memory/feedback", {
                "repo_id": repo_id,
                "event_id": evt["id"],
                "user": user,
                "type": "prevented_error",
            })

        reasons = [evt["result"] for evt in blocking_rules]
        reason = " | ".join(reasons)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"[OVERMIND BLOCK] Team rule for {scope}: {reason}",
            }
        }
        print(json.dumps(output))
        return

    # Non-blocking: inject context as systemMessage
    message = format_pre_tool_use(events, scope)
    if message:
        print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    main()
