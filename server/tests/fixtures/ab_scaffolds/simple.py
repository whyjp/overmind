"""Simple A/B scaffold: Python server + config.toml with prescriptive errors.

Scenario:
  A Python HTTP server reads config.toml for startup configuration.
  config.toml is deliberately incomplete — missing required fields.
  The server prints error messages showing only symptoms (not solutions).

  Config traps (not in config.toml):
    1. [server] section with port + host
    2. [security] section with api_secret (>= 32 chars)
    3. [app] section with env ("development" or "production")
"""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-ab"
REPO_ID = "github.com/test/hive-ab"
MAX_TURNS = 20

SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT modify files under src/ or docs/.
""",
    "config.toml": """# Hive Server Configuration
# Start the server with: bash start.sh

[database]
url = "postgres://localhost:5432/hive"

[auth]
jwt_secret = "my-jwt-secret-key-here"
""",
    "docs/config-schema.md": """# Hive Server Configuration Schema

All configuration is in `config.toml` at the project root.

## Required Sections

### [server]
| Key  | Type    | Required | Description              |
|------|---------|----------|--------------------------|
| port | integer | yes      | HTTP listen port         |
| host | string  | yes      | Bind address             |

### [security]
| Key        | Type   | Required | Constraints     | Description        |
|------------|--------|----------|-----------------|--------------------|
| api_secret | string | yes      | min 32 chars    | API signing secret |

### [app]
| Key | Type   | Required | Valid values                  | Description     |
|-----|--------|----------|-------------------------------|-----------------|
| env | string | yes      | "development", "production"   | Runtime mode    |

## Example

```toml
[database]
url = "postgres://localhost:5432/hive"

[auth]
jwt_secret = "my-jwt-secret"

[server]
port = 3000
host = "0.0.0.0"

[security]
api_secret = "a-very-long-secret-string-that-is-at-least-32-characters"

[app]
env = "development"
```
""",
    "start.sh": """#!/usr/bin/env bash
# Hive Server startup script
# Usage: bash start.sh
set -e
cd "$(dirname "$0")"
echo "[start.sh] Starting Hive server..."
python src/server.py 2>&1
""",
    "src/server.py": r'''#!/usr/bin/env python3
"""Hive API Server — validates config.toml then starts HTTP server."""

import http.server
import json
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11 fallback


def load_config() -> dict:
    config_path = Path("config.toml")
    if not config_path.exists():
        print("=== CONFIGURATION ERROR ===", file=sys.stderr)
        print("config.toml not found.", file=sys.stderr)
        print("Create config.toml in the project root.", file=sys.stderr)
        print("===========================", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def validate_config(config: dict) -> list[str]:
    """Validate config — errors show SYMPTOMS only, not solutions."""
    errors = []

    # --- Check 1: [server] section ---
    if "server" not in config:
        errors.append('Missing required configuration section: [server]')
    else:
        server = config["server"]
        if "port" not in server:
            errors.append('Missing required key "port" in [server]')
        elif not isinstance(server["port"], int):
            errors.append(f'Invalid type for [server].port: expected integer, got {type(server["port"]).__name__}')
        if "host" not in server:
            errors.append('Missing required key "host" in [server]')

    # --- Check 2: [security] section ---
    if "security" not in config:
        errors.append('Missing required configuration section: [security]')
    else:
        sec = config["security"]
        secret = sec.get("api_secret", "")
        if not secret:
            errors.append('Missing required key "api_secret" in [security]')
        elif len(str(secret)) < 32:
            errors.append(f'Validation failed: [security].api_secret is too short (length {len(str(secret))}, minimum 32)')

    # --- Check 3: [app] section ---
    if "app" not in config:
        errors.append('Missing required configuration section: [app]')
    else:
        env = config["app"].get("env", "")
        if env not in ("development", "production"):
            errors.append(f'Invalid value for [app].env: "{env}" (must be "development" or "production")')

    return errors


def main():
    config = load_config()
    errors = validate_config(config)

    if errors:
        # Only show the FIRST error — forces iterative discovery
        print("", file=sys.stderr)
        print("=== STARTUP FAILED ===", file=sys.stderr)
        print(f"  ERROR: {errors[0]}", file=sys.stderr)
        if len(errors) > 1:
            print(f"  ({len(errors) - 1} more error(s) may appear after fixing this one)", file=sys.stderr)
        print("======================", file=sys.stderr)
        sys.exit(1)

    # All checks passed — start server
    port = config["server"]["port"]
    host = config["server"].get("host", "0.0.0.0")
    env = config["app"]["env"]

    print(f"[Hive] Configuration OK")
    print(f"[Hive] port={port}, host={host}, env={env}")
    print(f"[Hive] api_secret length={len(config['security']['api_secret'])}")
    print(f"[Hive] Server starting on {host}:{port}...")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok", "port": port, "env": env,
            }).encode())

        def log_message(self, format, *args):
            pass  # suppress request logs

    server = http.server.HTTPServer((host, port), Handler)
    print(f"[Hive] Server running on http://{host}:{port}")
    # For testing: print success and exit immediately (don't actually serve)
    print(f"[Hive] Server ready. Exiting (test mode).")


if __name__ == "__main__":
    main()
''',
}


def create_scaffold(base_dir: Path) -> Path:
    """Create config.toml-based scaffold as a git repo."""
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
        ["git", "commit", "-m", "initial: Hive server scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-ab.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


def check_config_toml(repo_dir: Path) -> dict:
    """Validate final config.toml state."""
    path = repo_dir / "config.toml"
    if not path.exists():
        return {"exists": False}

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    content = path.read_text(encoding="utf-8")
    try:
        config = tomllib.loads(content)
    except Exception:
        return {"exists": True, "parse_error": True}

    server = config.get("server", {})
    security = config.get("security", {})
    app = config.get("app", {})

    port_ok = isinstance(server.get("port"), int)
    host_ok = "host" in server
    secret = str(security.get("api_secret", ""))
    secret_ok = len(secret) >= 32
    env_val = app.get("env", "")
    env_ok = env_val in ("development", "production")

    return {
        "exists": True,
        "has_server_section": "server" in config,
        "port_ok": port_ok,
        "port_value": server.get("port"),
        "host_ok": host_ok,
        "has_security_section": "security" in config,
        "api_secret_ok": secret_ok,
        "api_secret_len": len(secret),
        "has_app_section": "app" in config,
        "env_ok": env_ok,
        "env_value": env_val,
        "all_ok": all([port_ok, host_ok, secret_ok, env_ok]),
    }
