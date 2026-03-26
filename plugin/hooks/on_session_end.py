#!/usr/bin/env python3
"""SessionEnd hook: push session events to Overmind server."""

import json
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, api_post


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()

    evt = {
        "id": f"session_{uuid.uuid4().hex[:12]}",
        "type": "discovery",
        "ts": datetime.now(timezone.utc).isoformat(),
        "result": f"Session ended by {user}",
    }

    api_post("/api/memory/push", {
        "repo_id": repo_id,
        "user": user,
        "events": [evt],
    })


if __name__ == "__main__":
    main()
