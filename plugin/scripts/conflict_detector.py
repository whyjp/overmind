"""Detect conflicts between pulled lessons and current tool use.

Compares structured lessons (action/target/reason) against the tool
input to decide whether to deny, warn, or ignore.
"""

from __future__ import annotations

from typing import Literal

Verdict = Literal["deny", "warn", "ignore"]


def detect_conflict(
    tool_name: str,
    tool_input: dict,
    events: list[dict],
) -> tuple[Verdict, list[dict]]:
    """Check events for conflicts with the current tool use.

    Returns (verdict, matching_events) where verdict is the highest
    severity among all matches: deny > warn > ignore.
    """
    deny_events: list[dict] = []
    warn_events: list[dict] = []

    file_path = tool_input.get("file_path", "")

    for evt in events:
        lesson = evt.get("lesson")
        if lesson:
            verdict = _check_structured(lesson, tool_name, tool_input, evt)
        else:
            verdict = _check_legacy(evt, file_path)

        if verdict == "deny":
            deny_events.append(evt)
        elif verdict == "warn":
            warn_events.append(evt)

    if deny_events:
        return "deny", deny_events
    if warn_events:
        return "warn", warn_events
    return "ignore", []


def _check_structured(
    lesson: dict, tool_name: str, tool_input: dict, evt: dict,
) -> Verdict:
    """Evaluate a structured lesson against tool input."""
    action = lesson.get("action", "")
    target = lesson.get("target", "")
    replacement = lesson.get("replacement")

    if not target:
        return "ignore"

    target_lower = target.lower()

    # Collect searchable text from tool input
    file_path = tool_input.get("file_path", "").lower()
    new_content = _get_content(tool_input, tool_name).lower()

    if action == "prohibit":
        # File/scope match → deny
        if _matches_path(target_lower, file_path):
            return "deny"
        # Content match (e.g. "prohibit: delete ButtonA")
        if target_lower in new_content:
            return "deny"

    elif action == "replace":
        # Agent is using the OLD thing (target) instead of replacement
        if target_lower in new_content:
            return "warn"

    elif action == "avoid":
        if target_lower in new_content:
            return "warn"

    elif action == "require":
        # Only warn if editing a file within the event's scope/files
        if file_path and _event_relevant_to_file(evt, file_path):
            if target_lower not in new_content:
                return "warn"

    # "prefer" is advisory — handled by systemMessage, not conflict detection
    return "ignore"


def _event_relevant_to_file(evt: dict, file_path: str) -> bool:
    """Check if event's scope or files overlap with the given file path."""
    file_lower = file_path.lower().replace("\\", "/")

    # Check event's files list
    for f in evt.get("files", []):
        f_lower = f.lower().replace("\\", "/")
        f_dir = f_lower.rsplit("/", 1)[0] if "/" in f_lower else ""
        if f_lower == file_lower or (f_dir and file_lower.startswith(f_dir + "/")):
            return True

    # Check event's scope
    scope = evt.get("scope", "")
    if scope:
        scope_lower = scope.lower().replace("\\", "/")
        if scope_lower.endswith("/*"):
            prefix = scope_lower[:-2]
            if file_lower.startswith(prefix + "/") or file_lower.startswith(prefix):
                return True
        elif scope_lower in file_lower:
            return True

    # No scope/files info → not relevant (require shouldn't apply globally)
    return False


def _check_legacy(evt: dict, file_path: str) -> Verdict:
    """Fallback for events without structured lesson.

    Only triggers deny when the event's files/scope overlap with the
    current file being edited.
    """
    if (
        evt.get("priority") == "high_priority"
        and evt.get("type") in ("correction", "decision")
    ):
        # Check if event is relevant to this file
        if _legacy_scope_matches(evt, file_path):
            return "deny"
    return "ignore"


def _legacy_scope_matches(evt: dict, file_path: str) -> bool:
    """Check if a legacy event (no lesson) is relevant to the file path."""
    if not file_path:
        return False
    file_lower = file_path.lower().replace("\\", "/")

    # Check event's files list
    evt_files = evt.get("files", [])
    for f in evt_files:
        f_lower = f.lower().replace("\\", "/")
        # Same directory or file substring match
        if f_lower in file_lower or file_lower.startswith(f_lower.rsplit("/", 1)[0]):
            return True

    # Check event's scope
    evt_scope = evt.get("scope", "")
    if evt_scope:
        scope_lower = evt_scope.lower().replace("\\", "/")
        if scope_lower.endswith("/*"):
            prefix = scope_lower[:-2]
            if file_lower.startswith(prefix):
                return True
        elif scope_lower in file_lower:
            return True

    # No file/scope info → conservatively match (shouldn't block without context)
    if not evt_files and not evt_scope:
        return True

    return False


def _get_content(tool_input: dict, tool_name: str) -> str:
    """Extract the content being written/edited from tool input."""
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name == "Bash":
        return tool_input.get("command", "")
    return ""


def _matches_path(target: str, file_path: str) -> bool:
    """Check if target matches file path (glob-like or substring)."""
    if not file_path:
        return False
    # Normalize separators
    file_path = file_path.replace("\\", "/")
    target = target.replace("\\", "/")

    # Glob-style: target ends with /*
    if target.endswith("/*"):
        prefix = target[:-2]
        return file_path.startswith(prefix) or f"/{prefix}" in file_path

    # Substring match
    return target in file_path
