# Push "Why" Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich PostToolUse push events with "why" context (git diff snippets + Bash error context) so receiving agents can understand the motivation behind changes, not just that files were modified.

**Architecture:** Two enrichment sources feed into `build_change_events()`: (1) git diff snippets collected at flush time, (2) Bash error context captured in PostToolUse `pending_changes`. Both are appended to the `result` field of change events. No LLM needed.

**Tech Stack:** Python 3.11+, subprocess (git diff), pytest

**Spec:** `docs/superpowers/specs/2026-03-27-post-tool-push-and-test-reinforcement-design.md` §7

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `plugin/scripts/diff_collector.py` | Run `git diff` for pending files, return summary |
| Modify | `plugin/scripts/api_client.py` | `build_change_events()` uses diff + context in result |
| Modify | `plugin/hooks/on_post_tool_use.py` | Capture Bash error context from tool_input |
| Create | `plugin/tests/test_diff_collector.py` | Unit tests for diff collection |
| Modify | `plugin/tests/test_flush_logic.py` | Updated tests for enriched result format |

---

### Task 1: Create diff_collector.py

**Files:**
- Create: `plugin/scripts/diff_collector.py`
- Create: `plugin/tests/test_diff_collector.py`

- [ ] **Step 1: Write tests**

Create `plugin/tests/test_diff_collector.py`:

```python
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diff_collector import collect_diff_summary


@pytest.fixture
def git_repo(tmp_path):
    """Create a temp git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    (repo / "config.toml").write_text("[app]\nname = 'test'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True, env=env)
    return repo


class TestCollectDiffSummary:
    def test_returns_diff_for_modified_file(self, git_repo):
        config = git_repo / "config.toml"
        config.write_text("[app]\nname = 'test'\n\n[server]\nport = 3000\n", encoding="utf-8")
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        assert "[server]" in result
        assert "port = 3000" in result

    def test_returns_empty_for_no_changes(self, git_repo):
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        assert result == ""

    def test_returns_empty_for_nonexistent_file(self, git_repo):
        result = collect_diff_summary(["nonexistent.ts"], cwd=str(git_repo))
        assert result == ""

    def test_truncates_long_diff(self, git_repo):
        config = git_repo / "config.toml"
        config.write_text("\n".join(f"line{i} = {i}" for i in range(200)), encoding="utf-8")
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo), max_lines=10)
        lines = result.strip().split("\n")
        assert len(lines) <= 12  # 10 lines + possible truncation notice

    def test_multiple_files(self, git_repo):
        (git_repo / "a.ts").write_text("new file a", encoding="utf-8")
        (git_repo / "b.ts").write_text("new file b", encoding="utf-8")
        result = collect_diff_summary(["a.ts", "b.ts"], cwd=str(git_repo))
        # Untracked files show in diff --no-index or won't appear in git diff
        # For new (untracked) files, git diff won't show them
        # This is expected — diff only works for tracked files
        assert isinstance(result, str)

    def test_only_added_lines_shown(self, git_repo):
        config = git_repo / "config.toml"
        config.write_text("[app]\nname = 'updated'\n\n[server]\nport = 3000\n", encoding="utf-8")
        result = collect_diff_summary(["config.toml"], cwd=str(git_repo))
        # Should contain + lines but not full context
        assert "+" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugin && python -m pytest tests/test_diff_collector.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement diff_collector.py**

Create `plugin/scripts/diff_collector.py`:

```python
"""Collect git diff snippets for pending change files."""

from __future__ import annotations

import subprocess


def collect_diff_summary(
    files: list[str],
    cwd: str | None = None,
    max_lines: int = 20,
) -> str:
    """Run git diff for given files and return a compact summary of changes.

    Returns only added/modified lines (+ prefix), truncated to max_lines.
    Returns empty string if no diff or git not available.
    """
    if not files:
        return ""

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--unified=0", "--no-color", "--"] + files,
            capture_output=True, text=True, timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
    except Exception:
        return ""

    # Extract only + lines (additions) excluding +++ header
    lines = []
    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line)
        elif line.startswith("@@"):
            # Include hunk headers for context
            lines.append(line)

    if not lines:
        return ""

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... ({len(lines)} more lines truncated)")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugin && python -m pytest tests/test_diff_collector.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/diff_collector.py plugin/tests/test_diff_collector.py
git commit -m "feat: diff_collector — git diff snippets for push enrichment"
```

---

### Task 2: Enrich build_change_events() with diff context

**Files:**
- Modify: `plugin/scripts/api_client.py`
- Modify: `plugin/tests/test_flush_logic.py`

- [ ] **Step 1: Write tests for enriched result**

Add to `plugin/tests/test_flush_logic.py`:

```python
class TestBuildChangeEventsEnriched:
    """build_change_events with diff and context enrichment."""

    def test_result_includes_diff_when_available(self):
        pending = [
            {"file": "config.toml", "scope": "*", "ts": "2026-03-27T10:00:00Z",
             "action": "Edit", "lesson": None, "context": None},
        ]
        # Pass diff_summary directly
        events = build_change_events(pending, diff_summary="+[server]\n+port = 3000")
        assert "+[server]" in events[0]["result"]
        assert "+port = 3000" in events[0]["result"]

    def test_result_includes_context_when_available(self):
        pending = [
            {"file": "config.toml", "scope": "*", "ts": "2026-03-27T10:00:00Z",
             "action": "Edit", "lesson": None, "context": "KeyError: 'server' section missing"},
        ]
        events = build_change_events(pending)
        assert "KeyError" in events[0]["result"]

    def test_result_includes_both_diff_and_context(self):
        pending = [
            {"file": "config.toml", "scope": "*", "ts": "2026-03-27T10:00:00Z",
             "action": "Edit", "lesson": None, "context": "KeyError: 'server'"},
        ]
        events = build_change_events(pending, diff_summary="+[server]\n+port = 3000")
        result = events[0]["result"]
        assert "KeyError" in result
        assert "+[server]" in result

    def test_result_falls_back_to_what_only(self):
        pending = [
            {"file": "config.toml", "scope": "*", "ts": "2026-03-27T10:00:00Z",
             "action": "Edit", "lesson": None, "context": None},
        ]
        events = build_change_events(pending, diff_summary="")
        assert events[0]["result"].startswith("Modified ")
        assert "+[" not in events[0]["result"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugin && python -m pytest tests/test_flush_logic.py::TestBuildChangeEventsEnriched -v`
Expected: FAIL — signature doesn't match

- [ ] **Step 3: Update build_change_events()**

In `plugin/scripts/api_client.py`, modify `build_change_events()`:

```python
def build_change_events(pending: list[dict], diff_summary: str = "") -> list[dict]:
    """Group pending changes by scope into change event dicts.

    Args:
        pending: List of pending change entries with file, scope, ts, action, context.
        diff_summary: Git diff snippet to include in result (collected at flush time).
    """
    if not pending:
        return []

    scope_files: dict[str, list[str]] = defaultdict(list)
    scope_contexts: dict[str, list[str]] = defaultdict(list)
    for entry in pending:
        scope = entry["scope"]
        f = entry["file"]
        if f not in scope_files[scope]:
            scope_files[scope].append(f)
        ctx = entry.get("context")
        if ctx and ctx not in scope_contexts[scope]:
            scope_contexts[scope].append(ctx)

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for scope, files in scope_files.items():
        basenames = [f.replace("\\", "/").rsplit("/", 1)[-1] for f in files]
        count = len(files)
        file_label = "file" if count == 1 else "files"

        # Build result: what + why
        what = f"Modified {scope} ({count} {file_label}: {', '.join(sorted(basenames))})"

        why_parts = []
        # Add error context if available
        contexts = scope_contexts.get(scope, [])
        if contexts:
            why_parts.append("Context: " + "; ".join(contexts))
        # Add diff summary if available
        if diff_summary:
            why_parts.append("Diff:\n" + diff_summary)

        if why_parts:
            result = what + "\n" + "\n".join(why_parts)
        else:
            result = what

        events.append({
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "type": "change",
            "ts": now,
            "result": result,
            "files": files,
            "scope": scope,
        })

    return events
```

- [ ] **Step 4: Run ALL flush logic tests**

Run: `cd plugin && python -m pytest tests/test_flush_logic.py -v`
Expected: all PASS (existing + new enrichment tests)

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/api_client.py plugin/tests/test_flush_logic.py
git commit -m "feat: build_change_events enriched with diff + context in result"
```

---

### Task 3: Integrate diff collection into flush_pending_changes()

**Files:**
- Modify: `plugin/scripts/api_client.py`

- [ ] **Step 1: Update flush_pending_changes() to collect diff**

In `plugin/scripts/api_client.py`, update `flush_pending_changes()`:

```python
from diff_collector import collect_diff_summary


def flush_pending_changes(state: dict, repo_id: str, user: str) -> dict:
    """Flush all pending_changes → push scope-grouped change events. Returns updated state."""
    pending = state.get("pending_changes", [])
    if not pending:
        return state

    # Collect diff for all pending files
    all_files = list({e["file"] for e in pending})
    diff_summary = collect_diff_summary(all_files)

    events = build_change_events(pending, diff_summary=diff_summary)
    if events:
        api_post("/api/memory/push", {
            "repo_id": repo_id,
            "user": user,
            "events": events,
        })

    state["pending_changes"] = []
    state["last_push_ts"] = datetime.now(timezone.utc).isoformat()
    return state
```

- [ ] **Step 2: Run plugin tests**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add plugin/scripts/api_client.py
git commit -m "feat: flush_pending_changes collects git diff at flush time"
```

---

### Task 4: Capture Bash error context in PostToolUse

**Files:**
- Modify: `plugin/hooks/on_post_tool_use.py`

- [ ] **Step 1: Update on_post_tool_use.py to capture Bash context**

The PostToolUse hook receives `tool_name` and `tool_input` from stdin. When `tool_name` is "Bash", the hook should store the command's stderr/error in the state so the next Write/Edit can reference it.

Update `plugin/hooks/on_post_tool_use.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: accumulate file changes, batch push when flush conditions met.

Also captures Bash error context for enriching subsequent change events.
"""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from datetime import datetime, timezone

from api_client import (
    file_to_scope,
    flush_pending_changes,
    get_repo_id,
    get_user,
    load_state,
    save_state,
    should_flush,
)


def _extract_bash_context(input_data: dict) -> str | None:
    """Extract error context from a Bash tool result, if present."""
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        return None
    # tool_input.command has the command, tool_result has output
    tool_result = input_data.get("tool_result", "")
    if not tool_result:
        return None
    # Only capture if it looks like an error (non-zero exit, error keywords)
    result_str = str(tool_result)
    error_indicators = ["error", "Error", "ERROR", "failed", "Failed", "FAILED",
                        "exception", "Exception", "traceback", "Traceback",
                        "KeyError", "TypeError", "ValueError", "FileNotFoundError"]
    if any(indicator in result_str for indicator in error_indicators):
        # Truncate to first 200 chars
        return result_str[:200]
    return None


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        input_data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()

    # Capture Bash error context for enriching next file change
    bash_context = _extract_bash_context(input_data)
    if bash_context:
        state["last_bash_context"] = bash_context
        save_state(state)

    # Only accumulate file changes for Write/Edit
    if not file_path:
        return

    scope = file_to_scope(file_path)
    now = datetime.now(timezone.utc).isoformat()

    # Check flush before adding new change
    if should_flush(state, scope):
        state = flush_pending_changes(state, repo_id, user)

    # Accumulate this change with context from last Bash error
    context = state.pop("last_bash_context", None)
    pending = state.get("pending_changes", [])
    pending.append({
        "file": file_path,
        "scope": scope,
        "ts": now,
        "action": tool_name or "Edit",
        "lesson": None,
        "context": context,
    })
    state["pending_changes"] = pending
    state["current_scope"] = scope

    save_state(state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run hook tests**

Run: `cd plugin && python -m pytest tests/test_hooks.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/on_post_tool_use.py
git commit -m "feat: PostToolUse captures Bash error context for push enrichment"
```

---

### Task 5: Full regression run + CLAUDE.md update

- [ ] **Step 1: Run all server tests**

Run: `cd server && uv run pytest tests/ -v`
Expected: all 70 tests PASS

- [ ] **Step 2: Run all plugin tests**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all tests PASS (existing + new diff_collector tests)

- [ ] **Step 3: Update CLAUDE.md**

Mark Push "why" enrichment as done in Phase 2-A section.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark Push why enrichment as done"
```
