# server/tests/fixtures/ab_scaffolds/multistage.py
"""Scaffold data for the A/B Multi-Stage Failure Cascade scenario (Node.js)."""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-multi"
REPO_ID = "github.com/test/hive-multistage"
MAX_TURNS = 30

# Prompt tells agent to run start.sh first (correct — server might already work).
# After failure, Student should use Overmind FIXES to fix ALL issues at once.
SHARED_PROMPT = (
    "Get the Hive server running. "
    "Run `bash start.sh` to start it. "
    "If it fails, figure out what's wrong and fix config.toml, then retry. "
    "You may only edit config.toml — do not modify any .js or .json files."
)

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Server

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT create new files. Do NOT modify files under src/ or any .js/.json files.
- The start script handles npm install automatically.
""",
    # ── config.toml: deliberately incomplete — has [database] and [auth] but
    # is missing [server], [session], [routes], [middleware], [logging];
    # auth.key_file points to wrong path. Agent must discover each gap by
    # running the app and reading the crash source. ──
    "config.toml": """# Hive Server Configuration

[database]
url = "postgres://localhost:5432/hive"

[auth]
key_file = "./keys/hmac.key"
algorithm = "HS256"
""",
    # ── The actual HMAC key file lives at project root, not ./keys/ ──
    "hmac.key": "4a7f3c9e1b2d8a0f5e6c7d3b9a1f0e2c4d5b6a8f7e3c1d9b0a2f4e6c8d7b5a3f",
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "[start.sh] Installing dependencies..."
npm install 2>&1
echo "[start.sh] Starting Hive server..."
node src/server.js 2>&1
""",
    "package.json": """{
  "name": "hive-server",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "node src/server.js"
  },
  "dependencies": {
    "@iarna/toml": "2.2.5",
    "assert": "2.1.0"
  }
}
""",
    # ── Main entry point: requires each init module sequentially ──
    "src/server.js": """'use strict';
const fs = require('fs');
const toml = require('@iarna/toml');

const configRaw = fs.readFileSync('config.toml', 'utf8');
const config = toml.parse(configRaw);

// Phase 1: network binding + env validation
const network = require('./network');
const { host, port } = network.init(config);

// Phase 2: auth keys
const auth = require('./auth');
auth.init(config);

// Phase 3: session store
const session = require('./session');
session.init(config);

// Phase 4: route table
const routes = require('./routes');
routes.init(config);

// Phase 5: middleware ordering
const middleware = require('./middleware');
middleware.init(config);

// Phase 6: structured logging
const logging = require('./logging');
logging.init(config);

// All checks passed — print success and exit
console.log('[Hive] Configuration validated successfully');
console.log(`[Hive] Server running on http://${host}:${port}`);
process.exit(0);
""",
    # ── Stage 1-2: config.server undefined → TypeError, then env validation ──
    "src/network.js": """'use strict';
/**
 * Network subsystem — binds to host:port from [server] config section.
 * Also validates deployment environment.
 */
const VALID_ENVS = ['production', 'staging', 'development'];

function init(config) {
  const host = config.server.host;           // TypeError if config.server undefined
  const port = Number(config.server.port);   // same
  if (!host || typeof host !== 'string') {
    throw new TypeError('Expected server.host to be a non-empty string');
  }
  if (isNaN(port) || port < 1 || port > 65535) {
    throw new RangeError(`Port out of valid range: ${port}`);
  }
  // Environment validation — must be explicitly set
  const env = config.server.env;
  if (!VALID_ENVS.includes(env)) {
    throw new RangeError(
      `server.env must be one of: ${VALID_ENVS.join(', ')} (got: ${JSON.stringify(env)})`
    );
  }
  return { host, port, env };
}
module.exports = { init };
""",
    # ── Stage 3: auth reads key_file from disk, validates length ──
    "src/auth.js": """'use strict';
const fs = require('fs');
const path = require('path');
/**
 * Auth subsystem — loads HMAC signing key from disk.
 * Expects config.auth.key_file to point to a readable file
 * containing a 64-character hex key.
 */
function init(config) {
  const keyPath = path.resolve(config.auth.key_file);  // resolves relative to cwd
  const raw = fs.readFileSync(keyPath, 'utf8').trim();  // ENOENT if path wrong
  if (raw.length !== 64) {
    throw new RangeError(
      `Invalid key length: expected 64 characters, got ${raw.length} (file: ${keyPath})`
    );
  }
  if (!/^[0-9a-fA-F]+$/.test(raw)) {
    throw new TypeError('Key must be hexadecimal');
  }
  return { key: raw, algorithm: config.auth.algorithm };
}
module.exports = { init };
""",
    # ── Stage 4-5: session config missing entirely, then ttl validation ──
    "src/session.js": """'use strict';
const assert = require('assert');
/**
 * Session subsystem — configures session store from [session] section.
 * ttl_seconds must be a positive integer >= 60 (minimum 1 minute).
 */
function init(config) {
  const store = config.session.store;         // TypeError if config.session undefined
  const ttl   = config.session.ttl_seconds;   // same
  assert.ok(
    Number.isInteger(ttl) && ttl >= 60,
    `ttl must be a positive integer >= 60, got: ${JSON.stringify(ttl)}`
  );
  const validStores = ['memory', 'redis', 'file'];
  if (!validStores.includes(store)) {
    throw new RangeError(`Unknown session store "${store}". Valid: ${validStores.join(', ')}`);
  }
  return { store, ttl };
}
module.exports = { init };
""",
    # ── Stage 6-7: routes config missing, then paths must be array ──
    "src/routes.js": """'use strict';
/**
 * Route table — loads API path definitions from [routes] section.
 */
function init(config) {
  const handler = config.routes;              // undefined if [routes] missing
  for (const r of handler.paths) {            // TypeError: handler.paths is not iterable
    if (typeof r !== 'string' || !r.startsWith('/')) {
      throw new SyntaxError(`Invalid route: "${r}" — must start with /`);
    }
  }
  if (!handler.paths.length) {
    throw new RangeError('routes.paths must not be empty');
  }
  return handler;
}
module.exports = { init };
""",
    # ── Stage 8: middleware ordering — must be non-empty string array ──
    "src/middleware.js": """'use strict';
/**
 * Middleware ordering — defines execution order of middleware layers.
 * Expects config.middleware.order to be a non-empty array of known names.
 */
const KNOWN_MIDDLEWARE = ['cors', 'auth', 'ratelimit', 'logging', 'compress', 'cache'];

function init(config) {
  const mw = config.middleware;               // undefined if [middleware] missing
  if (!Array.isArray(mw.order) || mw.order.length === 0) {
    throw new Error('middleware_order must be non-empty array of strings');
  }
  for (const name of mw.order) {
    if (!KNOWN_MIDDLEWARE.includes(name)) {
      throw new Error(
        `Unknown middleware "${name}". Known: ${KNOWN_MIDDLEWARE.join(', ')}`
      );
    }
  }
  return { order: mw.order };
}
module.exports = { init };
""",
    # ── Stage 9: structured logging — format must match pattern ──
    "src/logging.js": """'use strict';
/**
 * Structured logging subsystem.
 * Expects config.logging.level (debug|info|warn|error)
 * and config.logging.format matching '<level>:<target>' pattern
 * e.g. "json:stdout" or "text:file"
 */
const VALID_LEVELS = ['debug', 'info', 'warn', 'error'];
const FORMAT_RE = /^(json|text):(stdout|stderr|file)$/;

function init(config) {
  const log = config.logging;                 // undefined if [logging] missing
  if (!VALID_LEVELS.includes(log.level)) {
    throw new Error(
      `Invalid log level "${log.level}". Valid: ${VALID_LEVELS.join(', ')}`
    );
  }
  if (!FORMAT_RE.test(log.format)) {
    throw new Error(
      `Log format must match '<type>:<target>' pattern (e.g. "json:stdout"). Got: "${log.format}"`
    );
  }
  return { level: log.level, format: log.format };
}
module.exports = { init };
""",
}


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
        ["git", "commit", "-m", "initial: Hive multi-stage scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-multistage.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir


def check_config(repo_dir: Path) -> dict:
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

    # Check auth.key_file points to a valid file with 64 hex chars
    key_file = config.get("auth", {}).get("key_file", "")
    key_ok = False
    if key_file:
        kp = repo_dir / key_file
        if kp.exists():
            kc = kp.read_text(encoding="utf-8").strip()
            key_ok = len(kc) == 64 and all(c in "0123456789abcdefABCDEF" for c in kc)

    checks = {
        "server_ok": (
            "server" in config
            and "host" in config.get("server", {})
            and "port" in config.get("server", {})
            and config.get("server", {}).get("env", "") in ("production", "staging", "development")
        ),
        "auth_ok": (
            "auth" in config
            and key_ok
        ),
        "session_ok": (
            "session" in config
            and isinstance(config.get("session", {}).get("ttl_seconds", None), int)
            and config.get("session", {}).get("ttl_seconds", 0) >= 60
            and config.get("session", {}).get("store", "") in ("memory", "redis", "file")
        ),
        "routes_ok": (
            "routes" in config
            and isinstance(config.get("routes", {}).get("paths", None), list)
            and len(config.get("routes", {}).get("paths", [])) > 0
        ),
        "middleware_ok": (
            "middleware" in config
            and isinstance(config.get("middleware", {}).get("order", None), list)
            and len(config.get("middleware", {}).get("order", [])) > 0
        ),
        "logging_ok": (
            "logging" in config
            and config.get("logging", {}).get("level", "") in ("debug", "info", "warn", "error")
            and bool(__import__("re").match(
                r"^(json|text):(stdout|stderr|file)$",
                config.get("logging", {}).get("format", ""),
            ))
        ),
    }
    checks["all_ok"] = all(checks.values())
    return checks
