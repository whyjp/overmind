# Branch-Conflict Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서로 다른 feature branch에서 작업하는 에이전트가 Overmind의 cross-branch intent/discovery 공유로 충돌을 회피하는지 E2E 검증하는 branch-conflict scaffold 구현.

**Architecture:** nightmare scaffold 패턴을 따름. `branch_conflict.py`가 scaffold 파일 + `create_scaffold(branch)` + `check_config()` 제공. 테스트는 기존 statistical AB framework에 branch-aware 전용 함수 추가. Pioneer(feat/auth)가 먼저 해결 → push → Student(feat/api)가 cross-branch intent 수신 → Naive(feat/api)는 수신 없음.

**Tech Stack:** Python, pytest, git subprocess, 기존 ab_runner.py + server_helpers.py

**Spec:** `docs/superpowers/specs/2026-03-29-branch-conflict-scaffold-design.md`

---

### Task 1: branch_conflict.py — Scaffold 파일 구조

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/branch_conflict.py`

- [ ] **Step 1: branch_conflict.py 생성 — 상수 + SCAFFOLD_FILES**

```python
"""Branch-Conflict Scaffold: cross-branch shared resource conflict.

Scenario:
  Two feature branches (feat/auth, feat/api) add modules to the same server.
  Both need ports, .env variables, and session config that can conflict.

  TRAP 1: Port conflict — both modules hint at port 8080
  TRAP 2: SERVICE_TOKEN format conflict — auth needs HS256, api needs UUID
  TRAP 3: Session timeout mutual exclusion — auth >= 3600, api <= 1800
"""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-branch-conflict"
REPO_ID = "github.com/test/hive-branch-conflict"
MAX_TURNS = 30

SHARED_PROMPT = (
    "Get this branch's module working. "
    "Run `bash start.sh` to test. "
    "If it fails, investigate and fix config.toml and .env, then retry. "
    "You may only edit config.toml and .env. Do NOT modify files under src/."
)

PIONEER_PROMPT = (
    "Get the auth module working on this branch. I've solved this before:\n\n"
    "1. Add [auth] to config.toml: port = 8080, algorithm = \"HS256\", session_timeout = 3600\n"
    "2. In .env, add AUTH_TOKEN (not SERVICE_TOKEN — it has format conflicts with other modules):\n"
    "   AUTH_TOKEN=overmind-branch-test-auth-token-2026xx\n"
    "3. Run `bash start.sh` to verify.\n\n"
    "You may only edit config.toml and .env. Do NOT modify files under src/."
)

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- You may edit: config.toml, .env
- Do NOT modify files under src/ or create new files.
""",
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python src/server.py 2>&1
""",
    "config.toml": """# Hive Server Configuration

[database]
pool_size = 5
timeout = 30

[logging]
level = "info"
format = "json"
""",
    ".env": """DATABASE_URL=postgresql://localhost:5432/hive
LOG_LEVEL=info
""",
    "src/config_loader.py": r'''"""Config loader — merges config.toml + .env into one dict."""

import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def _parse_env(env_path: Path) -> dict[str, str]:
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def load_config() -> dict:
    config_path = Path("config.toml")
    if not config_path.exists():
        print("FATAL: config.toml not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    config["env"] = _parse_env(Path(".env"))
    return config
''',
    "src/server.py": r'''#!/usr/bin/env python3
"""Hive Server — validates auth + api modules, checks for conflicts."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config
from auth import validate_auth
from api import validate_api
from ports import validate_ports


def main():
    config = load_config()

    validate_auth(config)
    validate_api(config)
    validate_ports(config)

    print("[Hive] Configuration validated successfully")
    print("[Hive] Server running on http://localhost:8080")


if __name__ == "__main__":
    main()
''',
    "src/auth.py": r'''"""Auth module validator.

TRAP 1 (partial): [auth].port required, hint suggests 8080.
TRAP 2 (partial): Needs a token — if SERVICE_TOKEN exists, validates HS256 format.
                   If AUTH_TOKEN exists, accepts it instead.
TRAP 3 (partial): [auth].session_timeout must be >= 3600.
"""

import re
import sys


def validate_auth(config: dict) -> None:
    if "auth" not in config:
        print("KeyError: 'auth'", file=sys.stderr)
        print("  Missing required configuration section: [auth]", file=sys.stderr)
        print("  Hint: auth services typically use port 8080", file=sys.stderr)
        sys.exit(1)

    auth = config["auth"]

    # Port
    port = auth.get("port")
    if not isinstance(port, int) or not (1024 <= port <= 65535):
        print(
            f"ValueError: [auth].port must be an integer 1024-65535, got: {port!r}",
            file=sys.stderr,
        )
        print("  Hint: auth services typically use port 8080", file=sys.stderr)
        sys.exit(1)

    # Algorithm
    algorithm = auth.get("algorithm", "")
    if algorithm not in ("HS256", "RS256"):
        print(
            f"ValueError: [auth].algorithm must be 'HS256' or 'RS256', got: {algorithm!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Token — prefer AUTH_TOKEN, fallback to SERVICE_TOKEN
    env = config.get("env", {})
    token = env.get("AUTH_TOKEN") or env.get("SERVICE_TOKEN", "")
    if not token:
        print("ValueError: AUTH_TOKEN or SERVICE_TOKEN must be set in .env", file=sys.stderr)
        sys.exit(1)

    # If using SERVICE_TOKEN, validate HS256 format (base64url, 32+ chars)
    if not env.get("AUTH_TOKEN") and env.get("SERVICE_TOKEN"):
        if not re.match(r'^[A-Za-z0-9_-]{32,}$', token):
            print(
                "ValueError: SERVICE_TOKEN must be HS256-compatible (base64url, 32+ chars)",
                file=sys.stderr,
            )
            print(f"  Got: '{token[:20]}...' (length {len(token)})", file=sys.stderr)
            sys.exit(1)

    # Session timeout
    session_timeout = auth.get("session_timeout")
    if not isinstance(session_timeout, int) or session_timeout < 3600:
        print(
            f"ValueError: [auth].session_timeout must be >= 3600, got: {session_timeout!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[auth] Auth OK: port={port}, algorithm={algorithm}, timeout={session_timeout}s",
          file=sys.stderr)
''',
    "src/api.py": r'''"""API module validator.

TRAP 1 (partial): [api].port required, hint suggests 8080.
TRAP 2 (partial): Needs a token — if SERVICE_TOKEN exists, validates UUID format.
                   If API_TOKEN exists, accepts it instead.
TRAP 3 (partial): [api].session_timeout must be <= 1800.
"""

import re
import sys


def validate_api(config: dict) -> None:
    if "api" not in config:
        print("KeyError: 'api'", file=sys.stderr)
        print("  Missing required configuration section: [api]", file=sys.stderr)
        print("  Hint: API gateway typically uses port 8080", file=sys.stderr)
        sys.exit(1)

    api = config["api"]

    # Port
    port = api.get("port")
    if not isinstance(port, int) or not (1024 <= port <= 65535):
        print(
            f"ValueError: [api].port must be an integer 1024-65535, got: {port!r}",
            file=sys.stderr,
        )
        print("  Hint: API gateway typically uses port 8080", file=sys.stderr)
        sys.exit(1)

    # Token — prefer API_TOKEN, fallback to SERVICE_TOKEN
    env = config.get("env", {})
    token = env.get("API_TOKEN") or env.get("SERVICE_TOKEN", "")
    if not token:
        print("ValueError: API_TOKEN or SERVICE_TOKEN must be set in .env", file=sys.stderr)
        sys.exit(1)

    # If using SERVICE_TOKEN, validate UUID format
    if not env.get("API_TOKEN") and env.get("SERVICE_TOKEN"):
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, token):
            print(
                "ValueError: SERVICE_TOKEN must be a valid UUID for API authentication",
                file=sys.stderr,
            )
            print(f"  Got: '{token[:20]}...'", file=sys.stderr)
            sys.exit(1)

    # Rate limit
    rate_limit = api.get("rate_limit")
    if not isinstance(rate_limit, int) or rate_limit <= 0:
        print(
            f"ValueError: [api].rate_limit must be a positive integer, got: {rate_limit!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Session timeout
    session_timeout = api.get("session_timeout")
    if not isinstance(session_timeout, int) or session_timeout > 1800:
        print(
            f"ValueError: [api].session_timeout must be <= 1800, got: {session_timeout!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[api] API OK: port={port}, rate_limit={rate_limit}, timeout={session_timeout}s",
          file=sys.stderr)
''',
    "src/ports.py": r'''"""Port conflict validator — all declared ports must be unique."""

import sys


def validate_ports(config: dict) -> None:
    ports: dict[str, int] = {}

    for section_name in ("auth", "api"):
        section = config.get(section_name, {})
        port = section.get("port")
        if isinstance(port, int):
            ports[section_name] = port

    # Check for conflicts — report ONE at a time
    names = list(ports.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if ports[names[i]] == ports[names[j]]:
                print(
                    f"AddressError: port conflict — [{names[i]}].port and [{names[j]}].port "
                    f"are both {ports[names[i]]}",
                    file=sys.stderr,
                )
                sys.exit(1)

    print(f"[ports] No conflicts: {ports}", file=sys.stderr)
''',
}
```

- [ ] **Step 2: create_scaffold() 함수 추가**

`branch_conflict.py` 하단에 추가:

```python
def create_scaffold(base_dir: Path, branch: str = "main") -> Path:
    """Create branch-conflict scaffold as a git repo on the specified branch.

    Args:
        base_dir: Parent directory for the repo.
        branch: Git branch to checkout after initial commit on main.
                Use "feat/auth" or "feat/api" for the test scenarios.
    """
    repo_dir = base_dir / REPO_NAME
    repo_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in SCAFFOLD_FILES.items():
        fp = repo_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(
        ["git", "init"], cwd=str(repo_dir), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial: Hive branch-conflict scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin",
         "https://github.com/test/hive-branch-conflict.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )

    # Checkout feature branch if not main
    if branch != "main":
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(repo_dir), capture_output=True, check=True,
        )

    return repo_dir
```

- [ ] **Step 3: check_config() 함수 추가**

`branch_conflict.py` 하단에 추가:

```python
def check_config(repo_dir: Path) -> dict:
    """Validate the current state of branch-conflict scaffold config files.

    Returns a dict with boolean checks for each trap area plus an all_ok flag.
    """
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    # Load .env
    env: dict[str, str] = {}
    env_path = repo_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

    # Load config.toml
    config: dict = {}
    config_path = repo_dir / "config.toml"
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # auth checks
    auth = config.get("auth", {})
    auth_port = auth.get("port")
    auth_port_ok = isinstance(auth_port, int) and 1024 <= auth_port <= 65535
    auth_algorithm_ok = auth.get("algorithm") in ("HS256", "RS256")
    auth_timeout = auth.get("session_timeout")
    auth_timeout_ok = isinstance(auth_timeout, int) and auth_timeout >= 3600
    auth_token = env.get("AUTH_TOKEN", "")
    auth_token_ok = len(auth_token) >= 1  # any non-empty AUTH_TOKEN is fine

    # api checks
    api = config.get("api", {})
    api_port = api.get("port")
    api_port_ok = isinstance(api_port, int) and 1024 <= api_port <= 65535
    api_rate_limit = api.get("rate_limit")
    api_rate_limit_ok = isinstance(api_rate_limit, int) and api_rate_limit > 0
    api_timeout = api.get("session_timeout")
    api_timeout_ok = isinstance(api_timeout, int) and api_timeout <= 1800
    api_token = env.get("API_TOKEN", "")
    api_token_ok = len(api_token) >= 1

    # port conflict check
    no_port_conflict = (
        auth_port_ok and api_port_ok and auth_port != api_port
    ) if (auth_port_ok and api_port_ok) else False

    # token separation check (not using SERVICE_TOKEN for both)
    tokens_separated = bool(auth_token) and bool(api_token)

    auth_ok = auth_port_ok and auth_algorithm_ok and auth_timeout_ok and (auth_token_ok or bool(env.get("SERVICE_TOKEN")))
    api_ok = api_port_ok and api_rate_limit_ok and api_timeout_ok and (api_token_ok or bool(env.get("SERVICE_TOKEN")))

    all_ok = auth_ok and api_ok and no_port_conflict

    return {
        "auth_port": auth_port,
        "auth_port_ok": auth_port_ok,
        "auth_algorithm_ok": auth_algorithm_ok,
        "auth_timeout_ok": auth_timeout_ok,
        "auth_token_ok": auth_token_ok,
        "api_port": api_port,
        "api_port_ok": api_port_ok,
        "api_rate_limit_ok": api_rate_limit_ok,
        "api_timeout_ok": api_timeout_ok,
        "api_token_ok": api_token_ok,
        "no_port_conflict": no_port_conflict,
        "tokens_separated": tokens_separated,
        "auth_ok": auth_ok,
        "api_ok": api_ok,
        "all_ok": all_ok,
    }
```

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/branch_conflict.py
git commit -m "feat: branch_conflict scaffold — 3 cross-branch traps"
```

---

### Task 2: check_config 단위 테스트

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/test_branch_conflict.py`

- [ ] **Step 1: check_config 정상/비정상 케이스 테스트 작성**

```python
"""Unit tests for branch_conflict scaffold — check_config + create_scaffold."""

import subprocess
from pathlib import Path

import pytest

from tests.fixtures.ab_scaffolds.branch_conflict import check_config, create_scaffold


class TestCheckConfig:
    """Test check_config() validation logic."""

    def _write_config(self, repo_dir: Path, config_toml: str, env: str) -> None:
        (repo_dir / "config.toml").write_text(config_toml, encoding="utf-8")
        (repo_dir / ".env").write_text(env, encoding="utf-8")

    def test_all_ok(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[database]
pool_size = 5

[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", """DATABASE_URL=postgresql://localhost/db
AUTH_TOKEN=my-auth-token
API_TOKEN=my-api-token
""")
        result = check_config(repo)
        assert result["all_ok"] is True
        assert result["no_port_conflict"] is True
        assert result["tokens_separated"] is True

    def test_port_conflict(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 8080
rate_limit = 100
session_timeout = 900
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["no_port_conflict"] is False
        assert result["all_ok"] is False

    def test_missing_auth_section(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "API_TOKEN=y\n")
        result = check_config(repo)
        assert result["auth_ok"] is False
        assert result["all_ok"] is False

    def test_auth_timeout_too_low(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 1800

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["auth_timeout_ok"] is False

    def test_api_timeout_too_high(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 3600
""", "AUTH_TOKEN=x\nAPI_TOKEN=y\n")
        result = check_config(repo)
        assert result["api_timeout_ok"] is False

    def test_tokens_not_separated(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._write_config(repo, """
[auth]
port = 8080
algorithm = "HS256"
session_timeout = 3600

[api]
port = 9090
rate_limit = 100
session_timeout = 900
""", "SERVICE_TOKEN=some-token\n")
        result = check_config(repo)
        assert result["tokens_separated"] is False


class TestCreateScaffold:
    """Test create_scaffold() git repo creation with branches."""

    def test_creates_on_main(self, tmp_path):
        repo_dir = create_scaffold(tmp_path, branch="main")
        assert repo_dir.exists()
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "main"

    def test_creates_on_feat_auth(self, tmp_path):
        repo_dir = create_scaffold(tmp_path / "auth", branch="feat/auth")
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat/auth"

    def test_creates_on_feat_api(self, tmp_path):
        repo_dir = create_scaffold(tmp_path / "api", branch="feat/api")
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat/api"

    def test_has_remote_origin(self, tmp_path):
        repo_dir = create_scaffold(tmp_path, branch="main")
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert "hive-branch-conflict" in result.stdout

    def test_base_branch_is_main(self, tmp_path):
        """feat/auth should have main as merge-base."""
        repo_dir = create_scaffold(tmp_path / "b", branch="feat/auth")
        result = subprocess.run(
            ["git", "merge-base", "main", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip()  # merge-base exists
```

- [ ] **Step 2: 테스트 실행**

Run: `cd server && uv run pytest tests/fixtures/ab_scaffolds/test_branch_conflict.py -v`
Expected: 10개 전부 PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/test_branch_conflict.py
git commit -m "test: branch_conflict scaffold check_config + create_scaffold 10 tests"
```

---

### Task 3: __init__.py 등록 + analyze_conversation 확장

**Files:**
- Modify: `server/tests/fixtures/ab_scaffolds/__init__.py`
- Modify: `server/tests/fixtures/ab_runner.py`

- [ ] **Step 1: __init__.py에 branch_conflict import 추가**

```python
"""Scaffold registry for A/B tests.

Each scaffold module exposes:
  SCAFFOLD_FILES: dict[str, str]
  SHARED_PROMPT: str
  PIONEER_PROMPT: str  (optional — smarter prompt for pioneer agent)
  REPO_NAME: str
  REPO_ID: str
  MAX_TURNS: int
  create_scaffold(base_dir: Path) -> Path
"""
from . import simple, multistage, nightmare, branch_conflict
from . import complex as complex_

SCAFFOLDS: dict = {
    "simple": simple,
    "multistage": multistage,
    "complex": complex_,
    "nightmare": nightmare,
    "branch_conflict": branch_conflict,
}
```

주의: branch_conflict는 `create_scaffold(base_dir, branch)` 시그니처가 다른 scaffold와 다름 (branch 파라미터 추가). 기존 statistical test의 parametrize에서는 `scaffold.create_scaffold(tmp_path / name)` 호출 패턴이므로, branch_conflict는 **별도 테스트 함수**에서만 사용. SCAFFOLDS에 등록하되, 기존 test_statistical_ab는 branch_conflict를 제외해야 함.

- [ ] **Step 2: analyze_conversation에 branch-specific 지표 추가**

`ab_runner.py`의 `analyze_conversation()` 함수 끝부분, return dict에 추가:

```python
    # Branch-conflict specific metrics
    port_conflict_count = sum(
        1 for evt in events
        if evt.get("type") == "user"
        and isinstance(evt.get("message", {}), dict)
        and any(
            "AddressError" in str(block.get("content", "")) or "port conflict" in str(block.get("content", ""))
            for block in evt.get("message", {}).get("content", [])
            if isinstance(block, dict)
        )
    )
    # Also check tool_use_result for port conflict
    for evt in events:
        if evt.get("type") == "user":
            result = evt.get("tool_use_result")
            if result and isinstance(result, str):
                if "AddressError" in result or "port conflict" in result:
                    port_conflict_count += 1
```

그리고 return dict에:

```python
        "port_conflict_count": port_conflict_count,
```

- [ ] **Step 3: NUMERIC_METRICS에 추가**

```python
NUMERIC_METRICS = [
    "total_tool_uses",
    "bash_commands",
    "server_run_attempts",
    "config_toml_edits",
    "config_file_edits",
    "src_file_reads",
    "src_file_edits",
    "first_config_edit_step",
    "first_server_run_step",
    "port_conflict_count",
]
```

- [ ] **Step 4: 기존 테스트가 깨지지 않는지 확인**

Run: `cd server && uv run pytest tests/ -v --ignore=tests/scenarios -k "not e2e_live"`
Expected: 기존 207+ 테스트 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/__init__.py server/tests/fixtures/ab_runner.py
git commit -m "feat: register branch_conflict scaffold + port_conflict_count metric"
```

---

### Task 4: Branch-Aware E2E 테스트 함수

**Files:**
- Modify: `server/tests/scenarios/test_live_agents_AB_statistical.py`

- [ ] **Step 1: test_branch_aware_ab 함수 추가**

파일 끝에 추가:

```python
@pytest.mark.e2e_live
def test_branch_aware_ab(claude_cli, server, base_url, tmp_path, request):
    """Branch-aware A/B: Pioneer on feat/auth, Student+Naive on feat/api.

    Tests cross-branch intent/discovery sharing via Overmind's 3-tier relevance.
    Pioneer's events (port choice, token naming, session config) should help
    Students on a sibling branch avoid conflicts.
    """
    from tests.fixtures.ab_scaffolds import branch_conflict

    N = request.config.getoption("--student-n")
    M = request.config.getoption("--naive-m")
    model = request.config.getoption("--agent-model")
    scaffold = branch_conflict
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    print(f"\n{'=' * 70}")
    print(f"  Branch-Aware A/B: branch_conflict (N={N}, M={M}, model={model or 'default'})")
    print(f"{'=' * 70}")

    # Create scaffolds on different branches
    # Pioneer: feat/auth, Students+Naives: feat/api
    repos = {"pioneer": scaffold.create_scaffold(tmp_path / "pioneer", branch="feat/auth")}
    for i in range(N):
        repos[f"student_{i}"] = scaffold.create_scaffold(
            tmp_path / f"student_{i}", branch="feat/api"
        )
    for i in range(M):
        repos[f"naive_{i}"] = scaffold.create_scaffold(
            tmp_path / f"naive_{i}", branch="feat/api"
        )
    print(f"  Created {1 + N + M} scaffold repos (pioneer=feat/auth, rest=feat/api)")

    # Phase 1: Pioneer on feat/auth
    print(f"\n  Phase 1: Pioneer (feat/auth, prompt=PIONEER)")
    pioneer = run_agent(
        prompt=scaffold.PIONEER_PROMPT, cwd=repos["pioneer"],
        user="pioneer", state_file=state_dir / "state_pioneer.json",
        base_url=base_url, repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS, with_overmind=True, model=model,
    )
    print(f"  Pioneer: {pioneer.elapsed:.1f}s, runs={pioneer.analysis['server_run_attempts']}, "
          f"success={pioneer.analysis['saw_server_running']}")

    # Verify pioneer pushed events
    pull = api_get(base_url, "/api/memory/pull", {"repo_id": scaffold.REPO_ID, "limit": "100"})
    p_events = [e for e in pull["events"] if e["user"] == "pioneer"]
    assert len(p_events) >= 1, "Pioneer must push at least 1 event"

    # Check that pioneer events have branch metadata
    branched = [e for e in p_events if e.get("current_branch") == "feat/auth"]
    print(f"  Pioneer pushed {len(p_events)} events ({len(branched)} with branch metadata)")

    # Phase 2: Students + Naives on feat/api (parallel)
    print(f"\n  Phase 2: {N} students + {M} naives on feat/api in parallel...")
    agents = []
    for i in range(N):
        agents.append(AgentSpec(
            name=f"student_{i}", cwd=repos[f"student_{i}"],
            user=f"student_{i}", state_file=state_dir / f"state_student_{i}.json",
            with_overmind=True,
        ))
    for i in range(M):
        agents.append(AgentSpec(
            name=f"naive_{i}", cwd=repos[f"naive_{i}"],
            user=f"naive_{i}", state_file=state_dir / f"state_naive_{i}.json",
            with_overmind=False,
        ))

    results = run_parallel_agents(
        agents=agents, prompt=scaffold.SHARED_PROMPT,
        base_url=base_url, repo_id=scaffold.REPO_ID,
        max_turns=scaffold.MAX_TURNS, model=model,
    )

    # Phase 3: Analyze
    students = [results[f"student_{i}"] for i in range(N)]
    naives = [results[f"naive_{i}"] for i in range(M)]
    student_stats = compute_statistics([s.analysis for s in students])
    naive_stats = compute_statistics([n.analysis for n in naives])
    student_elapsed = compute_elapsed_stats(students)
    naive_elapsed = compute_elapsed_stats(naives)

    # Phase 4: Print comparison
    print_comparison_table(
        pioneer=pioneer.analysis, student_stats=student_stats,
        naive_stats=naive_stats, student_elapsed=student_elapsed,
        naive_elapsed=naive_elapsed, n=N, m=M,
        scaffold_name="branch_conflict", model=model,
        pioneer_elapsed=pioneer.elapsed,
    )

    # Phase 5: Save reports
    report = generate_report(
        scaffold_name="branch_conflict", model=model,
        pioneer=pioneer, students=students, naives=naives, n=N, m=M,
    )
    save_report(report, report_dir / "branch_conflict_report.json")
    save_jsonl(pioneer.events, report_dir / "pioneer.jsonl")
    for i in range(N):
        save_jsonl(results[f"student_{i}"].events, report_dir / f"student_{i}.jsonl")
    for i in range(M):
        save_jsonl(results[f"naive_{i}"].events, report_dir / f"naive_{i}.jsonl")
    print(f"\n  Reports saved to: {report_dir}")

    # Assertions: all agents completed
    for i in range(N):
        assert f"student_{i}" in results, f"student_{i} didn't complete"
    for i in range(M):
        assert f"naive_{i}" in results, f"naive_{i} didn't complete"

    # Branch-specific assertion: students should have fewer port conflicts
    s_port = student_stats.get("port_conflict_count", {}).get("mean", 0) or 0
    n_port = naive_stats.get("port_conflict_count", {}).get("mean", 0) or 0
    if s_port > n_port:
        print(f"\n  WARNING: Students had MORE port conflicts ({s_port}) than naives ({n_port})")
```

- [ ] **Step 2: test_statistical_ab에서 branch_conflict 제외**

기존 parametrize를 수정:

```python
@pytest.mark.e2e_live
@pytest.mark.parametrize("scaffold_name", [k for k in SCAFFOLDS if k != "branch_conflict"])
def test_statistical_ab(scaffold_name, claude_cli, server, base_url, tmp_path, request):
```

이유: branch_conflict는 `create_scaffold(base_dir, branch)` 시그니처가 다르고, Pioneer와 Student가 서로 다른 branch를 사용해야 하므로 기존 flow와 호환되지 않음.

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_live_agents_AB_statistical.py
git commit -m "feat: test_branch_aware_ab — cross-branch E2E with port conflict metrics"
```

---

### Task 5: 통합 검증

**Files:** (변경 없음, 검증만)

- [ ] **Step 1: 전체 단위 테스트 실행**

Run: `cd server && uv run pytest tests/ -v --ignore=tests/scenarios -k "not e2e_live"`
Expected: 기존 207+ 테스트 + 새 branch_conflict 테스트 10개 = 217+ PASS

- [ ] **Step 2: branch_conflict 테스트만 실행**

Run: `cd server && uv run pytest tests/fixtures/ab_scaffolds/test_branch_conflict.py -v`
Expected: 10 PASS

- [ ] **Step 3: scaffold 파일 수동 검증 — start.sh가 실제로 동작하는지**

```bash
cd /tmp && python -c "
from pathlib import Path
import sys; sys.path.insert(0, 'D:/github/overmind/server')
from tests.fixtures.ab_scaffolds.branch_conflict import create_scaffold
repo = create_scaffold(Path('/tmp/test_scaffold'), branch='feat/auth')
print(f'Created at: {repo}')
import subprocess
r = subprocess.run(['bash', 'start.sh'], cwd=str(repo), capture_output=True, text=True)
print('STDOUT:', r.stdout[:200])
print('STDERR:', r.stderr[:200])
print('Return code:', r.returncode)
"
```

Expected: returncode=1, stderr에 `KeyError: 'auth'` 또는 유사 에러 (scaffold가 의도적으로 불완전하므로)

- [ ] **Step 4: 최종 커밋 (필요 시)**

모든 테스트 통과 후, 수정이 있으면 커밋:

```bash
git add -A
git commit -m "fix: branch_conflict scaffold adjustments from integration test"
```

---

### Task 6 (Optional): Live E2E 실행

**Files:** (변경 없음, 실행만)

- [ ] **Step 1: Live E2E 테스트 실행**

```bash
cd server && uv run pytest tests/scenarios/test_live_agents_AB_statistical.py \
  -m e2e_live -s -k branch_aware --student-n 2 --naive-m 2 --agent-model haiku
```

Expected: Pioneer(feat/auth) 성공 → Student(feat/api) cross-branch intent 수신 → Naive(feat/api) 없음.

- [ ] **Step 2: 결과 분석 + docs/benchmark-ab-test.md 업데이트**

결과에서 Student vs Naive 비교:
- port_conflict_count: Student < Naive 기대
- elapsed: Student < Naive 기대
- saw_server_running: Student > Naive 기대

---

## 파일 변경 요약

| 파일 | Task | 유형 |
|------|------|------|
| `server/tests/fixtures/ab_scaffolds/branch_conflict.py` | 1 | 신규 |
| `server/tests/fixtures/ab_scaffolds/test_branch_conflict.py` | 2 | 신규 |
| `server/tests/fixtures/ab_scaffolds/__init__.py` | 3 | 수정 (import 1줄) |
| `server/tests/fixtures/ab_runner.py` | 3 | 수정 (port_conflict metric) |
| `server/tests/scenarios/test_live_agents_AB_statistical.py` | 4 | 수정 (test_branch_aware_ab 추가) |
