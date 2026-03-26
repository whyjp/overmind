---
description: "View Overmind status and team activity. Triggers when user says: 'overmind status', 'show overmind', 'team activity', 'memory report', 'overmind 현황', '팀 활동'"
---

# Overmind Report

Show the current Overmind status: recent team events, active users, and statistics.

## Instructions

1. Use the `overmind_pull` MCP tool to get recent events:

```
overmind_pull(
  repo_id="<derived from git remote>",
  exclude_user="<current user>",
  limit=20
)
```

2. Present the results to the user in a readable format:
   - Group by user
   - Highlight urgent/broadcast events
   - Show process logs for corrections/decisions
   - Flag any polymorphism (same scope, different users with different intents)

3. If the user wants detailed statistics, direct them to the dashboard:
   `http://localhost:7777/dashboard`
