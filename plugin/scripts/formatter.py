"""Format pulled Overmind events into instructional systemMessage prompts."""

from __future__ import annotations

# Event types that Claude should treat as rules/instructions
RULE_TYPES = {"correction", "decision"}
# Event types that are informational context
CONTEXT_TYPES = {"discovery", "change"}
# Broadcast is its own category
BROADCAST_TYPE = "broadcast"


def format_session_start(events: list[dict]) -> str | None:
    """Format events for SessionStart hook — full instructional prompt."""
    if not events:
        return None

    rules = []
    context = []
    broadcasts = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")
        process = evt.get("process", [])

        entry = f"- {result} (by {user})"
        if priority == "urgent":
            entry = f"- [URGENT] {result} (by {user})"

        if etype in RULE_TYPES:
            rules.append(entry)
            # Include reasoning for corrections/decisions
            for step in process[:2]:
                rules.append(f"  Reason: {step}")
        elif etype == BROADCAST_TYPE:
            broadcasts.append(entry)
        else:
            context.append(entry)

    lines = ["[OVERMIND] Team context from other agents on this repo."]
    lines.append("")

    if rules:
        lines.append("RULES — Apply these to all actions in this session:")
        lines.extend(rules)
        lines.append("")

    if context:
        lines.append("CONTEXT — Be aware of these when relevant:")
        lines.extend(context)
        lines.append("")

    if broadcasts:
        lines.append("ANNOUNCEMENTS:")
        lines.extend(broadcasts)
        lines.append("")

    lines.append("Follow RULES strictly. Use CONTEXT to inform decisions when relevant.")

    return "\n".join(lines)


def format_pre_tool_use(events: list[dict], scope: str) -> str | None:
    """Format events for PreToolUse hook — scope-specific warnings."""
    if not events:
        return None

    rules = []
    warnings = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")

        if etype in RULE_TYPES or priority == "urgent":
            prefix = "[URGENT] " if priority == "urgent" else ""
            rules.append(f"- {prefix}{result} (by {user})")
        else:
            warnings.append(f"- {result} (by {user})")

    lines = [f"[OVERMIND] Team context for {scope}:"]
    lines.append("")

    if rules:
        lines.append("RULES for this scope — follow before proceeding:")
        lines.extend(rules)
        lines.append("")

    if warnings:
        lines.append("Related context:")
        lines.extend(warnings)
        lines.append("")

    lines.append("Check these before making changes to this scope.")

    return "\n".join(lines)
