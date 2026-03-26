#!/usr/bin/env python3
"""SessionStart hook: pull latest events from Overmind server."""

import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, load_state, save_state, api_get


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

    state["last_pull_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    lines = [f"Overmind: {result['count']} team events since last session:"]
    for evt in result["events"]:
        prefix = "!" if evt.get("priority") == "urgent" else "-"
        lines.append(f"  {prefix} [{evt['type']}] {evt['user']}: {evt['result']}")
        if evt.get("process"):
            for step in evt["process"][:3]:
                lines.append(f"      > {step}")

    output = {"systemMessage": "\n".join(lines)}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
