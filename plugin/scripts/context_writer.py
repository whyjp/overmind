"""Write pulled Overmind events to .claude/overmind-context.md."""

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


def write_context_file(events: list[dict], output_path: Path) -> None:
    """Write pulled events to context markdown file, grouped by type.

    If events is empty, does nothing (preserves existing file).
    """
    if not events:
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    # Group events by type
    groups: dict[str, list[dict]] = {}
    for evt in events:
        etype = evt.get("type", "change")
        groups.setdefault(etype, []).append(evt)

    # Build markdown
    lines = [
        "# Overmind Team Context",
        "> Auto-synced at session start. Do not edit manually.",
        f"> Last sync: {now_iso} | Events: {len(events)}",
        "",
    ]

    for etype in TYPE_ORDER:
        if etype not in groups:
            continue
        label = TYPE_LABELS.get(etype, etype.title())
        lines.append(f"## {label}")
        for evt in groups[etype]:
            lines.append(_format_event_line(evt))
        lines.append("")

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
