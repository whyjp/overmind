"""Format pulled Overmind events into instructional systemMessage prompts."""

from __future__ import annotations

# Event types that Claude should treat as rules/instructions
RULE_TYPES = {"correction", "decision"}
# Event types that are informational context
CONTEXT_TYPES = {"discovery", "change"}
# Broadcast is its own category
BROADCAST_TYPE = "broadcast"


def _has_diff(result: str) -> bool:
    """Check if a result string contains a diff snippet."""
    return "\nDiff:" in result or result.startswith("Diff:")


def format_session_start(events: list[dict]) -> str | None:
    """Format events for SessionStart hook — full instructional prompt.

    Events with diffs are presented as actionable FIXES that the agent
    should apply proactively. Events without diffs remain informational.
    """
    if not events:
        return None

    rules = []
    fixes = []
    context = []
    broadcasts = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")
        process = evt.get("process", [])

        entry = f"- {result} (by {user})"
        if priority == "high_priority":
            entry = f"- [HIGH PRIORITY] {result} (by {user})"

        if etype in RULE_TYPES:
            rules.append(entry)
            # Include reasoning for corrections/decisions
            for step in process[:2]:
                rules.append(f"  Reason: {step}")
        elif etype == BROADCAST_TYPE:
            broadcasts.append(entry)
        elif _has_diff(result):
            # Events with diffs are actionable teammate fixes
            fixes.append(entry)
        else:
            context.append(entry)

    lines = ["[OVERMIND] Team context from other agents on this repo."]
    lines.append("")

    if rules:
        lines.append("RULES — Apply these to all actions in this session:")
        lines.extend(rules)
        lines.append("")

    if fixes:
        lines.append(
            "FIXES BY TEAMMATES — Another agent already solved these problems. "
            "If you encounter errors, apply ALL of these diffs at once instead of "
            "fixing one issue at a time:"
        )
        lines.extend(fixes)
        lines.append("")

    if context:
        lines.append("CONTEXT — Be aware of these when relevant:")
        lines.extend(context)
        lines.append("")

    if broadcasts:
        lines.append("ANNOUNCEMENTS:")
        lines.extend(broadcasts)
        lines.append("")

    if fixes:
        lines.append(
            "IMPORTANT: When you hit an error, apply ALL fixes above at once — "
            "do NOT re-discover issues that teammates already solved. "
            "Follow RULES strictly. Use CONTEXT to inform decisions."
        )
    else:
        lines.append(
            "Follow RULES strictly. Use CONTEXT to inform decisions when relevant."
        )

    return "\n".join(lines)


def format_pre_tool_use(events: list[dict], scope: str) -> str | None:
    """Format events for PreToolUse hook — scope-specific warnings.

    Events with diffs are shown as FIXES — the agent should apply all of them
    at once instead of discovering issues one by one.
    """
    if not events:
        return None

    rules = []
    fixes = []
    warnings = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")

        if etype in RULE_TYPES or priority == "high_priority":
            prefix = "[HIGH PRIORITY] " if priority == "high_priority" else ""
            rules.append(f"- {prefix}{result} (by {user})")
        elif _has_diff(result):
            fixes.append(f"- {result} (by {user})")
        else:
            warnings.append(f"- {result} (by {user})")

    lines = [f"[OVERMIND] Team context for {scope}:"]
    lines.append("")

    if rules:
        lines.append("RULES for this scope — follow before proceeding:")
        lines.extend(rules)
        lines.append("")

    if fixes:
        lines.append(
            "FIXES BY TEAMMATES — Apply ALL of these diffs in this edit. "
            "Do not fix only the current error; fix everything at once:"
        )
        lines.extend(fixes)
        lines.append("")

    if warnings:
        lines.append("Related context:")
        lines.extend(warnings)
        lines.append("")

    if fixes:
        lines.append(
            "IMPORTANT: Apply ALL fixes above in a single edit — "
            "another agent already discovered and solved these problems."
        )
    else:
        lines.append("Check these before making changes to this scope.")

    return "\n".join(lines)
