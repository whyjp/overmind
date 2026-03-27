# Phase 2-B Part 1: overmind-context.md Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SessionStart hook writes pulled team lessons to `.claude/overmind-context.md`, giving Claude persistent cross-session awareness of team rules and context.

**Architecture:** New `context_writer.py` module formats events into markdown by type. SessionStart hook calls it after pull. File persists across sessions; only overwritten when new events exist. CLAUDE.md gets a one-line reference (manual setup).

**Tech Stack:** Python 3.11+, pathlib, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-phase2b-context-sync-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `plugin/scripts/context_writer.py` | Format events → markdown, write to file |
| Create | `plugin/tests/test_context_writer.py` | Unit tests for formatting + file ops |
| Modify | `plugin/hooks/on_session_start.py` | Call context_writer after pull |
| Modify | `.gitignore` | Exclude `.claude/overmind-context.md` |
| Modify | `docs/setup-guide.md` | Add CLAUDE.md reference instruction |
| Modify | `server/tests/scenarios/test_hooks_e2e.py` | E2E: verify context.md created |

---

### Task 1: Create context_writer.py with tests

**Files:**
- Create: `plugin/scripts/context_writer.py`
- Create: `plugin/tests/test_context_writer.py`

- [ ] **Step 1: Write the tests**

Create `plugin/tests/test_context_writer.py`:

```python
import pytest
from pathlib import Path

# Tests run from plugin/ directory, scripts/ is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from context_writer import write_context_file


def _make_events():
    return [
        {"type": "correction", "result": "Use argon2 instead of bcrypt", "user": "dev_a",
         "ts": "2026-03-27T10:00:00Z", "scope": "src/auth/*", "summary": None},
        {"type": "decision", "result": "All API endpoints must validate input", "user": "dev_b",
         "ts": "2026-03-27T11:00:00Z", "scope": "src/api/*", "summary": "Validate all API input"},
        {"type": "discovery", "result": "Redis v3 pub/sub has memory leak", "user": "dev_a",
         "ts": "2026-03-27T12:00:00Z", "scope": "src/services/*", "summary": None},
        {"type": "change", "result": "Migrated auth to custom middleware", "user": "dev_a",
         "ts": "2026-03-27T09:00:00Z", "scope": "src/auth/*", "summary": None},
    ]


class TestWriteContextFile:
    def test_writes_grouped_by_type(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        # Check section order: corrections before decisions before discoveries before changes
        corr_pos = content.index("## Corrections")
        dec_pos = content.index("## Decisions")
        disc_pos = content.index("## Discoveries")
        chg_pos = content.index("## Changes")
        assert corr_pos < dec_pos < disc_pos < chg_pos

    def test_empty_groups_omitted(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        events = [e for e in _make_events() if e["type"] == "correction"]
        write_context_file(events, output)
        content = output.read_text(encoding="utf-8")

        assert "## Corrections" in content
        assert "## Decisions" not in content
        assert "## Discoveries" not in content
        assert "## Changes" not in content

    def test_uses_summary_over_result(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        # decision event has summary="Validate all API input"
        assert "Validate all API input" in content
        # correction event has no summary, uses result
        assert "Use argon2 instead of bcrypt" in content

    def test_scope_omitted_when_none(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        events = [{"type": "correction", "result": "No scope event", "user": "dev_a",
                    "ts": "2026-03-27T10:00:00Z", "scope": None, "summary": None}]
        write_context_file(events, output)
        content = output.read_text(encoding="utf-8")

        assert "No scope event (dev_a, 2026-03-27)" in content
        assert "scope:" not in content

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        assert not output.parent.exists()
        write_context_file(_make_events(), output)
        assert output.exists()

    def test_header_contains_metadata(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")

        assert "# Overmind Team Context" in content
        assert "Auto-synced at session start" in content
        assert "Events: 4" in content

    def test_empty_events_does_nothing(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        write_context_file([], output)
        assert not output.exists()

    def test_overwrites_existing_file(self, tmp_path):
        output = tmp_path / ".claude" / "overmind-context.md"
        output.parent.mkdir(parents=True)
        output.write_text("old content", encoding="utf-8")

        write_context_file(_make_events(), output)
        content = output.read_text(encoding="utf-8")
        assert "old content" not in content
        assert "# Overmind Team Context" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugin && python -m pytest tests/test_context_writer.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement context_writer.py**

Create `plugin/scripts/context_writer.py`:

```python
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
        f"> Auto-synced at session start. Do not edit manually.",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugin && python -m pytest tests/test_context_writer.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/context_writer.py plugin/tests/test_context_writer.py
git commit -m "feat: context_writer — format events to overmind-context.md"
```

---

### Task 2: Update SessionStart hook to write context.md

**Files:**
- Modify: `plugin/hooks/on_session_start.py`

- [ ] **Step 1: Update on_session_start.py**

Replace `plugin/hooks/on_session_start.py`:

```python
#!/usr/bin/env python3
"""SessionStart hook: pull latest events from Overmind server.

Writes team context to .claude/overmind-context.md for persistent awareness,
and outputs systemMessage for immediate visibility.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from api_client import get_repo_id, get_user, load_state, save_state, api_get
from context_writer import write_context_file
from formatter import format_session_start


CONTEXT_FILE = Path.cwd() / ".claude" / "overmind-context.md"


def main():
    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()
    last_pull = state.get("last_pull_ts")
    if not last_pull:
        last_pull = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    result = api_get("/api/memory/pull", {
        "repo_id": repo_id,
        "exclude_user": user,
        "since": last_pull,
        "limit": "20",
    })

    if not result or result.get("count", 0) == 0:
        return

    events = result["events"]

    state["last_pull_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Write persistent context file
    write_context_file(events, CONTEXT_FILE)

    # Output systemMessage for immediate visibility
    message = format_session_start(events)
    if message:
        print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run existing plugin hook tests to verify no regression**

Run: `cd plugin && python -m pytest tests/test_hooks.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/on_session_start.py
git commit -m "feat: SessionStart writes .claude/overmind-context.md"
```

---

### Task 3: Add E2E test for context.md creation

**Files:**
- Modify: `server/tests/scenarios/test_hooks_e2e.py`

- [ ] **Step 1: Add E2E test**

Add to `TestSessionStartHook` class in `server/tests/scenarios/test_hooks_e2e.py`:

```python
    def test_session_start_creates_context_file(self, server, base_url, state_dir, seed_events):
        """SessionStart should create .claude/overmind-context.md with pulled events."""
        import tempfile
        from pathlib import Path

        # Create a temp dir to act as cwd (project root)
        with tempfile.TemporaryDirectory() as project_root:
            state_file = state_dir / "state_context_test.json"
            env = make_hook_env(base_url, state_file, "dev_b", REPO_ID)
            # Set cwd to project_root so context file lands there
            env_with_cwd = {**env}

            # Run SessionStart hook from the project root
            script = Path(__file__).resolve().parents[3] / "plugin" / "hooks" / "on_session_start.py"
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=10,
                env=env_with_cwd, cwd=project_root,
            )

            # Check context file was created
            context_file = Path(project_root) / ".claude" / "overmind-context.md"
            assert context_file.exists(), f"context file not created. stdout={result.stdout}, stderr={result.stderr}"

            content = context_file.read_text(encoding="utf-8")
            assert "# Overmind Team Context" in content
            assert "argon2" in content or "auth" in content  # seed events contain auth-related content
```

- [ ] **Step 2: Run E2E test**

Run: `cd server && uv run pytest tests/scenarios/test_hooks_e2e.py::TestSessionStartHook::test_session_start_creates_context_file -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_hooks_e2e.py
git commit -m "test: E2E verify SessionStart creates overmind-context.md"
```

---

### Task 4: Update .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add context file exclusion**

Add to `.gitignore` under the `# Overmind runtime data` section:

```
# Overmind context sync (local cache, not shared via git)
.claude/overmind-context.md
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore .claude/overmind-context.md"
```

---

### Task 5: Update setup guide + CLAUDE.md

**Files:**
- Modify: `docs/setup-guide.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add team context section to setup-guide.md**

Read `docs/setup-guide.md`, then append before the last section:

```markdown
## 팀 컨텍스트 활성화 (선택)

Overmind이 세션 시작 시 동기화한 팀 규칙을 세션 전체에 걸쳐 유지하려면,
프로젝트 CLAUDE.md에 다음 한 줄을 추가하세요:

```
- 팀 동기화 규칙은 .claude/overmind-context.md를 참고하라
```

이 파일은 SessionStart 훅이 자동으로 생성/갱신합니다. 직접 편집하지 마세요.
`.gitignore`에 포함되어 있으므로 git에 커밋되지 않습니다.
```

- [ ] **Step 2: Update CLAUDE.md Phase 2-B section**

Mark context sync as done:

```markdown
**Phase 2-B: 클라이언트 레슨 반영 (수신 측 영향력)**
- ~~`.claude/overmind-context.md` 동기화: 훅이 관리하는 전용 파일, TTL 기반 만료~~ ✅
```

- [ ] **Step 3: Commit**

```bash
git add docs/setup-guide.md CLAUDE.md
git commit -m "docs: setup guide for context sync + mark Phase 2-B context as done"
```

---

### Task 6: Full regression run

- [ ] **Step 1: Run all server tests**

Run: `cd server && uv run pytest tests/ -v`
Expected: all ~70 tests PASS

- [ ] **Step 2: Run all plugin tests**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all ~67 tests PASS (59 existing + 8 new context_writer)

- [ ] **Step 3: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: regression fixes for context sync"
```
