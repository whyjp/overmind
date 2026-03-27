# PostToolUse Push + SessionEnd 경량화 + 테스트 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PostToolUse hook으로 세션 중 변경 사항을 자동 push하고, SessionEnd를 경량화하며, plugin/server 테스트를 보강한다.

**Architecture:** PostToolUse hook이 Write/Edit 완료 후 변경 파일을 state file에 누적하고, 개수/시간 조건 충족 시 scope별 그룹핑된 `change` 이벤트를 서버에 batch push한다. SessionEnd는 잔여분 flush만 담당한다. `file_to_scope()`와 `flush_pending_changes()`를 `api_client.py`에 공통화하여 3개 hook에서 공유한다.

**Tech Stack:** Python 3.11+ (순수 stdlib), pytest, httpx, FastAPI TestClient

**Spec:** `docs/superpowers/specs/2026-03-27-post-tool-push-and-test-reinforcement-design.md`

---

### Task 1: Plugin 테스트 인프라 셋업

**Files:**
- Create: `plugin/tests/__init__.py`
- Create: `plugin/tests/conftest.py`

- [ ] **Step 1: 디렉토리 및 파일 생성**

```python
# plugin/tests/__init__.py
# (empty)
```

```python
# plugin/tests/conftest.py
"""Shared fixtures for plugin tests."""

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_state_file(tmp_path):
    """Temporary state file for hook tests."""
    return tmp_path / "test_state.json"


@pytest.fixture
def plugin_env(tmp_state_file):
    """Environment variables for isolated hook testing."""
    return {
        **os.environ,
        "OVERMIND_URL": "http://127.0.0.1:19999",
        "OVERMIND_REPO_ID": "github.com/test/repo",
        "OVERMIND_USER": "test_user",
        "OVERMIND_STATE_FILE": str(tmp_state_file),
        "PYTHONIOENCODING": "utf-8",
    }


@pytest.fixture
def scripts_dir():
    """Path to plugin/scripts/ directory."""
    return Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def hooks_dir():
    """Path to plugin/hooks/ directory."""
    return Path(__file__).resolve().parents[1] / "hooks"
```

- [ ] **Step 2: 테스트 실행 확인**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/ -v --co`
Expected: collected 0 items (no tests yet, but no import errors)

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/__init__.py plugin/tests/conftest.py
git commit -m "chore: add plugin test infrastructure"
```

---

### Task 2: `file_to_scope` 이동 + `normalize_git_remote` 테스트 (TDD)

**Files:**
- Test: `plugin/tests/test_api_client.py`
- Modify: `plugin/scripts/api_client.py:48` (add `file_to_scope` after `normalize_git_remote`)
- Modify: `plugin/hooks/on_pre_tool_use.py:16-21` (remove local `file_to_scope`, import from api_client)

- [ ] **Step 1: Write failing tests for `normalize_git_remote`**

```python
# plugin/tests/test_api_client.py
"""Tests for plugin/scripts/api_client.py pure functions."""

import json
import sys
from pathlib import Path

import pytest

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from api_client import normalize_git_remote


class TestNormalizeGitRemote:
    def test_https_with_git_suffix(self):
        assert normalize_git_remote("https://github.com/user/repo.git") == "github.com/user/repo"

    def test_https_without_git_suffix(self):
        assert normalize_git_remote("https://github.com/user/repo") == "github.com/user/repo"

    def test_http_url(self):
        assert normalize_git_remote("http://github.com/user/repo.git") == "github.com/user/repo"

    def test_ssh_url(self):
        assert normalize_git_remote("git@github.com:user/repo.git") == "github.com/user/repo"

    def test_ssh_without_git_suffix(self):
        assert normalize_git_remote("git@github.com:user/repo") == "github.com/user/repo"

    def test_trailing_slash(self):
        assert normalize_git_remote("https://github.com/user/repo/") == "github.com/user/repo"

    def test_whitespace(self):
        assert normalize_git_remote("  https://github.com/user/repo.git  ") == "github.com/user/repo"

    def test_gitlab_ssh(self):
        assert normalize_git_remote("git@gitlab.com:org/project.git") == "gitlab.com/org/project"

    def test_nested_path(self):
        assert normalize_git_remote("https://github.com/org/sub/repo.git") == "github.com/org/sub/repo"

    def test_empty_string(self):
        assert normalize_git_remote("") == ""

    def test_plain_domain(self):
        assert normalize_git_remote("github.com/user/repo") == "github.com/user/repo"
```

- [ ] **Step 2: Run tests to verify they pass (these test existing code)**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_api_client.py -v`
Expected: 11 PASSED

- [ ] **Step 3: Write failing tests for `file_to_scope`**

Append to `plugin/tests/test_api_client.py`:

```python
from api_client import file_to_scope


class TestFileToScope:
    def test_nested_path(self):
        assert file_to_scope("src/auth/login.ts") == "src/auth/*"

    def test_deep_path(self):
        assert file_to_scope("src/components/ui/button.tsx") == "src/components/ui/*"

    def test_root_file(self):
        assert file_to_scope("README.md") == "README.md"

    def test_windows_backslash(self):
        assert file_to_scope("src\\auth\\login.ts") == "src/auth/*"

    def test_single_dir(self):
        assert file_to_scope("src/file.ts") == "src/*"
```

- [ ] **Step 4: Run tests — `file_to_scope` should FAIL (not yet in api_client)**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_api_client.py::TestFileToScope -v`
Expected: ImportError — `cannot import name 'file_to_scope' from 'api_client'`

- [ ] **Step 5: Move `file_to_scope` to `api_client.py`**

Add after `normalize_git_remote` function (after line 48) in `plugin/scripts/api_client.py`:

```python
def file_to_scope(file_path: str) -> str:
    """Convert file path to scope glob pattern. e.g. 'src/auth/login.ts' -> 'src/auth/*'."""
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    if len(parts) == 2:
        return parts[0] + "/*"
    return file_path
```

- [ ] **Step 6: Update `on_pre_tool_use.py` — remove local `file_to_scope`, import from api_client**

Replace lines 12-21 of `plugin/hooks/on_pre_tool_use.py`:

```python
from api_client import get_repo_id, get_user, api_get, file_to_scope
from formatter import format_pre_tool_use
```

Remove the local `file_to_scope` function (lines 16-21).

- [ ] **Step 7: Run all tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_api_client.py -v`
Expected: 16 PASSED

- [ ] **Step 8: Commit**

```bash
git add plugin/scripts/api_client.py plugin/hooks/on_pre_tool_use.py plugin/tests/test_api_client.py
git commit -m "refactor: move file_to_scope to api_client, add normalize_git_remote tests"
```

---

### Task 3: `load_state`/`save_state` 테스트

**Files:**
- Modify: `plugin/tests/test_api_client.py` (append tests)

- [ ] **Step 1: Write tests for `load_state`/`save_state`**

Append to `plugin/tests/test_api_client.py`:

```python
import api_client


class TestLoadSaveState:
    def test_load_empty_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        assert api_client.load_state() == {}

    def test_save_and_load(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"last_pull_ts": "2026-03-27T10:00:00Z", "pending_changes": []})
        state = api_client.load_state()
        assert state["last_pull_ts"] == "2026-03-27T10:00:00Z"
        assert state["pending_changes"] == []

    def test_overwrite_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"key": "old"})
        api_client.save_state({"key": "new"})
        state = api_client.load_state()
        assert state["key"] == "new"

    def test_preserves_unicode(self, tmp_path):
        state_file = tmp_path / "state.json"
        api_client.STATE_FILE = state_file
        api_client.save_state({"result": "한글 테스트"})
        state = api_client.load_state()
        assert state["result"] == "한글 테스트"
```

- [ ] **Step 2: Run tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_api_client.py::TestLoadSaveState -v`
Expected: 4 PASSED

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_api_client.py
git commit -m "test: add load_state/save_state unit tests"
```

---

### Task 4: `flush_pending_changes` 구현 (TDD)

**Files:**
- Create: `plugin/tests/test_flush_logic.py`
- Modify: `plugin/scripts/api_client.py` (add `flush_pending_changes`, `build_change_events`)

- [ ] **Step 1: Write failing tests for flush logic**

```python
# plugin/tests/test_flush_logic.py
"""Tests for flush_pending_changes logic in api_client."""

import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from api_client import build_change_events


class TestBuildChangeEvents:
    """build_change_events groups pending_changes by scope into event dicts."""

    def test_single_scope(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/oauth2.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:05:00Z", "action": "Write"},
        ]
        events = build_change_events(pending)
        assert len(events) == 1
        evt = events[0]
        assert evt["type"] == "change"
        assert evt["scope"] == "src/auth/*"
        assert set(evt["files"]) == {"src/auth/login.ts", "src/auth/oauth2.ts"}
        assert "2 files" in evt["result"]
        assert evt["id"].startswith("auto_")

    def test_multiple_scopes(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/cache/redis.ts", "scope": "src/cache/*", "ts": "2026-03-27T10:05:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert len(events) == 2
        scopes = {e["scope"] for e in events}
        assert scopes == {"src/auth/*", "src/cache/*"}

    def test_empty_pending(self):
        events = build_change_events([])
        assert events == []

    def test_deduplicates_files(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:10:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert len(events) == 1
        assert len(events[0]["files"]) == 1
        assert "1 file" in events[0]["result"]

    def test_result_format_single_file(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
        ]
        events = build_change_events(pending)
        assert events[0]["result"] == "Modified src/auth/* (1 file: login.ts)"

    def test_result_format_multiple_files(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit"},
            {"file": "src/auth/oauth2.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:01:00Z", "action": "Edit"},
            {"file": "src/auth/jwt.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:02:00Z", "action": "Write"},
        ]
        events = build_change_events(pending)
        assert "3 files" in events[0]["result"]

    def test_lesson_field_preserved(self):
        pending = [
            {"file": "src/auth/login.ts", "scope": "src/auth/*", "ts": "2026-03-27T10:00:00Z", "action": "Edit", "lesson": None},
        ]
        events = build_change_events(pending)
        assert events[0]["type"] == "change"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_flush_logic.py -v`
Expected: ImportError — `cannot import name 'build_change_events' from 'api_client'`

- [ ] **Step 3: Implement `build_change_events` in `api_client.py`**

First, add missing imports to the top of `plugin/scripts/api_client.py` (after existing imports):

```python
import uuid
from collections import defaultdict
from datetime import datetime, timezone
```

Then add at the end of `plugin/scripts/api_client.py`:

```python
# ------------------------------------------------------------------
# Flush logic: accumulate pending changes → scope-grouped events
# ------------------------------------------------------------------

FLUSH_THRESHOLD = int(os.environ.get("OVERMIND_FLUSH_THRESHOLD", "5"))
FLUSH_INTERVAL = int(os.environ.get("OVERMIND_FLUSH_INTERVAL", "1800"))


def build_change_events(pending: list[dict]) -> list[dict]:
    """Group pending changes by scope into change event dicts."""
    if not pending:
        return []

    scope_files: dict[str, list[str]] = defaultdict(list)
    for entry in pending:
        scope = entry["scope"]
        f = entry["file"]
        if f not in scope_files[scope]:
            scope_files[scope].append(f)

    now = datetime.now(timezone.utc).isoformat()
    events = []
    for scope, files in scope_files.items():
        basenames = [f.replace("\\", "/").rsplit("/", 1)[-1] for f in files]
        count = len(files)
        file_label = "file" if count == 1 else "files"
        result = f"Modified {scope} ({count} {file_label}: {', '.join(sorted(basenames))})"
        events.append({
            "id": f"auto_{uuid.uuid4().hex[:12]}",
            "type": "change",
            "ts": now,
            "result": result,
            "files": files,
            "scope": scope,
        })

    return events


def flush_pending_changes(state: dict, repo_id: str, user: str) -> dict:
    """Flush all pending_changes → push scope-grouped change events. Returns updated state."""
    pending = state.get("pending_changes", [])
    if not pending:
        return state

    events = build_change_events(pending)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_flush_logic.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/api_client.py plugin/tests/test_flush_logic.py
git commit -m "feat: add build_change_events and flush_pending_changes"
```

---

### Task 5: `test_flush_logic.py` — flush 트리거 조건 테스트

**Files:**
- Modify: `plugin/tests/test_flush_logic.py` (append tests)

- [ ] **Step 1: Write tests for should_flush conditions**

Append to `plugin/tests/test_flush_logic.py`:

```python
from api_client import should_flush


class TestShouldFlush:
    """should_flush(state, new_scope) checks count/time/scope-change triggers."""

    def test_empty_pending_no_flush(self):
        state = {"pending_changes": [], "last_push_ts": "2026-03-27T10:00:00Z"}
        assert should_flush(state, "src/auth/*") is False

    def test_threshold_reached(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}] * 5,
            "last_push_ts": "2026-03-27T10:00:00Z",
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is True

    def test_below_threshold(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}] * 3,
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is False

    def test_time_exceeded(self):
        old_ts = "2026-03-27T08:00:00+00:00"  # 2+ hours ago
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "last_push_ts": old_ts,
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/auth/*") is True

    def test_scope_change(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/cache/*") is True

    def test_no_last_push_ts_uses_time_trigger(self):
        state = {
            "pending_changes": [{"scope": "src/auth/*"}],
            "current_scope": "src/auth/*",
        }
        # No last_push_ts → should flush (treat as stale)
        assert should_flush(state, "src/auth/*") is True

    def test_scope_change_with_no_pending_no_flush(self):
        state = {
            "pending_changes": [],
            "last_push_ts": datetime.now(timezone.utc).isoformat(),
            "current_scope": "src/auth/*",
        }
        assert should_flush(state, "src/cache/*") is False
```

- [ ] **Step 2: Run tests — should FAIL**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_flush_logic.py::TestShouldFlush -v`
Expected: ImportError — `cannot import name 'should_flush' from 'api_client'`

- [ ] **Step 3: Implement `should_flush` in `api_client.py`**

Add before `build_change_events` in `plugin/scripts/api_client.py`:

```python
def should_flush(state: dict, new_scope: str) -> bool:
    """Check if pending_changes should be flushed based on count/time/scope-change."""
    pending = state.get("pending_changes", [])
    if not pending:
        return False

    # Count trigger
    if len(pending) >= FLUSH_THRESHOLD:
        return True

    # Time trigger
    last_push = state.get("last_push_ts")
    if not last_push:
        return True  # never pushed → flush
    try:
        last_dt = datetime.fromisoformat(last_push)
        now = datetime.now(timezone.utc)
        if (now - last_dt).total_seconds() >= FLUSH_INTERVAL:
            return True
    except (ValueError, TypeError):
        return True

    # Scope change trigger
    current_scope = state.get("current_scope")
    if current_scope and current_scope != new_scope:
        return True

    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_flush_logic.py -v`
Expected: 15 PASSED

- [ ] **Step 5: Commit**

```bash
git add plugin/scripts/api_client.py plugin/tests/test_flush_logic.py
git commit -m "feat: add should_flush trigger logic with count/time/scope conditions"
```

---

### Task 6: PostToolUse Hook 구현

**Files:**
- Create: `plugin/hooks/on_post_tool_use.py`

- [ ] **Step 1: Create the PostToolUse hook**

```python
#!/usr/bin/env python3
"""PostToolUse hook: accumulate file changes, batch push when flush conditions met."""

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


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    scope = file_to_scope(file_path)
    now = datetime.now(timezone.utc).isoformat()

    state = load_state()

    # Check flush before adding new change
    if should_flush(state, scope):
        state = flush_pending_changes(state, repo_id, user)

    # Accumulate this change
    pending = state.get("pending_changes", [])
    pending.append({
        "file": file_path,
        "scope": scope,
        "ts": now,
        "action": input_data.get("tool_name", "Edit"),
        "lesson": None,
    })
    state["pending_changes"] = pending
    state["current_scope"] = scope

    save_state(state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:/github/overmind/plugin && python -c "import py_compile; py_compile.compile('hooks/on_post_tool_use.py', doraise=True)"`
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/on_post_tool_use.py
git commit -m "feat: add PostToolUse hook — accumulate changes, batch push on flush"
```

---

### Task 7: SessionEnd 경량화

**Files:**
- Modify: `plugin/hooks/on_session_end.py` (rewrite)

- [ ] **Step 1: Rewrite `on_session_end.py`**

Replace entire content of `plugin/hooks/on_session_end.py`:

```python
#!/usr/bin/env python3
"""SessionEnd hook: flush any remaining pending changes to Overmind server."""

import json
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'scripts'))
from api_client import flush_pending_changes, get_repo_id, get_user, load_state, save_state


def main():
    input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}

    repo_id = get_repo_id()
    if not repo_id:
        return

    user = get_user()
    state = load_state()

    # Flush remaining pending changes
    if state.get("pending_changes"):
        state = flush_pending_changes(state, repo_id, user)

    # Clear session tracking state
    state.pop("current_scope", None)
    save_state(state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:/github/overmind/plugin && python -c "import py_compile; py_compile.compile('hooks/on_session_end.py', doraise=True)"`
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/on_session_end.py
git commit -m "refactor: SessionEnd hook — flush remaining pending changes only"
```

---

### Task 8: hooks.json에 PostToolUse 등록

**Files:**
- Modify: `plugin/hooks/hooks.json`

- [ ] **Step 1: Add PostToolUse entry to hooks.json**

Replace the entire `plugin/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_session_start.py\"",
            "timeout": 5000
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_session_end.py\"",
            "timeout": 5000
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "matcher": "^(Write|Edit)$",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_pre_tool_use.py\"",
            "timeout": 3000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "matcher": "^(Write|Edit)$",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_post_tool_use.py\"",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Validate JSON**

Run: `cd D:/github/overmind/plugin && python -c "import json; json.load(open('hooks/hooks.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/hooks.json
git commit -m "feat: register PostToolUse hook in hooks.json"
```

---

### Task 9: Formatter 테스트

**Files:**
- Create: `plugin/tests/test_formatter.py`

- [ ] **Step 1: Write formatter tests**

```python
# plugin/tests/test_formatter.py
"""Tests for plugin/scripts/formatter.py output formatting."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from formatter import format_session_start, format_pre_tool_use


class TestFormatSessionStart:
    def test_empty_events_returns_none(self):
        assert format_session_start([]) is None

    def test_correction_in_rules_section(self):
        events = [{
            "type": "correction",
            "user": "dev_a",
            "result": "bcrypt to argon2",
            "priority": "normal",
            "process": ["perf issue found"],
        }]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "bcrypt to argon2" in msg
        assert "dev_a" in msg
        assert "Reason: perf issue found" in msg

    def test_decision_in_rules_section(self):
        events = [{"type": "decision", "user": "dev_b", "result": "use Redis", "priority": "normal", "process": []}]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "use Redis" in msg

    def test_discovery_in_context_section(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "found endpoint", "priority": "normal"}]
        msg = format_session_start(events)
        assert "CONTEXT" in msg
        assert "found endpoint" in msg

    def test_broadcast_in_announcements_section(self):
        events = [{"type": "broadcast", "user": "master", "result": "deploy freeze", "priority": "normal"}]
        msg = format_session_start(events)
        assert "ANNOUNCEMENTS" in msg
        assert "deploy freeze" in msg

    def test_urgent_prefix(self):
        events = [{"type": "correction", "user": "dev_a", "result": "fix it", "priority": "urgent", "process": []}]
        msg = format_session_start(events)
        assert "[URGENT]" in msg

    def test_mixed_events(self):
        events = [
            {"type": "correction", "user": "dev_a", "result": "rule1", "priority": "normal", "process": []},
            {"type": "discovery", "user": "dev_b", "result": "context1", "priority": "normal"},
            {"type": "broadcast", "user": "master", "result": "announce1", "priority": "normal"},
        ]
        msg = format_session_start(events)
        assert "RULES" in msg
        assert "CONTEXT" in msg
        assert "ANNOUNCEMENTS" in msg

    def test_header_present(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "something", "priority": "normal"}]
        msg = format_session_start(events)
        assert "[OVERMIND]" in msg

    def test_footer_present(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "something", "priority": "normal"}]
        msg = format_session_start(events)
        assert "Follow RULES strictly" in msg


class TestFormatPreToolUse:
    def test_empty_events_returns_none(self):
        assert format_pre_tool_use([], "src/auth/*") is None

    def test_correction_in_rules(self):
        events = [{"type": "correction", "user": "dev_a", "result": "don't modify", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/auth/*")
        assert "RULES for this scope" in msg
        assert "don't modify" in msg

    def test_urgent_in_rules(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "urgent thing", "priority": "urgent"}]
        msg = format_pre_tool_use(events, "src/api/*")
        assert "[URGENT]" in msg
        assert "RULES for this scope" in msg

    def test_normal_discovery_in_context(self):
        events = [{"type": "discovery", "user": "dev_a", "result": "found issue", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/cache/*")
        assert "Related context" in msg
        assert "found issue" in msg

    def test_scope_in_header(self):
        events = [{"type": "change", "user": "dev_a", "result": "changed file", "priority": "normal"}]
        msg = format_pre_tool_use(events, "src/auth/*")
        assert "src/auth/*" in msg
```

- [ ] **Step 2: Run tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_formatter.py -v`
Expected: 14 PASSED

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_formatter.py
git commit -m "test: add formatter unit tests for session_start and pre_tool_use"
```

---

### Task 10: Hook 통합 테스트 (subprocess)

**Files:**
- Create: `plugin/tests/test_hooks.py`

이 테스트는 각 hook을 subprocess로 실행하여 stdin→stdout 동작을 검증한다. 서버가 없는 상태에서 테스트하므로 서버 연결 실패 시에도 hook이 정상 종료하는 것을 확인한다. 서버가 있는 E2E 테스트는 `server/tests/scenarios/test_hooks_e2e.py`에 이미 존재한다.

- [ ] **Step 1: Write hook subprocess tests**

```python
# plugin/tests/test_hooks.py
"""Integration tests: run hook scripts as subprocesses with env overrides.

These tests verify hook scripts handle stdin/stdout correctly.
Server is NOT running — hooks should gracefully handle connection failures.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"
PLUGIN_DIR = Path(__file__).resolve().parents[1]


def run_hook(script_name: str, env: dict, stdin_data: str = "") -> subprocess.CompletedProcess:
    """Run a hook script as subprocess."""
    script = HOOKS_DIR / script_name
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(PLUGIN_DIR),
    )


class TestPostToolUseHook:
    """on_post_tool_use.py: accumulates changes in state file."""

    def test_accumulates_change_in_state(self, plugin_env, tmp_state_file):
        """PostToolUse writes pending_changes to state file."""
        stdin_data = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth/login.ts"},
        })
        result = run_hook("on_post_tool_use.py", plugin_env, stdin_data)
        assert result.returncode == 0

        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert len(state.get("pending_changes", [])) == 1
        assert state["pending_changes"][0]["file"] == "src/auth/login.ts"
        assert state["pending_changes"][0]["scope"] == "src/auth/*"
        assert state["current_scope"] == "src/auth/*"

    def test_multiple_accumulations(self, plugin_env, tmp_state_file):
        """Multiple PostToolUse calls accumulate in state."""
        for f in ["src/auth/login.ts", "src/auth/oauth2.ts", "src/auth/jwt.ts"]:
            stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": f}})
            run_hook("on_post_tool_use.py", plugin_env, stdin_data)

        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert len(state["pending_changes"]) == 3

    def test_no_file_path_no_state_change(self, plugin_env, tmp_state_file):
        """No file_path in input → no state change."""
        stdin_data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        run_hook("on_post_tool_use.py", plugin_env, stdin_data)
        assert not tmp_state_file.exists()

    def test_empty_stdin_no_crash(self, plugin_env, tmp_state_file):
        """Empty stdin → graceful exit."""
        result = run_hook("on_post_tool_use.py", plugin_env, "")
        assert result.returncode == 0

    def test_no_repo_id_no_crash(self, plugin_env, tmp_state_file):
        """Missing OVERMIND_REPO_ID → graceful exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/foo.ts"}})
        result = run_hook("on_post_tool_use.py", env, stdin_data)
        assert result.returncode == 0


class TestSessionEndHook:
    """on_session_end.py: flushes remaining pending changes."""

    def test_no_pending_no_push(self, plugin_env, tmp_state_file):
        """No pending changes → no push attempt, clean exit."""
        tmp_state_file.write_text(json.dumps({"last_pull_ts": "2026-03-27T10:00:00Z"}))
        result = run_hook("on_session_end.py", plugin_env, "{}")
        assert result.returncode == 0

    def test_clears_current_scope(self, plugin_env, tmp_state_file):
        """SessionEnd clears current_scope from state."""
        tmp_state_file.write_text(json.dumps({
            "current_scope": "src/auth/*",
            "pending_changes": [],
        }))
        result = run_hook("on_session_end.py", plugin_env, "{}")
        assert result.returncode == 0
        state = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert "current_scope" not in state

    def test_no_repo_id_no_crash(self, plugin_env, tmp_state_file):
        """Missing repo_id → graceful exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        result = run_hook("on_session_end.py", env, "{}")
        assert result.returncode == 0


class TestPreToolUseHook:
    """on_pre_tool_use.py: basic subprocess behavior (no server)."""

    def test_no_file_path_no_output(self, plugin_env):
        """No file_path → no output, clean exit."""
        stdin_data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        result = run_hook("on_pre_tool_use.py", plugin_env, stdin_data)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_no_repo_id_no_output(self, plugin_env):
        """Missing repo_id → no output, clean exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        stdin_data = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/foo.ts"}})
        result = run_hook("on_pre_tool_use.py", env, stdin_data)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestSessionStartHook:
    """on_session_start.py: basic subprocess behavior (no server)."""

    def test_no_repo_id_no_output(self, plugin_env):
        """Missing repo_id → no output, clean exit."""
        env = {**plugin_env}
        del env["OVERMIND_REPO_ID"]
        result = run_hook("on_session_start.py", env, "")
        assert result.returncode == 0
        assert result.stdout.strip() == ""
```

- [ ] **Step 2: Run tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/test_hooks.py -v`
Expected: 12 PASSED

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_hooks.py
git commit -m "test: add hook subprocess integration tests"
```

---

### Task 11: 서버 concurrent push stress test

**Files:**
- Modify: `server/tests/test_api.py` (append test class)

- [ ] **Step 1: Write concurrent push stress test**

Append to `server/tests/test_api.py`:

```python
import asyncio


@pytest.mark.asyncio
class TestConcurrentPush:
    async def test_concurrent_push_no_data_loss(self, client):
        """Multiple agents pushing concurrently should not lose events."""
        async def push_batch(user: str, start: int, count: int):
            for i in range(count):
                await client.post("/api/memory/push", json={
                    "repo_id": "github.com/stress/test",
                    "user": user,
                    "events": [{
                        "id": f"stress_{user}_{start + i}",
                        "type": "change",
                        "ts": "2026-03-27T10:00:00Z",
                        "result": f"change {i} by {user}",
                        "files": [f"src/{user}/file_{i}.ts"],
                    }],
                })

        # 5 agents push 10 events each concurrently
        await asyncio.gather(
            push_batch("agent_a", 0, 10),
            push_batch("agent_b", 100, 10),
            push_batch("agent_c", 200, 10),
            push_batch("agent_d", 300, 10),
            push_batch("agent_e", 400, 10),
        )

        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/stress/test",
            "limit": 100,
        })
        body = resp.json()
        assert body["count"] == 50

        # Verify all agents present
        users = {e["user"] for e in body["events"]}
        assert users == {"agent_a", "agent_b", "agent_c", "agent_d", "agent_e"}

    async def test_concurrent_push_dedup(self, client):
        """Same event ID pushed concurrently should be deduped."""
        async def push_same(user: str):
            await client.post("/api/memory/push", json={
                "repo_id": "github.com/stress/dedup",
                "user": user,
                "events": [{
                    "id": "shared_event_001",
                    "type": "correction",
                    "ts": "2026-03-27T10:00:00Z",
                    "result": "shared fix",
                }],
            })

        await asyncio.gather(
            push_same("agent_a"),
            push_same("agent_b"),
            push_same("agent_c"),
        )

        resp = await client.get("/api/memory/pull", params={
            "repo_id": "github.com/stress/dedup",
        })
        body = resp.json()
        # Only 1 event should exist (dedup by id)
        assert body["count"] == 1
```

- [ ] **Step 2: Run tests**

Run: `cd D:/github/overmind/server && uv run pytest tests/test_api.py::TestConcurrentPush -v`
Expected: 2 PASSED

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_api.py
git commit -m "test: add concurrent push stress tests"
```

---

### Task 12: 서버 E2E subprocess test

**Files:**
- Create: `server/tests/scenarios/test_e2e_server.py`

- [ ] **Step 1: Write E2E server test**

```python
# server/tests/scenarios/test_e2e_server.py
"""E2E test: start server as subprocess, run real HTTP requests.

Unlike test_hooks_e2e.py (thread-based), this test uses subprocess for full isolation.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

PORT = 18888
BASE_URL = f"http://127.0.0.1:{PORT}"


def _api_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _api_get(path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _wait_for_server(timeout: float = 10.0) -> bool:
    """Poll until server responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{BASE_URL}/api/repos", method="GET")
            with urlopen(req, timeout=2):
                return True
        except (URLError, OSError):
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server_process(tmp_path_factory):
    """Start overmind server as a subprocess."""
    data_dir = tmp_path_factory.mktemp("e2e_subprocess_data")
    server_dir = Path(__file__).resolve().parents[2]

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "overmind.main:create_standalone_app",
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--log-level", "error",
            "--factory",
        ],
        cwd=str(server_dir),
        env={**__import__("os").environ, "OVERMIND_DATA_DIR": str(data_dir)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if not _wait_for_server():
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(f"Server failed to start. stderr: {stderr.decode()}")

    yield proc

    proc.terminate()
    proc.wait(timeout=5)


class TestE2ESubprocess:
    def test_push_and_pull(self, server_process):
        """Push events and pull them back via real HTTP."""
        result = _api_post("/api/memory/push", {
            "repo_id": "github.com/e2e/subprocess",
            "user": "dev_a",
            "events": [{
                "id": "e2e_sub_001",
                "type": "correction",
                "ts": "2026-03-27T10:00:00Z",
                "result": "subprocess test correction",
                "files": ["src/test/file.ts"],
            }],
        })
        assert result["accepted"] == 1

        pull = _api_get("/api/memory/pull", {
            "repo_id": "github.com/e2e/subprocess",
            "exclude_user": "dev_b",
        })
        assert pull["count"] == 1
        assert pull["events"][0]["result"] == "subprocess test correction"

    def test_broadcast_and_pull(self, server_process):
        """Broadcast and verify it appears in pull."""
        result = _api_post("/api/memory/broadcast", {
            "repo_id": "github.com/e2e/subprocess",
            "user": "master",
            "message": "subprocess broadcast test",
            "priority": "urgent",
        })
        assert result["delivered"] is True

        pull = _api_get("/api/memory/pull", {
            "repo_id": "github.com/e2e/subprocess",
            "exclude_user": "dev_b",
        })
        # Urgent broadcast should be first
        assert pull["events"][0]["type"] == "broadcast"
        assert pull["events"][0]["priority"] == "urgent"

    def test_report(self, server_process):
        """Report endpoint returns correct stats."""
        report = _api_get("/api/report", {
            "repo_id": "github.com/e2e/subprocess",
        })
        assert report["total_pushes"] >= 2
        assert report["unique_users"] >= 2

    def test_repos_list(self, server_process):
        """Repos endpoint lists known repos."""
        repos = _api_get("/api/repos")
        assert "github.com/e2e/subprocess" in repos
```

- [ ] **Step 2: Add `create_standalone_app` factory to `main.py`**

This test needs a factory function that uvicorn can call with `--factory`. Add before `def main()` in `server/overmind/main.py` (line 15):

```python
def create_standalone_app():
    """Factory for uvicorn --factory. Reads OVERMIND_DATA_DIR env var."""
    import os
    data_dir = Path(os.environ.get("OVERMIND_DATA_DIR", "data"))
    store = MemoryStore(data_dir=data_dir)
    return create_app(data_dir=data_dir, store=store)
```

Note: `create_app`, `MemoryStore`, and `Path` are already imported in `main.py`.

- [ ] **Step 3: Run tests**

Run: `cd D:/github/overmind/server && uv run pytest tests/scenarios/test_e2e_server.py -v`
Expected: 4 PASSED

- [ ] **Step 4: Commit**

```bash
git add server/tests/scenarios/test_e2e_server.py server/overmind/main.py
git commit -m "test: add E2E subprocess server test + create_standalone_app factory"
```

---

### Task 13: 전체 테스트 실행 및 확인

**Files:** (none — verification only)

- [ ] **Step 1: Run all plugin tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/ -v`
Expected: ~40+ tests PASSED

- [ ] **Step 2: Run all server tests**

Run: `cd D:/github/overmind/server && uv run pytest tests/ -v`
Expected: ~40+ tests PASSED (기존 33 + concurrent 2 + e2e 4)

- [ ] **Step 3: Update CLAUDE.md test count**

Update the test counts in `CLAUDE.md` to reflect the new totals.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with new test counts and PostToolUse hook"
```
