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
"""Hive Server — validates modules based on current git branch."""

import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config


def get_branch() -> str:
    """Detect current git branch."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else "main"
    except Exception:
        return "main"


def main():
    config = load_config()
    branch = get_branch()

    if branch == "feat/auth" or branch == "main":
        from auth import validate_auth
        validate_auth(config)

    if branch == "feat/api" or branch == "main":
        from api import validate_api
        validate_api(config)

    # Port conflict only matters when both modules are configured
    if "auth" in config and "api" in config:
        from ports import validate_ports
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
        ["git", "init", "-b", "main"], cwd=str(repo_dir), capture_output=True, check=True
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
    auth_token_ok = len(auth_token) >= 1

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

    # token separation check
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
