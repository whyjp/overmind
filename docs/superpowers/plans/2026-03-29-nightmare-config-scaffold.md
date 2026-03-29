# Nightmare Config Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a complex AB test scaffold with 5 interdependent traps that demonstrates Overmind's cross-agent knowledge sharing value — Student should need 30%+ fewer server runs than Naive.

**Architecture:** Python microservice with config spread across 4 files (config.toml, .env, secrets/hmac.key, plugins/registry.json). Server loads modules sequentially; each module validates its config section and throws on the first failure. Traps are designed with misleading errors, cross-file dependencies, and multi-hop reasoning chains that punish iterative discovery.

**Tech Stack:** Python 3.11+ (tomllib, hashlib, json, os, pathlib), pytest

**Spec:** `docs/superpowers/specs/2026-03-29-nightmare-config-scaffold-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `server/tests/fixtures/ab_scaffolds/nightmare.py` | Create | Scaffold module: SCAFFOLD_FILES dict, create_scaffold(), check_config() |
| `server/tests/fixtures/ab_scaffolds/__init__.py` | Modify | Add nightmare to SCAFFOLDS registry |
| `server/tests/fixtures/ab_runner.py` | Modify | Extend analyze_conversation for multi-file config edits |
| `server/tests/test_nightmare_scaffold.py` | Create | Unit tests: scaffold creation, trap sequence, check_config, analyze |

All Python source files for the scaffold (server.py, config_loader.py, db.py, auth.py, cache.py, session.py, metrics.py, plugins.py) live as string values inside `SCAFFOLD_FILES` in `nightmare.py` — they are NOT separate files in our repo.

---

### Task 1: Scaffold Module Skeleton + Registry

**Files:**
- Create: `server/tests/fixtures/ab_scaffolds/nightmare.py`
- Modify: `server/tests/fixtures/ab_scaffolds/__init__.py`
- Test: `server/tests/test_nightmare_scaffold.py`

- [ ] **Step 1: Write test for scaffold module interface**

```python
# server/tests/test_nightmare_scaffold.py
"""Tests for the nightmare config scaffold."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.ab_scaffolds import nightmare, SCAFFOLDS


class TestNightmareScaffoldStructure:
    """Verify scaffold module exports and file creation."""

    def test_module_exports(self):
        """Scaffold module exposes required interface."""
        assert hasattr(nightmare, "SCAFFOLD_FILES")
        assert hasattr(nightmare, "SHARED_PROMPT")
        assert hasattr(nightmare, "REPO_NAME")
        assert hasattr(nightmare, "REPO_ID")
        assert hasattr(nightmare, "MAX_TURNS")
        assert hasattr(nightmare, "create_scaffold")
        assert hasattr(nightmare, "check_config")

    def test_registered_in_scaffolds(self):
        """Nightmare is in the SCAFFOLDS registry."""
        assert "nightmare" in SCAFFOLDS
        assert SCAFFOLDS["nightmare"] is nightmare

    def test_constants(self):
        assert nightmare.REPO_NAME == "hive-nightmare"
        assert nightmare.REPO_ID == "github.com/test/hive-nightmare"
        assert nightmare.MAX_TURNS == 40

    def test_scaffold_files_has_required_keys(self):
        required = [
            "CLAUDE.md", "config.toml", ".env", "secrets/hmac.key",
            "plugins/registry.json", "start.sh",
            "src/server.py", "src/config_loader.py",
            "src/db.py", "src/auth.py", "src/cache.py",
            "src/session.py", "src/metrics.py", "src/plugins.py",
        ]
        for key in required:
            assert key in nightmare.SCAFFOLD_FILES, f"Missing: {key}"

    def test_create_scaffold(self, tmp_path):
        """create_scaffold produces a git repo with all files."""
        repo = nightmare.create_scaffold(tmp_path)
        assert repo.exists()
        assert (repo / ".git").is_dir()
        for rel in nightmare.SCAFFOLD_FILES:
            assert (repo / rel).exists(), f"Missing file: {rel}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareScaffoldStructure -v`
Expected: FAIL — module `nightmare` not found

- [ ] **Step 3: Create nightmare.py skeleton + register**

```python
# server/tests/fixtures/ab_scaffolds/nightmare.py
"""Nightmare config scaffold: Python microservice with 5 interdependent traps.

Traps: misleading error, cross-file SHA256 validation, mutual dependency,
three-way port conflict, three-hop plugin chain.

Config spread across: config.toml, .env, secrets/hmac.key, plugins/registry.json
"""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-nightmare"
REPO_ID = "github.com/test/hive-nightmare"
MAX_TURNS = 40

SHARED_PROMPT = (
    "Get the Hive Nightmare service running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may edit config.toml, .env, secrets/hmac.key, and plugins/registry.json only."
)

SCAFFOLD_FILES: dict[str, str] = {}  # populated in Tasks 2-4

def create_scaffold(base_dir: Path) -> Path:
    repo_dir = base_dir / REPO_NAME
    repo_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in SCAFFOLD_FILES.items():
        fp = repo_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial: Hive nightmare scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-nightmare.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


def check_config(repo_dir: Path) -> dict:
    """Placeholder — implemented in Task 6."""
    return {}
```

Add to `__init__.py`:

```python
# server/tests/fixtures/ab_scaffolds/__init__.py
from . import simple, multistage, nightmare
from . import complex as complex_

SCAFFOLDS: dict = {
    "simple": simple,
    "multistage": multistage,
    "complex": complex_,
    "nightmare": nightmare,
}
```

- [ ] **Step 4: Run tests to verify structure tests pass (except SCAFFOLD_FILES content)**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareScaffoldStructure -v`
Expected: `test_scaffold_files_has_required_keys` FAILS (SCAFFOLD_FILES empty), others PASS

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/nightmare.py server/tests/fixtures/ab_scaffolds/__init__.py server/tests/test_nightmare_scaffold.py
git commit -m "feat: nightmare scaffold skeleton + test + registry"
```

---

### Task 2: Config Files + Start Script

**Files:**
- Modify: `server/tests/fixtures/ab_scaffolds/nightmare.py` (add to SCAFFOLD_FILES)

- [ ] **Step 1: Add config files to SCAFFOLD_FILES**

Add these entries to the `SCAFFOLD_FILES` dict in `nightmare.py`:

```python
SCAFFOLD_FILES: dict[str, str] = {
    # ── CLAUDE.md: rules for the agent ──
    "CLAUDE.md": """# Hive Nightmare Service

## Start
Run `bash start.sh` to start the server.

## Rules
- You may edit: config.toml, .env, secrets/hmac.key, plugins/registry.json
- Do NOT modify files under src/ or any .py files.
- Do NOT create new files.
""",

    # ── start.sh: launcher ──
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "[start.sh] Starting Hive Nightmare service..."
python src/server.py 2>&1
""",

    # ── config.toml: partial — only [database] and [auth] ──
    "config.toml": """# Hive Nightmare Service Configuration

[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600
""",

    # ── .env: placeholder values ──
    ".env": """# Hive Environment Variables
DATABASE_URL=changeme://localhost/db
SECRET_KEY=dev-placeholder-key
NODE_ENV=development
""",

    # ── secrets/hmac.key: zero-filled (invalid) ──
    "secrets/hmac.key": "0000000000000000000000000000000000000000000000000000000000000000",

    # ── plugins/registry.json: missing 'enabled' field ──
    "plugins/registry.json": """{
  "plugins": [
    {"name": "audit-log", "module": "audit"}
  ]
}
""",
}
```

- [ ] **Step 2: Run test to confirm config file keys now present**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareScaffoldStructure::test_scaffold_files_has_required_keys -v`
Expected: FAIL — src/ files still missing (that's expected, added in Task 3-4)

- [ ] **Step 3: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/nightmare.py
git commit -m "feat: nightmare scaffold config files + start script"
```

---

### Task 3: Config Loader + Server Entry Point

**Files:**
- Modify: `server/tests/fixtures/ab_scaffolds/nightmare.py` (add src/config_loader.py and src/server.py to SCAFFOLD_FILES)
- Test: `server/tests/test_nightmare_scaffold.py`

- [ ] **Step 1: Write test for trap sequence**

Add to `server/tests/test_nightmare_scaffold.py`:

```python
class TestNightmareTrapSequence:
    """Run scaffold server.py and verify traps fire in order."""

    @pytest.fixture()
    def repo(self, tmp_path):
        return nightmare.create_scaffold(tmp_path)

    def _run_server(self, repo: Path) -> tuple[int, str, str]:
        """Run start.sh in the scaffold repo, return (returncode, stdout, stderr)."""
        result = subprocess.run(
            ["bash", "start.sh"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr

    def test_trap1_misleading_db_error(self, repo):
        """Initial state triggers TRAP 1: db.py parse error pointing at wrong file."""
        rc, stdout, stderr = self._run_server(repo)
        assert rc != 0
        combined = stdout + stderr
        # Error mentions db.py / parse — misleading traceback
        assert "database" in combined.lower() or "parse" in combined.lower()
        assert "DATABASE_URL" in combined or "url" in combined.lower()

    def test_trap2_after_fixing_db(self, repo):
        """After fixing .env DATABASE_URL, TRAP 2: auth HMAC mismatch."""
        env_path = repo / ".env"
        content = env_path.read_text(encoding="utf-8")
        content = content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        env_path.write_text(content, encoding="utf-8")

        rc, stdout, stderr = self._run_server(repo)
        assert rc != 0
        combined = stdout + stderr
        assert "HMAC" in combined or "key" in combined.lower() or "digest" in combined.lower()

    def test_trap3_after_fixing_auth(self, repo):
        """After fixing auth (SECRET_KEY + hmac.key pair), TRAP 3: session missing."""
        import hashlib

        # Fix TRAP 1
        env_path = repo / ".env"
        content = env_path.read_text(encoding="utf-8")
        content = content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        # Fix TRAP 2: set SECRET_KEY and matching hmac.key
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        content = content.replace("SECRET_KEY=dev-placeholder-key", f"SECRET_KEY={secret}")
        env_path.write_text(content, encoding="utf-8")
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        rc, stdout, stderr = self._run_server(repo)
        assert rc != 0
        combined = stdout + stderr
        assert "session" in combined.lower()

    def test_trap4_after_fixing_session_cache(self, repo):
        """After fixing session+cache, TRAP 4: port conflict."""
        import hashlib

        # Fix TRAPs 1-2
        env_path = repo / ".env"
        content = env_path.read_text(encoding="utf-8")
        content = content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        content = content.replace("SECRET_KEY=dev-placeholder-key", f"SECRET_KEY={secret}")
        env_path.write_text(content, encoding="utf-8")
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix TRAP 3: add [session] + [cache] with correct dependency
        config_path = repo / "config.toml"
        config_content = config_path.read_text(encoding="utf-8")
        config_content += """
[session]
timeout = 3600

[cache]
ttl_seconds = 1800
backend = "memory"
max_items = 1000
"""
        config_path.write_text(config_content, encoding="utf-8")

        rc, stdout, stderr = self._run_server(repo)
        assert rc != 0
        combined = stdout + stderr
        assert "port" in combined.lower()

    def test_trap5_after_fixing_ports(self, repo):
        """After fixing ports, TRAP 5: plugin chain."""
        import hashlib

        # Fix TRAPs 1-2
        env_path = repo / ".env"
        content = env_path.read_text(encoding="utf-8")
        content = content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        content = content.replace("SECRET_KEY=dev-placeholder-key", f"SECRET_KEY={secret}")
        env_path.write_text(content, encoding="utf-8")
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix TRAPs 3-4
        config_path = repo / "config.toml"
        config_content = config_path.read_text(encoding="utf-8")
        config_content += """
[session]
timeout = 3600

[cache]
ttl_seconds = 1800
backend = "memory"
max_items = 1000

[server]
port = 8080

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30
"""
        config_path.write_text(config_content, encoding="utf-8")

        rc, stdout, stderr = self._run_server(repo)
        assert rc != 0
        combined = stdout + stderr
        assert "plugin" in combined.lower() or "registry" in combined.lower()

    def test_all_traps_fixed_success(self, repo):
        """With all traps fixed, server starts successfully."""
        import hashlib

        # Fix TRAP 1
        env_path = repo / ".env"
        content = env_path.read_text(encoding="utf-8")
        content = content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        # Fix TRAP 2
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        content = content.replace("SECRET_KEY=dev-placeholder-key", f"SECRET_KEY={secret}")
        # Fix TRAP 5 (partial): add PLUGIN_PATH
        content += "\nPLUGIN_PATH=./plugins\n"
        env_path.write_text(content, encoding="utf-8")
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix TRAP 5 (partial): add enabled to registry.json
        import json
        reg_path = repo / "plugins" / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["plugins"][0]["enabled"] = True
        reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        # Fix TRAPs 3-4-5
        config_path = repo / "config.toml"
        config_content = config_path.read_text(encoding="utf-8")
        config_content += """
[session]
timeout = 3600

[cache]
ttl_seconds = 1800
backend = "memory"
max_items = 1000

[server]
port = 8080

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30

[plugins]
enabled = true
registry_path = "plugins/registry.json"
"""
        config_path.write_text(config_content, encoding="utf-8")

        rc, stdout, stderr = self._run_server(repo)
        combined = stdout + stderr
        assert rc == 0, f"Server failed: {combined}"
        assert "Configuration validated successfully" in combined
```

- [ ] **Step 2: Run tests to confirm they fail (no src/ files yet)**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareTrapSequence -v`
Expected: FAIL — src/server.py not in SCAFFOLD_FILES

- [ ] **Step 3: Add config_loader.py to SCAFFOLD_FILES**

Add to `SCAFFOLD_FILES` in `nightmare.py`:

```python
    # ── src/config_loader.py: unified config loader ──
    "src/config_loader.py": r'''"""Config loader: merges config.toml + .env + secrets/ into one dict."""

import os
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    print("ERROR: Python 3.11+ required (tomllib)", file=sys.stderr)
    sys.exit(1)


def _load_env(env_path: Path) -> dict[str, str]:
    """Parse .env file into dict. Ignores comments and blank lines."""
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def load_config() -> dict:
    """Load and merge all config sources.

    Returns a dict with:
      - All sections from config.toml
      - env: dict from .env file
      - secrets: dict with file contents from secrets/
    """
    config_path = Path("config.toml")
    if not config_path.exists():
        print("=== CONFIGURATION ERROR ===", file=sys.stderr)
        print("config.toml not found.", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    # Merge .env
    env = _load_env(Path(".env"))
    config["env"] = env

    # Load secrets
    secrets_dir = Path("secrets")
    secrets = {}
    if secrets_dir.is_dir():
        for fp in secrets_dir.iterdir():
            if fp.is_file():
                secrets[fp.stem] = fp.read_text(encoding="utf-8").strip()
    config["secrets"] = secrets

    return config
''',
```

- [ ] **Step 4: Add server.py to SCAFFOLD_FILES**

```python
    # ── src/server.py: entry point — sequential module validation ──
    "src/server.py": r'''#!/usr/bin/env python3
"""Hive Nightmare Service — validates config then reports success."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_config

def main():
    config = load_config()

    # Validate modules in order — first failure stops execution
    from db import validate_db
    validate_db(config)

    from auth import validate_auth
    validate_auth(config)

    from session import validate_session
    validate_session(config)

    from cache import validate_cache
    validate_cache(config)

    from metrics import validate_server_ports
    validate_server_ports(config)

    from plugins import validate_plugins
    validate_plugins(config)

    # All passed
    print("[Hive] Configuration validated successfully")
    print("[Hive] All modules loaded. Server ready.")

if __name__ == "__main__":
    main()
''',
```

- [ ] **Step 5: Run structure test to check src files present (still partial)**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareScaffoldStructure::test_scaffold_files_has_required_keys -v`
Expected: FAIL — remaining src/ files not yet added

- [ ] **Step 6: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/nightmare.py server/tests/test_nightmare_scaffold.py
git commit -m "feat: nightmare scaffold config_loader + server entry point + trap tests"
```

---

### Task 4: Trap Source Files

**Files:**
- Modify: `server/tests/fixtures/ab_scaffolds/nightmare.py` (add 6 trap modules to SCAFFOLD_FILES)

- [ ] **Step 1: Add TRAP 1 — db.py (misleading error)**

Add to `SCAFFOLD_FILES`:

```python
    # ── src/db.py: TRAP 1 — misleading error ──
    # Traceback points here, but actual fix is in .env DATABASE_URL
    "src/db.py": r'''"""Database module — validates DATABASE_URL from environment."""

import sys
from urllib.parse import urlparse


def validate_db(config: dict) -> None:
    """Validate database connection URL.

    Reads DATABASE_URL from .env (loaded into config['env']).
    Raises on invalid URL scheme — but the traceback points HERE,
    even though the fix is in .env.
    """
    url = config.get("env", {}).get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    parsed = parse_url(url)
    if parsed["scheme"] not in ("postgresql", "postgres", "mysql", "sqlite"):
        print(f"=== DATABASE ERROR in db.py:parse_url() ===", file=sys.stderr)
        print(f"  ConnectionError: Failed to parse database URL scheme", file=sys.stderr)
        print(f"  Got scheme: '{parsed['scheme']}'", file=sys.stderr)
        print(f"  File: src/db.py, line 34, in parse_url", file=sys.stderr)
        print(f"  Traceback (most recent call last):", file=sys.stderr)
        print(f"    db.py:parse_url -> _validate_scheme -> raise ConnectionError", file=sys.stderr)
        print(f"========================================", file=sys.stderr)
        sys.exit(1)

    pool = config.get("database", {}).get("pool_size", 5)
    print(f"[db] Database OK: {parsed['scheme']}://.../{parsed['dbname']} (pool={pool})")


def parse_url(url: str) -> dict:
    """Parse a database URL into components."""
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") or "default",
        "user": parsed.username,
    }
''',
```

- [ ] **Step 2: Add TRAP 2 — auth.py (cross-file SHA256 validation)**

```python
    # ── src/auth.py: TRAP 2 — cross-file secret validation ──
    # SECRET_KEY in .env must match SHA256 digest in secrets/hmac.key
    "src/auth.py": r'''"""Auth module — validates HMAC key consistency across files."""

import hashlib
import sys


def validate_auth(config: dict) -> None:
    """Validate that secrets/hmac.key contains SHA256(SECRET_KEY).

    The relationship between these two values is:
        hmac.key content == hashlib.sha256(SECRET_KEY.encode()).hexdigest()

    Error message hints at 'digest does not match' but does NOT
    reveal the SHA256 relationship — agent must read this source.
    """
    secret_key = config.get("env", {}).get("SECRET_KEY", "")
    hmac_key = config.get("secrets", {}).get("hmac", "")
    algorithm = config.get("auth", {}).get("algorithm", "HS256")

    if not secret_key:
        print("ERROR: SECRET_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    if not hmac_key:
        print("ERROR: secrets/hmac.key is empty or missing", file=sys.stderr)
        sys.exit(1)

    expected_digest = hashlib.sha256(secret_key.encode()).hexdigest()

    if hmac_key != expected_digest:
        print(f"=== AUTH ERROR ===", file=sys.stderr)
        print(f"  ValueError: HMAC key verification failed", file=sys.stderr)
        print(f"  Key file digest does not match SECRET_KEY", file=sys.stderr)
        print(f"  Algorithm: {algorithm}", file=sys.stderr)
        print(f"  Hint: The key file must contain a valid digest of your secret", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    print(f"[auth] Auth OK: algorithm={algorithm}, key verified")
''',
```

- [ ] **Step 3: Add TRAP 3 — session.py + cache.py (mutual dependency)**

```python
    # ── src/session.py: TRAP 3a — session config required ──
    "src/session.py": r'''"""Session module — validates [session] config section."""

import sys


def validate_session(config: dict) -> None:
    """Validate session configuration.

    Requires [session] section with 'timeout' (int, >= 60).
    Must be validated BEFORE cache (cache depends on session.timeout).
    """
    if "session" not in config:
        print("=== SESSION ERROR ===", file=sys.stderr)
        print("  KeyError: 'session'", file=sys.stderr)
        print("  Missing required config section: [session]", file=sys.stderr)
        print("  Required keys: timeout (integer, >= 60)", file=sys.stderr)
        print("=====================", file=sys.stderr)
        sys.exit(1)

    session = config["session"]
    timeout = session.get("timeout")

    if not isinstance(timeout, int) or timeout < 60:
        print(f"=== SESSION ERROR ===", file=sys.stderr)
        print(f"  ValueError: session.timeout must be integer >= 60", file=sys.stderr)
        print(f"  Got: {timeout!r}", file=sys.stderr)
        print(f"=====================", file=sys.stderr)
        sys.exit(1)

    print(f"[session] Session OK: timeout={timeout}s")
''',

    # ── src/cache.py: TRAP 3b — cache depends on session.timeout ──
    "src/cache.py": r'''"""Cache module — validates [cache] config with session dependency."""

import sys


def validate_cache(config: dict) -> None:
    """Validate cache configuration.

    Rules:
      1. cache.ttl_seconds must be < session.timeout (strict less-than)
      2. If backend == "redis": redis_url is required
      3. If backend == "memory": max_items is required (int > 0)
    """
    if "cache" not in config:
        print("=== CACHE ERROR ===", file=sys.stderr)
        print("  KeyError: 'cache'", file=sys.stderr)
        print("  Missing required config section: [cache]", file=sys.stderr)
        print("  Required keys: ttl_seconds, backend", file=sys.stderr)
        print("===================", file=sys.stderr)
        sys.exit(1)

    cache = config["cache"]
    session_timeout = config.get("session", {}).get("timeout", 0)
    ttl = cache.get("ttl_seconds")
    backend = cache.get("backend", "")

    if not isinstance(ttl, int) or ttl <= 0:
        print(f"=== CACHE ERROR ===", file=sys.stderr)
        print(f"  ValueError: cache.ttl_seconds must be a positive integer", file=sys.stderr)
        print(f"  Got: {ttl!r}", file=sys.stderr)
        print(f"===================", file=sys.stderr)
        sys.exit(1)

    if ttl >= session_timeout:
        print(f"=== CACHE ERROR ===", file=sys.stderr)
        print(f"  ValueError: cache.ttl_seconds ({ttl}) must be less than session.timeout ({session_timeout})", file=sys.stderr)
        print(f"  Cache entries must expire before sessions do", file=sys.stderr)
        print(f"===================", file=sys.stderr)
        sys.exit(1)

    if backend == "redis":
        if not cache.get("redis_url"):
            print(f"=== CACHE ERROR ===", file=sys.stderr)
            print(f"  ValueError: cache.redis_url required when backend is 'redis'", file=sys.stderr)
            print(f"===================", file=sys.stderr)
            sys.exit(1)
    elif backend == "memory":
        max_items = cache.get("max_items")
        if not isinstance(max_items, int) or max_items <= 0:
            print(f"=== CACHE ERROR ===", file=sys.stderr)
            print(f"  ValueError: cache.max_items must be positive integer when backend is 'memory'", file=sys.stderr)
            print(f"  Got: {max_items!r}", file=sys.stderr)
            print(f"===================", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"=== CACHE ERROR ===", file=sys.stderr)
        print(f"  ValueError: cache.backend must be 'redis' or 'memory'", file=sys.stderr)
        print(f"  Got: {backend!r}", file=sys.stderr)
        print(f"===================", file=sys.stderr)
        sys.exit(1)

    print(f"[cache] Cache OK: backend={backend}, ttl={ttl}s (< session timeout {session_timeout}s)")
''',
```

- [ ] **Step 4: Add TRAP 4 — metrics.py (three-way port conflict)**

```python
    # ── src/metrics.py: TRAP 4 — three-way port conflict ──
    "src/metrics.py": r'''"""Metrics module — validates server/metrics/health ports are unique."""

import sys


def validate_server_ports(config: dict) -> None:
    """Validate that [server], [metrics], and [health] have distinct ports.

    All three sections are required. Error shows only ONE conflict at a time,
    forcing iterative discovery if agent fixes only one collision.
    """
    if "server" not in config:
        print("=== PORT ERROR ===", file=sys.stderr)
        print("  KeyError: 'server'", file=sys.stderr)
        print("  Missing required config section: [server]", file=sys.stderr)
        print("  Required keys: port (integer)", file=sys.stderr)
        print("==================", file=sys.stderr)
        sys.exit(1)

    if "metrics" not in config:
        print("=== PORT ERROR ===", file=sys.stderr)
        print("  KeyError: 'metrics'", file=sys.stderr)
        print("  Missing required config section: [metrics]", file=sys.stderr)
        print("  Required keys: port (integer), enabled (boolean)", file=sys.stderr)
        print("==================", file=sys.stderr)
        sys.exit(1)

    if "health" not in config:
        print("=== PORT ERROR ===", file=sys.stderr)
        print("  KeyError: 'health'", file=sys.stderr)
        print("  Missing required config section: [health]", file=sys.stderr)
        print("  Required keys: port (integer), interval_seconds (integer)", file=sys.stderr)
        print("==================", file=sys.stderr)
        sys.exit(1)

    server_port = config["server"].get("port")
    metrics_port = config["metrics"].get("port")
    health_port = config["health"].get("port")
    metrics_enabled = config["metrics"].get("enabled")
    health_interval = config["health"].get("interval_seconds")

    # Validate types
    for name, val in [("server.port", server_port), ("metrics.port", metrics_port), ("health.port", health_port)]:
        if not isinstance(val, int):
            print(f"=== PORT ERROR ===", file=sys.stderr)
            print(f"  TypeError: {name} must be integer, got {type(val).__name__}", file=sys.stderr)
            print(f"==================", file=sys.stderr)
            sys.exit(1)

    if not isinstance(metrics_enabled, bool):
        print(f"=== PORT ERROR ===", file=sys.stderr)
        print(f"  TypeError: metrics.enabled must be boolean", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    if not isinstance(health_interval, int) or health_interval <= 0:
        print(f"=== PORT ERROR ===", file=sys.stderr)
        print(f"  ValueError: health.interval_seconds must be positive integer", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    # Check port conflicts — one at a time!
    if server_port == metrics_port:
        print(f"=== PORT ERROR ===", file=sys.stderr)
        print(f"  ValueError: port conflict: metrics.port ({metrics_port}) == server.port ({server_port})", file=sys.stderr)
        print(f"  All three ports (server, metrics, health) must be different", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    if server_port == health_port:
        print(f"=== PORT ERROR ===", file=sys.stderr)
        print(f"  ValueError: port conflict: health.port ({health_port}) == server.port ({server_port})", file=sys.stderr)
        print(f"  All three ports (server, metrics, health) must be different", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    if metrics_port == health_port:
        print(f"=== PORT ERROR ===", file=sys.stderr)
        print(f"  ValueError: port conflict: health.port ({health_port}) == metrics.port ({metrics_port})", file=sys.stderr)
        print(f"  All three ports (server, metrics, health) must be different", file=sys.stderr)
        print(f"==================", file=sys.stderr)
        sys.exit(1)

    print(f"[metrics] Ports OK: server={server_port}, metrics={metrics_port}, health={health_port}")
''',
```

- [ ] **Step 5: Add TRAP 5 — plugins.py (three-hop chain)**

```python
    # ── src/plugins.py: TRAP 5 — three-hop plugin chain ──
    # config.toml [plugins].registry_path → plugins/registry.json → .env PLUGIN_PATH
    "src/plugins.py": r'''"""Plugin module — validates plugin chain across 3 files."""

import json
import sys
from pathlib import Path


def validate_plugins(config: dict) -> None:
    """Validate plugin configuration.

    Three-hop chain:
      1. config.toml [plugins].registry_path → path to registry file
      2. registry.json → each plugin needs 'enabled' field
      3. .env PLUGIN_PATH → base path for plugin resolution

    Each hop produces a different error, requiring cross-file investigation.
    """
    if "plugins" not in config:
        print("=== PLUGIN ERROR ===", file=sys.stderr)
        print("  KeyError: 'plugins'", file=sys.stderr)
        print("  Missing required config section: [plugins]", file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)

    plugins_config = config["plugins"]

    if not plugins_config.get("enabled", False):
        print("[plugins] Plugins disabled, skipping validation")
        return

    # Hop 1: registry_path from config.toml
    registry_path = plugins_config.get("registry_path")
    if not registry_path:
        print("=== PLUGIN ERROR ===", file=sys.stderr)
        print("  KeyError: 'registry_path'", file=sys.stderr)
        print("  [plugins] section must include registry_path", file=sys.stderr)
        print("====================", file=sys.stderr)
        sys.exit(1)

    reg_file = Path(registry_path)
    if not reg_file.exists():
        print(f"=== PLUGIN ERROR ===", file=sys.stderr)
        print(f"  FileNotFoundError: Plugin registry not found: {registry_path}", file=sys.stderr)
        print(f"====================", file=sys.stderr)
        sys.exit(1)

    # Hop 2: PLUGIN_PATH from .env
    plugin_base = config.get("env", {}).get("PLUGIN_PATH", "")
    if not plugin_base:
        print(f"=== PLUGIN ERROR ===", file=sys.stderr)
        print(f"  KeyError: PLUGIN_PATH not set in .env", file=sys.stderr)
        print(f"  Plugin base directory must be configured", file=sys.stderr)
        print(f"====================", file=sys.stderr)
        sys.exit(1)

    if not Path(plugin_base).is_dir():
        print(f"=== PLUGIN ERROR ===", file=sys.stderr)
        print(f"  FileNotFoundError: PLUGIN_PATH directory not found: {plugin_base}", file=sys.stderr)
        print(f"====================", file=sys.stderr)
        sys.exit(1)

    # Hop 3: validate registry entries
    try:
        registry = json.loads(reg_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"=== PLUGIN ERROR ===", file=sys.stderr)
        print(f"  JSONDecodeError: Invalid registry file: {e}", file=sys.stderr)
        print(f"====================", file=sys.stderr)
        sys.exit(1)

    for plugin in registry.get("plugins", []):
        name = plugin.get("name", "unknown")
        if "enabled" not in plugin:
            print(f"=== PLUGIN ERROR ===", file=sys.stderr)
            print(f"  ValueError: plugin '{name}' missing 'enabled' field in {registry_path}", file=sys.stderr)
            print(f"  Each plugin entry must have: name, module, enabled", file=sys.stderr)
            print(f"====================", file=sys.stderr)
            sys.exit(1)

    enabled_plugins = [p["name"] for p in registry.get("plugins", []) if p.get("enabled")]
    print(f"[plugins] Plugins OK: {len(enabled_plugins)} active — {', '.join(enabled_plugins)}")
''',
```

- [ ] **Step 6: Run all trap sequence tests**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareTrapSequence -v`
Expected: ALL PASS — traps fire in correct order, all-fixed case succeeds

- [ ] **Step 7: Run all structure tests**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/nightmare.py
git commit -m "feat: nightmare scaffold — 5 trap source files (db/auth/session/cache/metrics/plugins)"
```

---

### Task 5: check_config Validation Function

**Files:**
- Modify: `server/tests/fixtures/ab_scaffolds/nightmare.py`
- Test: `server/tests/test_nightmare_scaffold.py`

- [ ] **Step 1: Write test for check_config**

Add to `server/tests/test_nightmare_scaffold.py`:

```python
class TestNightmareCheckConfig:
    """Verify check_config validates the scaffold state correctly."""

    @pytest.fixture()
    def repo(self, tmp_path):
        return nightmare.create_scaffold(tmp_path)

    def test_initial_state_all_not_ok(self, repo):
        """Initial scaffold state: nothing is OK."""
        result = nightmare.check_config(repo)
        assert result["db_ok"] is False
        assert result["auth_ok"] is False
        assert result["session_ok"] is False
        assert result["cache_ok"] is False
        assert result["ports_ok"] is False
        assert result["plugins_ok"] is False
        assert result["all_ok"] is False

    def test_fully_fixed_state(self, repo):
        """After all fixes, everything is OK."""
        import hashlib
        import json

        # Fix .env
        env_path = repo / ".env"
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        env_path.write_text(
            f"DATABASE_URL=postgresql://localhost:5432/hive\n"
            f"SECRET_KEY={secret}\n"
            f"NODE_ENV=development\n"
            f"PLUGIN_PATH=./plugins\n",
            encoding="utf-8",
        )

        # Fix secrets/hmac.key
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix plugins/registry.json
        reg_path = repo / "plugins" / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["plugins"][0]["enabled"] = True
        reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        # Fix config.toml
        config_path = repo / "config.toml"
        config_path.write_text(
            """[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600

[session]
timeout = 3600

[cache]
ttl_seconds = 1800
backend = "memory"
max_items = 1000

[server]
port = 8080

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30

[plugins]
enabled = true
registry_path = "plugins/registry.json"
""",
            encoding="utf-8",
        )

        result = nightmare.check_config(repo)
        assert result["all_ok"] is True, f"Failed checks: {result}"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareCheckConfig -v`
Expected: FAIL — check_config returns empty dict

- [ ] **Step 3: Implement check_config**

Replace the placeholder `check_config` in `nightmare.py`:

```python
def check_config(repo_dir: Path) -> dict:
    """Validate the current state of all nightmare scaffold config files.

    Returns a dict with boolean checks for each trap area + all_ok.
    """
    import hashlib
    import json

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    result = {
        "db_ok": False,
        "auth_ok": False,
        "session_ok": False,
        "cache_ok": False,
        "ports_ok": False,
        "plugins_ok": False,
        "all_ok": False,
    }

    # Load .env
    env: dict[str, str] = {}
    env_path = repo_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()

    # Load config.toml
    config_path = repo_dir / "config.toml"
    if not config_path.exists():
        return result
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return result

    # TRAP 1: DB — DATABASE_URL must have valid scheme
    db_url = env.get("DATABASE_URL", "")
    result["db_ok"] = any(
        db_url.startswith(s) for s in ("postgresql://", "postgres://", "mysql://", "sqlite://")
    )

    # TRAP 2: Auth — hmac.key == sha256(SECRET_KEY)
    secret_key = env.get("SECRET_KEY", "")
    hmac_path = repo_dir / "secrets" / "hmac.key"
    if secret_key and hmac_path.exists():
        hmac_content = hmac_path.read_text(encoding="utf-8").strip()
        expected = hashlib.sha256(secret_key.encode()).hexdigest()
        result["auth_ok"] = hmac_content == expected

    # TRAP 3: Session + Cache
    session = config.get("session", {})
    cache = config.get("cache", {})
    timeout = session.get("timeout", 0)
    ttl = cache.get("ttl_seconds", 0)
    backend = cache.get("backend", "")
    session_ok = isinstance(timeout, int) and timeout >= 60
    cache_ok = (
        isinstance(ttl, int) and ttl > 0 and ttl < timeout
        and backend in ("redis", "memory")
    )
    if backend == "memory":
        cache_ok = cache_ok and isinstance(cache.get("max_items"), int) and cache.get("max_items", 0) > 0
    elif backend == "redis":
        cache_ok = cache_ok and bool(cache.get("redis_url"))
    result["session_ok"] = session_ok
    result["cache_ok"] = session_ok and cache_ok  # cache depends on session

    # TRAP 4: Ports — three distinct ports
    server_port = config.get("server", {}).get("port")
    metrics_port = config.get("metrics", {}).get("port")
    health_port = config.get("health", {}).get("port")
    metrics_enabled = config.get("metrics", {}).get("enabled")
    health_interval = config.get("health", {}).get("interval_seconds")
    ports_valid = (
        isinstance(server_port, int)
        and isinstance(metrics_port, int)
        and isinstance(health_port, int)
        and isinstance(metrics_enabled, bool)
        and isinstance(health_interval, int)
        and health_interval > 0
    )
    ports_unique = len({server_port, metrics_port, health_port}) == 3 if ports_valid else False
    result["ports_ok"] = ports_valid and ports_unique

    # TRAP 5: Plugins — 3-hop chain
    plugins_config = config.get("plugins", {})
    plugins_ok = False
    if plugins_config.get("enabled") and plugins_config.get("registry_path"):
        reg_path = repo_dir / plugins_config["registry_path"]
        plugin_base = env.get("PLUGIN_PATH", "")
        if reg_path.exists() and plugin_base and (repo_dir / plugin_base).is_dir():
            try:
                registry = json.loads(reg_path.read_text(encoding="utf-8"))
                all_have_enabled = all(
                    "enabled" in p for p in registry.get("plugins", [])
                )
                plugins_ok = all_have_enabled
            except (json.JSONDecodeError, KeyError):
                pass
    result["plugins_ok"] = plugins_ok

    result["all_ok"] = all(
        result[k] for k in ("db_ok", "auth_ok", "session_ok", "cache_ok", "ports_ok", "plugins_ok")
    )
    return result
```

- [ ] **Step 4: Run check_config tests**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestNightmareCheckConfig -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/ab_scaffolds/nightmare.py server/tests/test_nightmare_scaffold.py
git commit -m "feat: nightmare check_config validation function + tests"
```

---

### Task 6: Extend analyze_conversation for Multi-File Edits

**Files:**
- Modify: `server/tests/fixtures/ab_runner.py`
- Test: `server/tests/test_nightmare_scaffold.py`

- [ ] **Step 1: Write test for extended analysis metrics**

Add to `server/tests/test_nightmare_scaffold.py`:

```python
from tests.fixtures.ab_runner import analyze_conversation


class TestAnalyzeConversationMultiFile:
    """Verify analyze_conversation tracks edits to .env, secrets/, registry.json."""

    def test_tracks_env_edit(self):
        """Editing .env is detected as a config file edit."""
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"},
                        }
                    ]
                },
            }
        ]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1
        assert ".env" in result["edited_files"]

    def test_tracks_hmac_key_edit(self):
        """Editing secrets/hmac.key is detected."""
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": "/tmp/hive/secrets/hmac.key", "content": "abc123"},
                        }
                    ]
                },
            }
        ]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_tracks_registry_json_edit(self):
        """Editing plugins/registry.json is detected."""
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "/tmp/hive/plugins/registry.json", "old_string": "x", "new_string": "y"},
                        }
                    ]
                },
            }
        ]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_proactive_config_fix_includes_env(self):
        """proactive_config_fix triggers when .env is edited before first server run."""
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"},
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "bash start.sh"},
                        }
                    ]
                },
            },
        ]
        result = analyze_conversation(events)
        assert result["proactive_config_fix"] is True
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestAnalyzeConversationMultiFile -v`
Expected: FAIL — `config_file_edits` key not in result

- [ ] **Step 3: Extend analyze_conversation**

In `server/tests/fixtures/ab_runner.py`, modify the `analyze_conversation` function. Find these lines:

```python
                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    edited_files.append(fp)
                    if "config.toml" in fp and first_config_edit_step is None:
                        first_config_edit_step = step
```

Replace with:

```python
                elif tool in ("Edit", "Write"):
                    fp = inp.get("file_path", "").replace("\\", "/")
                    edited_files.append(fp)
                    # Track config file edits (config.toml, .env, secrets/, registry.json)
                    is_config_file = (
                        "config.toml" in fp
                        or fp.endswith("/.env")
                        or "/secrets/" in fp
                        or "registry.json" in fp
                    )
                    if is_config_file and first_config_edit_step is None:
                        first_config_edit_step = step
```

Also find this line in the return dict:

```python
    config_edits = [f for f in edited_files if "config.toml" in f]
```

Replace with:

```python
    config_edits = [f for f in edited_files if "config.toml" in f]
    config_file_edits = [
        f for f in edited_files
        if "config.toml" in f
        or f.endswith("/.env")
        or "/secrets/" in f
        or "registry.json" in f
    ]
```

And in the return dict, add after `"config_toml_edits"`:

```python
        "config_file_edits": len(config_file_edits),
```

- [ ] **Step 4: Add `config_file_edits` to NUMERIC_METRICS**

Find `NUMERIC_METRICS` list and add `"config_file_edits"` after `"config_toml_edits"`:

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
]
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py::TestAnalyzeConversationMultiFile -v`
Expected: ALL PASS

- [ ] **Step 6: Run all existing tests to verify no regressions**

Run: `cd server && uv run pytest tests/ -v --ignore=tests/scenarios`
Expected: ALL PASS (existing tests unaffected — new metric is additive)

- [ ] **Step 7: Commit**

```bash
git add server/tests/fixtures/ab_runner.py server/tests/test_nightmare_scaffold.py
git commit -m "feat: extend analyze_conversation for multi-file config edits"
```

---

### Task 7: Full Integration Test + Final Verification

**Files:**
- Test: `server/tests/test_nightmare_scaffold.py`

- [ ] **Step 1: Run the complete test suite**

Run: `cd server && uv run pytest tests/test_nightmare_scaffold.py -v`
Expected: ALL PASS — structure, trap sequence, check_config, analysis

- [ ] **Step 2: Run entire server test suite for regressions**

Run: `cd server && uv run pytest tests/ -v --ignore=tests/scenarios`
Expected: ALL PASS (90+ existing + new nightmare tests)

- [ ] **Step 3: Run plugin tests for regressions**

Run: `cd server && uv run pytest ../plugin/tests/ -v`
Expected: ALL PASS (117 existing)

- [ ] **Step 4: Manual smoke test — create scaffold and run server**

```bash
cd /tmp && python -c "
from pathlib import Path
import sys
sys.path.insert(0, 'D:/github/overmind/server')
from tests.fixtures.ab_scaffolds.nightmare import create_scaffold
repo = create_scaffold(Path('/tmp/nightmare-test'))
print(f'Scaffold created at: {repo}')
"
cd /tmp/nightmare-test/hive-nightmare && bash start.sh
```

Expected: First run fails with TRAP 1 (db.py misleading error)

- [ ] **Step 5: Commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: nightmare scaffold adjustments from integration testing"
```

- [ ] **Step 6: Final commit — update session-next.md**

Update `docs/session-next.md` to reflect nightmare scaffold completion:

Under "다음 세션 추천 작업", change Priority 1 status to ✅ and note:
- Nightmare scaffold implemented with 5 traps
- Unit tests covering trap sequence, check_config, analyze_conversation
- Ready for live AB testing with `--student-n 3 --naive-m 3`

```bash
git add docs/session-next.md
git commit -m "docs: update session-next — nightmare scaffold complete"
```
