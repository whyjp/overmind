#!/usr/bin/env python3
"""PreToolUse hook: pull related events when editing files."""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_get


def file_to_scope(file_path: str) -> str:
    """Convert file path to scope glob pattern."""
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    if len(parts) == 2:
        return parts[0] + "/*"
    return file_path


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

    lines = [f"Overmind: {result['count']} related events in {scope}:"]
    for evt in result["events"]:
        prefix = "!" if evt.get("priority") == "urgent" else "-"
        lines.append(f"  {prefix} [{evt['type']}] {evt['user']}: {evt['result']}")

    output = {"systemMessage": "\n".join(lines)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
