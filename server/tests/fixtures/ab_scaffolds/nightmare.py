"""Nightmare Config Scaffold: multi-file config with misleading errors and cross-file traps.

Scenario:
  A Python server reads config.toml + .env + secrets/ + plugins/registry.json.
  Six sequential traps, each requiring deeper investigation:

  TRAP 1: Misleading error — db.py prints fake traceback pointing at itself,
          but the fix is changing DATABASE_URL in .env.
  TRAP 2: Cross-file SHA256 — auth.py checks that secrets/hmac.key ==
          sha256(SECRET_KEY from .env). Error doesn't reveal the relationship.
  TRAP 3a: Missing [session] section with timeout >= 60.
  TRAP 3b: Mutual dependency — cache.ttl_seconds must be < session.timeout.
  TRAP 4: Three-way port conflict — [server], [metrics], [health] ports must differ.
  TRAP 5: Three-hop plugin chain — config.toml registry_path → .env PLUGIN_PATH →
          registry.json enabled field.
"""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-nightmare"
REPO_ID = "github.com/test/hive-nightmare"
MAX_TURNS = 40

SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may edit config.toml, .env, secrets/hmac.key, plugins/registry.json. "
    "Do NOT modify files under src/ or create new files."
)

# Pioneer gets a smarter prompt that guides systematic investigation.
# The VALUE is that this structured approach (read source → map dependencies →
# fix holistically) gets propagated to Students via Overmind, while Naives
# are left doing blind trial-and-error with SHARED_PROMPT.
PIONEER_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to see the first error. "
    "IMPORTANT: Before fixing anything, read the source files under src/ to understand "
    "the full validation chain and dependencies between config files. "
    "Map out which config values depend on each other across config.toml, .env, "
    "secrets/hmac.key, and plugins/registry.json. "
    "Then fix ALL issues at once rather than one at a time. "
    "You may edit config.toml, .env, secrets/hmac.key, plugins/registry.json. "
    "Do NOT modify files under src/ or create new files."
)

SCAFFOLD_FILES: dict[str, str] = {
    # ── Project rules ──
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- You may edit: config.toml, .env, secrets/hmac.key, plugins/registry.json
- Do NOT modify files under src/ or create new files.
""",
    # ── Startup script ──
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python src/server.py 2>&1
""",
    # ── Config: deliberately incomplete ──
    "config.toml": """# Hive Server Configuration

[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600
""",
    # ── Environment: placeholder values ──
    ".env": """DATABASE_URL=changeme://localhost/db
SECRET_KEY=dev-placeholder-key
NODE_ENV=development
""",
    # ── Secret: zero-filled HMAC key ──
    "secrets/hmac.key": "0000000000000000000000000000000000000000000000000000000000000000",
    # ── Plugin registry: missing enabled field ──
    "plugins/registry.json": '{"plugins": [{"name": "audit-log", "module": "audit"}]}',
    # ── Source: config loader ──
    "src/config_loader.py": r'''"""Config loader — merges config.toml + .env + secrets/ into one dict."""

import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11 fallback


def _parse_env(env_path: Path) -> dict[str, str]:
    """Simple .env parser: KEY=VALUE lines, ignoring comments and blanks."""
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


def _load_secrets(secrets_dir: Path) -> dict[str, str]:
    """Load all files in secrets/ dir as key-value pairs (filename sans ext -> content)."""
    secrets = {}
    if not secrets_dir.is_dir():
        return secrets
    for f in secrets_dir.iterdir():
        if f.is_file():
            secrets[f.stem] = f.read_text(encoding="utf-8").strip()
    return secrets


def load_config() -> dict:
    """Load and merge all configuration sources."""
    config_path = Path("config.toml")
    if not config_path.exists():
        print("FATAL: config.toml not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    config["env"] = _parse_env(Path(".env"))
    config["secrets"] = _load_secrets(Path("secrets"))
    return config
''',
    # ── Source: main entry point ──
    "src/server.py": r'''#!/usr/bin/env python3
"""Hive Server — validates configuration then starts."""

import sys
from config_loader import load_config
from db import validate_db
from auth import validate_auth
from session import validate_session
from cache import validate_cache
from metrics import validate_server_ports
from plugins import validate_plugins


def main():
    config = load_config()

    validate_db(config)
    validate_auth(config)
    validate_session(config)
    validate_cache(config)
    validate_server_ports(config)
    validate_plugins(config)

    print("[Hive] Configuration validated successfully")


if __name__ == "__main__":
    # Ensure src/ is on the path for sibling imports
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
''',
    # ── TRAP 1: Misleading database error ──
    "src/db.py": r'''"""Database validator — TRAP 1: misleading error points at db.py, fix is in .env."""

import sys


def validate_db(config: dict) -> None:
    url = config.get("env", {}).get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set in environment", file=sys.stderr)
        sys.exit(1)

    scheme = url.split("://")[0] if "://" in url else ""
    valid_schemes = ("postgresql", "postgres", "mysql", "sqlite")

    if scheme not in valid_schemes:
        # Deliberately misleading: traceback points at db.py, not .env
        print("Traceback (most recent call last):", file=sys.stderr)
        print('  File "src/db.py", line 42, in parse_url', file=sys.stderr)
        print("    scheme, rest = url.split('://', 1)", file=sys.stderr)
        print(f'  File "src/db.py", line 58, in validate_scheme', file=sys.stderr)
        print(f'    raise ConnectionError(scheme)', file=sys.stderr)
        print(
            f"ConnectionError: Failed to parse database URL scheme: '{scheme}'",
            file=sys.stderr,
        )
        print(
            "  Expected one of: postgresql, postgres, mysql, sqlite",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[db] Database OK: {scheme}://***", file=sys.stderr)
''',
    # ── TRAP 2: Cross-file SHA256 relationship ──
    "src/auth.py": r'''"""Auth validator — TRAP 2: HMAC key must be SHA256 of SECRET_KEY."""

import hashlib
import sys


def validate_auth(config: dict) -> None:
    secret_key = config.get("env", {}).get("SECRET_KEY", "")
    if not secret_key:
        print("ERROR: SECRET_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    hmac_content = config.get("secrets", {}).get("hmac", "")
    if not hmac_content:
        print("ERROR: secrets/hmac.key not found or empty", file=sys.stderr)
        sys.exit(1)

    expected = hashlib.sha256(secret_key.encode()).hexdigest()

    if hmac_content != expected:
        print(
            "HMAC key verification failed: key file digest does not match SECRET_KEY",
            file=sys.stderr,
        )
        print(
            f"  key file length: {len(hmac_content)}, expected length: {len(expected)}",
            file=sys.stderr,
        )
        sys.exit(1)

    algorithm = config.get("auth", {}).get("algorithm", "HS256")
    print(f"[auth] Auth OK: algorithm={algorithm}", file=sys.stderr)
''',
    # ── TRAP 3a: Missing session config ──
    "src/session.py": r'''"""Session validator — TRAP 3a: requires [session] with timeout >= 60."""

import sys


def validate_session(config: dict) -> None:
    if "session" not in config:
        print("KeyError: 'session'", file=sys.stderr)
        print("  Missing required configuration section: [session]", file=sys.stderr)
        sys.exit(1)

    session = config["session"]
    timeout = session.get("timeout")

    if not isinstance(timeout, int) or timeout < 60:
        print(
            f"ValueError: session.timeout must be an integer >= 60, got: {timeout!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[session] Session OK: timeout={timeout}s", file=sys.stderr)
''',
    # ── TRAP 3b: Cache/session mutual dependency ──
    "src/cache.py": r'''"""Cache validator — TRAP 3b: cache.ttl_seconds must be < session.timeout."""

import sys


def validate_cache(config: dict) -> None:
    if "cache" not in config:
        print("KeyError: 'cache'", file=sys.stderr)
        print("  Missing required configuration section: [cache]", file=sys.stderr)
        sys.exit(1)

    cache = config["cache"]
    session = config.get("session", {})

    ttl = cache.get("ttl_seconds")
    session_timeout = session.get("timeout", 0)

    if not isinstance(ttl, int) or ttl <= 0:
        print(
            f"ValueError: cache.ttl_seconds must be a positive integer, got: {ttl!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if ttl >= session_timeout:
        print(
            f"ValueError: cache.ttl_seconds ({ttl}) must be strictly less than session.timeout ({session_timeout})",
            file=sys.stderr,
        )
        sys.exit(1)

    backend = cache.get("backend", "")
    if backend == "redis":
        if not cache.get("redis_url"):
            print("ValueError: cache.backend is 'redis' but redis_url is not set", file=sys.stderr)
            sys.exit(1)
    elif backend == "memory":
        max_items = cache.get("max_items")
        if not isinstance(max_items, int) or max_items <= 0:
            print(
                f"ValueError: cache.backend is 'memory' but max_items is invalid: {max_items!r}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            f"ValueError: cache.backend must be 'redis' or 'memory', got: {backend!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[cache] Cache OK: backend={backend}, ttl={ttl}s", file=sys.stderr)
''',
    # ── TRAP 4: Three-way port conflict ──
    "src/metrics.py": r'''"""Metrics/health validator — TRAP 4: three ports must all differ."""

import sys


def validate_server_ports(config: dict) -> None:
    for section in ("server", "metrics", "health"):
        if section not in config:
            print(f"KeyError: '{section}'", file=sys.stderr)
            print(
                f"  Missing required configuration section: [{section}]",
                file=sys.stderr,
            )
            sys.exit(1)

    server_port = config["server"].get("port")
    metrics_port = config["metrics"].get("port")
    health_port = config["health"].get("port")

    for name, val in [("server.port", server_port), ("metrics.port", metrics_port), ("health.port", health_port)]:
        if not isinstance(val, int):
            print(f"TypeError: {name} must be an integer, got: {val!r}", file=sys.stderr)
            sys.exit(1)

    # Check enabled flag on metrics
    if not isinstance(config["metrics"].get("enabled"), bool):
        print("TypeError: metrics.enabled must be a boolean", file=sys.stderr)
        sys.exit(1)

    # Check interval on health
    interval = config["health"].get("interval_seconds")
    if not isinstance(interval, int) or interval <= 0:
        print(
            f"ValueError: health.interval_seconds must be a positive integer, got: {interval!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Only report ONE conflict at a time
    ports = {"server": server_port, "metrics": metrics_port, "health": health_port}
    names = list(ports.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if ports[names[i]] == ports[names[j]]:
                print(
                    f"AddressError: port conflict — [{names[i]}].port and [{names[j]}].port are both {ports[names[i]]}",
                    file=sys.stderr,
                )
                sys.exit(1)

    print(
        f"[metrics] Ports OK: server={server_port}, metrics={metrics_port}, health={health_port}",
        file=sys.stderr,
    )
''',
    # ── TRAP 5: Three-hop plugin chain ──
    "src/plugins.py": r'''"""Plugin validator — TRAP 5: three-hop chain (config → env → registry)."""

import json
import sys
from pathlib import Path


def validate_plugins(config: dict) -> None:
    # Hop 1: config.toml [plugins].registry_path must point to registry file
    if "plugins" not in config:
        print("KeyError: 'plugins'", file=sys.stderr)
        print("  Missing required configuration section: [plugins]", file=sys.stderr)
        sys.exit(1)

    registry_path_str = config["plugins"].get("registry_path", "")
    if not registry_path_str:
        print(
            "ValueError: [plugins].registry_path is not set in config.toml",
            file=sys.stderr,
        )
        sys.exit(1)

    registry_path = Path(registry_path_str)
    if not registry_path.exists():
        print(
            f"FileNotFoundError: plugin registry not found at '{registry_path}'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Hop 2: .env PLUGIN_PATH must be set (base directory for plugin modules)
    plugin_path = config.get("env", {}).get("PLUGIN_PATH", "")
    if not plugin_path:
        print(
            "ValueError: PLUGIN_PATH environment variable is not set",
            file=sys.stderr,
        )
        sys.exit(1)

    # Hop 3: registry.json — each plugin must have 'enabled' field
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error reading plugin registry: {exc}", file=sys.stderr)
        sys.exit(1)

    plugins = registry.get("plugins", [])
    for plugin in plugins:
        if "enabled" not in plugin:
            print(
                f"ValueError: plugin '{plugin.get('name', '?')}' is missing required 'enabled' field in registry",
                file=sys.stderr,
            )
            sys.exit(1)

    enabled_count = sum(1 for p in plugins if p.get("enabled"))
    print(
        f"[plugins] Plugins OK: {enabled_count}/{len(plugins)} enabled, path={plugin_path}",
        file=sys.stderr,
    )
''',
}


def create_scaffold(base_dir: Path) -> Path:
    """Create nightmare config scaffold as a git repo."""
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
        ["git", "commit", "-m", "initial: Hive nightmare scaffold"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
        env=git_env,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/test/hive-nightmare.git",
        ],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    return repo_dir


def check_config(repo_dir: Path) -> dict:
    """Validate the current state of all nightmare scaffold config files.

    Returns a dict with boolean checks for each trap area plus an ``all_ok`` flag.
    """
    import hashlib
    import json

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    # -- Load .env --
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

    # -- Load config.toml --
    config: dict = {}
    config_path = repo_dir / "config.toml"
    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # -- db_ok: DATABASE_URL has valid scheme --
    db_url = env.get("DATABASE_URL", "")
    scheme = db_url.split("://")[0] if "://" in db_url else ""
    db_ok = scheme in ("postgresql", "postgres", "mysql", "sqlite")

    # -- auth_ok: hmac.key == sha256(SECRET_KEY) --
    secret_key = env.get("SECRET_KEY", "")
    hmac_path = repo_dir / "secrets" / "hmac.key"
    hmac_content = hmac_path.read_text(encoding="utf-8").strip() if hmac_path.exists() else ""
    if secret_key and hmac_content:
        expected_hmac = hashlib.sha256(secret_key.encode()).hexdigest()
        auth_ok = hmac_content == expected_hmac
    else:
        auth_ok = False

    # -- session_ok: [session] exists with timeout >= 60 --
    session = config.get("session", {})
    session_timeout = session.get("timeout")
    session_ok = isinstance(session_timeout, int) and session_timeout >= 60

    # -- cache_ok: depends on session_ok, ttl > 0, ttl < timeout, valid backend --
    cache = config.get("cache", {})
    ttl = cache.get("ttl_seconds")
    backend = cache.get("backend", "")
    cache_ok = False
    if session_ok and isinstance(ttl, int) and ttl > 0 and ttl < session_timeout:
        if backend == "redis":
            cache_ok = bool(cache.get("redis_url"))
        elif backend == "memory":
            max_items = cache.get("max_items")
            cache_ok = isinstance(max_items, int) and max_items > 0
        # else: cache_ok stays False

    # -- ports_ok: server/metrics/health all have int ports, all different, extra checks --
    ports_ok = False
    if all(s in config for s in ("server", "metrics", "health")):
        server_port = config["server"].get("port")
        metrics_port = config["metrics"].get("port")
        health_port = config["health"].get("port")
        metrics_enabled = config["metrics"].get("enabled")
        health_interval = config["health"].get("interval_seconds")

        all_int = all(isinstance(p, int) for p in (server_port, metrics_port, health_port))
        all_different = len({server_port, metrics_port, health_port}) == 3 if all_int else False
        enabled_bool = isinstance(metrics_enabled, bool)
        interval_valid = isinstance(health_interval, int) and health_interval > 0

        ports_ok = all_int and all_different and enabled_bool and interval_valid

    # -- plugins_ok: [plugins].enabled, registry_path exists, PLUGIN_PATH, registry entries have 'enabled' --
    plugins_ok = False
    plugins_cfg = config.get("plugins", {})
    if plugins_cfg.get("enabled") is True:
        registry_rel = plugins_cfg.get("registry_path", "")
        registry_abs = repo_dir / registry_rel if registry_rel else None
        plugin_path_env = env.get("PLUGIN_PATH", "")
        plugin_dir = repo_dir / plugin_path_env if plugin_path_env else None

        if (
            registry_abs
            and registry_abs.exists()
            and plugin_dir
            and plugin_dir.exists()
        ):
            try:
                registry = json.loads(registry_abs.read_text(encoding="utf-8"))
                entries = registry.get("plugins", [])
                if entries and all("enabled" in p for p in entries):
                    plugins_ok = True
            except (json.JSONDecodeError, OSError):
                pass

    all_ok = db_ok and auth_ok and session_ok and cache_ok and ports_ok and plugins_ok

    return {
        "db_ok": db_ok,
        "auth_ok": auth_ok,
        "session_ok": session_ok,
        "cache_ok": cache_ok,
        "ports_ok": ports_ok,
        "plugins_ok": plugins_ok,
        "all_ok": all_ok,
    }
