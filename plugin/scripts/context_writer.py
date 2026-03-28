"""Write pulled Overmind events to .claude/overmind-context.md.

This file persists through the session and is referenced like CLAUDE.md.
Diffs from teammate changes are presented as structured information so
the agent can naturally use them when encountering related issues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# Type group display order (importance descending)
TYPE_ORDER = ["correction", "decision", "discovery", "change", "broadcast"]
TYPE_LABELS = {
    "correction": "Corrections",
    "decision": "Decisions",
    "discovery": "Discoveries",
    "change": "Changes",
    "broadcast": "Broadcasts",
}


def _has_diff(text: str) -> bool:
    """Check if text contains a diff snippet."""
    return "\nDiff:" in text or text.startswith("Diff:")


def _format_event_line(evt: dict) -> str:
    """Format a single event as a markdown list item."""
    text = evt.get("summary") or evt.get("result", "")
    user = evt.get("user", "unknown")
    ts = evt.get("ts", "")
    date = ts[:10] if ts else ""

    scope = evt.get("scope")
    if scope:
        return f"- {text} ({user}, {date}, scope: {scope})"
    return f"- {text} ({user}, {date})"


def _extract_diff_block(result: str) -> str | None:
    """Extract the diff portion from a result string."""
    idx = result.find("\nDiff:")
    if idx == -1:
        if result.startswith("Diff:"):
            return result[5:].strip()
        return None
    return result[idx + 6:].strip()


def write_context_file(events: list[dict], output_path: Path) -> None:
    """Write pulled events to context markdown file, grouped by type.

    If events is empty, does nothing (preserves existing file).
    Diff-containing events get a dedicated section with the actual diffs
    so the agent can reference them when fixing similar issues.
    """
    if not events:
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    # Separate events with diffs from regular events
    diff_events = []
    regular_groups: dict[str, list[dict]] = {}

    for evt in events:
        etype = evt.get("type", "change")
        result = evt.get("result", "")
        if _has_diff(result):
            diff_events.append(evt)
        else:
            regular_groups.setdefault(etype, []).append(evt)

    # Build markdown
    lines = [
        "# Overmind Team Context",
        "> Auto-synced at session start. Do not edit manually.",
        f"> Last sync: {now_iso} | Events: {len(events)}",
        "",
    ]

    # Diff section first — most actionable information
    if diff_events:
        lines.append("## Teammate Changes (with diffs)")
        lines.append("")
        for evt in diff_events:
            user = evt.get("user", "unknown")
            result = evt.get("result", "")
            # Extract description (before diff) and diff (after)
            diff_idx = result.find("\nDiff:")
            if diff_idx >= 0:
                desc = result[:diff_idx].strip()
                diff = result[diff_idx + 6:].strip()
            else:
                desc = result
                diff = ""
            lines.append(f"**{desc}** ({user})")
            if diff:
                lines.append("```diff")
                lines.append(diff)
                lines.append("```")
            lines.append("")

    # Regular events grouped by type
    for etype in TYPE_ORDER:
        if etype not in regular_groups:
            continue
        label = TYPE_LABELS.get(etype, etype.title())
        lines.append(f"## {label}")
        for evt in regular_groups[etype]:
            lines.append(_format_event_line(evt))
        lines.append("")

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
