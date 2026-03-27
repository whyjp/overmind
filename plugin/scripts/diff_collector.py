"""Collect git diff snippets for pending change files."""
from __future__ import annotations
import subprocess


def collect_diff_summary(files: list[str], cwd: str | None = None, max_lines: int = 20) -> str:
    """Run git diff for given files and return compact summary of additions.
    Returns only added lines (+ prefix), truncated to max_lines.
    Returns empty string if no diff or git not available."""
    if not files:
        return ""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--unified=0", "--no-color", "--"] + files,
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
    except Exception:
        return ""
    lines = []
    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line)
        elif line.startswith("@@"):
            lines.append(line)
    if not lines:
        return ""
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... ({len(lines)} more lines truncated)")
    return "\n".join(lines)
