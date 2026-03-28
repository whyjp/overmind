"""Format pulled Overmind events into systemMessage prompts.

Design principle: Present FACTS, not instructions. The formatter tells the agent
what other agents did (including diffs), but does NOT prescribe what to do with
that information. The agent should naturally use the context to work more efficiently.
"""

from __future__ import annotations

# Event types that Claude should treat as rules/instructions
RULE_TYPES = {"correction", "decision"}
# Event types that are informational context
CONTEXT_TYPES = {"discovery", "change"}
# Forward-looking declarations
INTENT_TYPE = "intent"
# Broadcast is its own category
BROADCAST_TYPE = "broadcast"


def _has_diff(result: str) -> bool:
    """Check if a result string contains a diff snippet."""
    return "\nDiff:" in result or result.startswith("Diff:")


def format_session_start(events: list[dict]) -> str | None:
    """Format events for SessionStart hook — full context prompt.

    Events are categorized by type. Diff-containing events are separated as
    TEAMMATE CHANGES for visibility, but no behavioral instructions are given.
    """
    if not events:
        return None

    rules = []
    intents = []
    changes = []
    context = []
    broadcasts = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")
        process = evt.get("process", [])
        branch = evt.get("current_branch")

        branch_tag = f" [{branch}]" if branch else ""
        entry = f"- {result} (by {user}{branch_tag})"
        if priority == "high_priority":
            entry = f"- [HIGH PRIORITY] {result} (by {user}{branch_tag})"

        if etype in RULE_TYPES:
            rules.append(entry)
            for step in process[:2]:
                rules.append(f"  Reason: {step}")
        elif etype == INTENT_TYPE:
            intents.append(entry)
        elif etype == BROADCAST_TYPE:
            broadcasts.append(entry)
        elif _has_diff(result):
            changes.append(entry)
        else:
            context.append(entry)

    lines = ["[OVERMIND] Team context from other agents on this repo."]
    lines.append("")

    if rules:
        lines.append("RULES — Apply these to all actions in this session:")
        lines.extend(rules)
        lines.append("")

    if intents:
        lines.append("PLANNED CHANGES — Other agents intend to do this:")
        lines.extend(intents)
        lines.append("")

    if changes:
        lines.append("TEAMMATE CHANGES — What other agents changed (with diffs):")
        lines.extend(changes)
        lines.append("")

    if context:
        lines.append("CONTEXT — Other activity on this repo:")
        lines.extend(context)
        lines.append("")

    if broadcasts:
        lines.append("ANNOUNCEMENTS:")
        lines.extend(broadcasts)
        lines.append("")

    lines.append(
        "Follow RULES strictly. Use TEAMMATE CHANGES and CONTEXT to inform your decisions."
    )

    return "\n".join(lines)


def format_pre_tool_use(events: list[dict], scope: str) -> str | None:
    """Format events for PreToolUse hook — scope-specific context.

    Shows what other agents did in this scope. Diff-containing events are
    shown as TEAMMATE CHANGES for visibility.
    """
    if not events:
        return None

    rules = []
    intents = []
    changes = []
    warnings = []

    for evt in events:
        etype = evt.get("type", "")
        user = evt.get("user", "unknown")
        result = evt.get("result", "")
        priority = evt.get("priority", "normal")

        if etype in RULE_TYPES or priority == "high_priority":
            prefix = "[HIGH PRIORITY] " if priority == "high_priority" else ""
            rules.append(f"- {prefix}{result} (by {user})")
        elif etype == INTENT_TYPE:
            intents.append(f"- {result} (by {user})")
        elif _has_diff(result):
            changes.append(f"- {result} (by {user})")
        else:
            warnings.append(f"- {result} (by {user})")

    lines = [f"[OVERMIND] Team context for {scope}:"]
    lines.append("")

    if rules:
        lines.append("RULES for this scope — follow before proceeding:")
        lines.extend(rules)
        lines.append("")

    if intents:
        lines.append("PLANNED CHANGES for this scope:")
        lines.extend(intents)
        lines.append("")

    if changes:
        lines.append("TEAMMATE CHANGES for this scope (with diffs):")
        lines.extend(changes)
        lines.append("")

    if warnings:
        lines.append("Related context:")
        lines.extend(warnings)
        lines.append("")

    lines.append("Consider this context before making changes to this scope.")

    return "\n".join(lines)
