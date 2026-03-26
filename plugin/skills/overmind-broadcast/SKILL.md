---
description: "Share important changes or discoveries with the team via Overmind. Triggers when user says: 'share this with the team', 'broadcast', 'tell everyone', 'alert the team', 'notify team', 'team에 알려줘', '팀에 공유', '전파'"
---

# Overmind Broadcast

Share an important change, discovery, or decision with all team members via Overmind.

## Instructions

1. Ask the user what message to broadcast (unless already clear from context)
2. Determine the priority:
   - "urgent": breaking changes, API schema changes, blocking issues
   - "normal": general discoveries, FYIs, non-blocking updates
3. Identify the affected scope (file paths or glob patterns)
4. Use the `overmind_broadcast` MCP tool to send the broadcast:

```
overmind_broadcast(
  repo_id="<derived from git remote>",
  user="<current user>",
  message="<the broadcast message>",
  priority="<urgent|normal>",
  scope="<affected scope>",
  related_files=["<list of affected files>"]
)
```

5. Confirm to the user that the broadcast was sent
