"""DEPRECATED: Overmind 효과 미미 — 상호의존성 있으나 에러 메시지가 직관적.

8개 모듈이지만 에러가 솔루션을 직접 가리키므로 Pioneer 지식이 큰 도움이 안 됨.
Overmind 가치 측정에는 misleading error가 핵심 — 에러 메시지 ≠ 실제 원인이어야 함.
비슷한 직관적-에러 scaffold 재생성 금지 — nightmare/branch_conflict 수준의 복잡도 필요.

See: docs/benchmark-ab-test.md (Statistical AB 벤치마크 인사이트)

---
Original: Scaffold data for the A/B Complex 8-Stage Failure Cascade test."""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-complex"
REPO_ID = "github.com/test/hive-complex"
MAX_TURNS = 35

SCAFFOLD_FILES: dict[str, str] = {
    "CLAUDE.md": """# Hive Microservice

## Start
Run `bash start.sh` to start the server.

## Rules
- config.toml is the ONLY file you may edit.
- Do NOT modify any .js or .json file.
- Do NOT create new files (except config.toml edits).
""",
    # ---- Config: only [database] and [auth] present, everything else missing ----
    "config.toml": """# Hive Microservice Configuration

[database]
url = "postgres://localhost:5432/hive"

[auth]
key_file = "./keys/hmac.key"
algorithm = "HS256"
""",
    # The actual key file is at project root, NOT in ./keys/
    "hmac.key": "4a7f3c9e1b2d8a0f5e6c7d3b9a1f0e2c4d5b6a8f7e3c1d9b0a2f4e6c8d7b5a3f",
    "start.sh": """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "[start.sh] Installing dependencies..."
npm install --silent 2>&1
echo "[start.sh] Starting Hive microservice..."
node src/server.js 2>&1
""",
    "package.json": """{
  "name": "hive-microservice",
  "version": "2.0.0",
  "private": true,
  "scripts": { "start": "node src/server.js" },
  "dependencies": { "@iarna/toml": "2.2.5" }
}
""",
    # ==== MAIN ENTRY: loads config, boots each subsystem sequentially ====
    "src/server.js": """'use strict';
const fs = require('fs');
const toml = require('@iarna/toml');

const raw = fs.readFileSync('config.toml', 'utf8');
const config = toml.parse(raw);

// Boot subsystems in order - each may throw
require('./boot/network').init(config);
require('./boot/auth').init(config);
require('./boot/security').init(config);
require('./boot/cache').init(config);
require('./boot/session').init(config);

// Middleware
require('./middleware/cors').init(config);
require('./middleware/ratelimit').init(config);

// Observability
require('./observability/logging').init(config);
require('./observability/metrics').init(config);

// All passed
const { host, port } = config.server;
console.log('[Hive] All 8 subsystems initialized');
console.log(`[Hive] Server running on http://${host}:${port}`);
process.exit(0);
""",
    # ==== BOOT: network ====
    "src/boot/network.js": """'use strict';
// Binds to host:port from [server] section
function init(config) {
  const host = config.server.host;
  const port = config.server.port;
  if (typeof port !== 'number' || !Number.isInteger(port)) {
    throw new RangeError(
      'server.port must be an integer, got ' + typeof port + ': ' + JSON.stringify(port)
    );
  }
  if (port < 1024 || port > 49151) {
    throw new RangeError('server.port must be between 1024-49151, got ' + port);
  }
  if (typeof host !== 'string' || !host) {
    throw new TypeError('server.host must be a non-empty string');
  }
}
module.exports = { init };
""",
    # ==== BOOT: auth (key_file path trap) ====
    "src/boot/auth.js": """'use strict';
const fs = require('fs');
const path = require('path');
// Loads HMAC key from config.auth.key_file
// Key must be exactly 64 hex characters
function init(config) {
  const keyPath = path.resolve(config.auth.key_file);
  const raw = fs.readFileSync(keyPath, 'utf8').trim();
  if (raw.length !== 64) {
    throw new RangeError('Auth key must be 64 hex chars, got ' + raw.length);
  }
  if (!/^[0-9a-fA-F]+$/.test(raw)) {
    throw new TypeError('Auth key must be hexadecimal');
  }
}
module.exports = { init };
""",
    # ==== BOOT: security (api_secret >= 32 chars) ====
    "src/boot/security.js": """'use strict';
const assert = require('assert');
// Reads [security].api_secret - must be >= 32 characters
function init(config) {
  const sec = config.security;
  assert.ok(sec && sec.api_secret, 'security.api_secret is required');
  assert.ok(
    sec.api_secret.length >= 32,
    'security.api_secret must be >= 32 chars, got ' + sec.api_secret.length
  );
  // encryption_algo must be aes-256-gcm or chacha20
  const algo = sec.encryption_algo;
  const valid = ['aes-256-gcm', 'chacha20-poly1305'];
  if (!valid.includes(algo)) {
    throw new RangeError(
      'security.encryption_algo must be one of: ' + valid.join(', ') + ', got: ' + algo
    );
  }
}
module.exports = { init };
""",
    # ==== BOOT: cache (redis URL + ttl) ====
    "src/boot/cache.js": """'use strict';
// Reads [cache] section: url (redis://...) and ttl_seconds (int, 60-86400)
function init(config) {
  const c = config.cache;
  if (!c || !c.url) {
    throw new TypeError('cache.url is required');
  }
  if (!c.url.startsWith('redis://')) {
    throw new TypeError('cache.url must start with redis://, got: ' + c.url);
  }
  const ttl = c.ttl_seconds;
  if (typeof ttl !== 'number' || !Number.isInteger(ttl)) {
    throw new TypeError('cache.ttl_seconds must be an integer');
  }
  if (ttl < 60 || ttl > 86400) {
    throw new RangeError('cache.ttl_seconds must be 60-86400, got ' + ttl);
  }
}
module.exports = { init };
""",
    # ==== BOOT: session (store type + ttl) ====
    "src/boot/session.js": """'use strict';
// Reads [session]: store (memory|redis|file), ttl_seconds (int > 0), secret (string)
function init(config) {
  const s = config.session;
  if (!s) throw new TypeError('Missing [session] configuration section');
  const validStores = ['memory', 'redis', 'file'];
  if (!validStores.includes(s.store)) {
    throw new RangeError('session.store must be: ' + validStores.join(', ') + ', got: ' + s.store);
  }
  if (typeof s.ttl_seconds !== 'number' || s.ttl_seconds <= 0) {
    throw new RangeError('session.ttl_seconds must be positive integer');
  }
  if (!s.secret || typeof s.secret !== 'string' || s.secret.length < 16) {
    throw new TypeError('session.secret must be a string >= 16 chars');
  }
}
module.exports = { init };
""",
    # ==== MIDDLEWARE: cors ====
    "src/middleware/cors.js": """'use strict';
// Reads [cors]: origins (array of URLs), credentials (bool)
function init(config) {
  const c = config.cors;
  if (!c) throw new TypeError('Missing [cors] configuration section');
  if (!Array.isArray(c.origins)) {
    throw new TypeError('cors.origins must be an array, got: ' + typeof c.origins);
  }
  if (c.origins.length === 0) {
    throw new RangeError('cors.origins must not be empty');
  }
  for (const o of c.origins) {
    if (!o.startsWith('http://') && !o.startsWith('https://')) {
      throw new TypeError('cors.origins entries must be URLs, got: ' + o);
    }
  }
  if (typeof c.credentials !== 'boolean') {
    throw new TypeError('cors.credentials must be boolean');
  }
}
module.exports = { init };
""",
    # ==== MIDDLEWARE: ratelimit ====
    "src/middleware/ratelimit.js": """'use strict';
// Reads [ratelimit]: window_ms (int), max_requests (int)
function init(config) {
  const r = config.ratelimit;
  if (!r) throw new TypeError('Missing [ratelimit] configuration section');
  if (typeof r.window_ms !== 'number' || r.window_ms <= 0) {
    throw new RangeError('ratelimit.window_ms must be positive integer');
  }
  if (typeof r.max_requests !== 'number' || r.max_requests <= 0) {
    throw new RangeError('ratelimit.max_requests must be positive integer');
  }
}
module.exports = { init };
""",
    # ==== OBSERVABILITY: logging ====
    "src/observability/logging.js": """'use strict';
// Reads [logging]: level (DEBUG|INFO|WARN|ERROR), format (json|text)
function init(config) {
  const l = config.logging;
  if (!l) throw new TypeError('Missing [logging] configuration section');
  const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
  if (!levels.includes(l.level)) {
    throw new RangeError('logging.level must be: ' + levels.join(', '));
  }
  const formats = ['json', 'text'];
  if (!formats.includes(l.format)) {
    throw new RangeError('logging.format must be: ' + formats.join(', '));
  }
}
module.exports = { init };
""",
    # ==== OBSERVABILITY: metrics (port must differ from server.port) ====
    "src/observability/metrics.js": """'use strict';
// Reads [metrics]: enabled (bool), port (int, must differ from server.port)
function init(config) {
  const m = config.metrics;
  if (!m) throw new TypeError('Missing [metrics] configuration section');
  if (typeof m.enabled !== 'boolean') {
    throw new TypeError('metrics.enabled must be boolean');
  }
  if (m.enabled) {
    if (typeof m.port !== 'number' || !Number.isInteger(m.port)) {
      throw new TypeError('metrics.port must be an integer');
    }
    if (m.port === config.server.port) {
      throw new Error(
        'metrics.port (' + m.port + ') must differ from server.port (' + config.server.port + ')'
      );
    }
  }
}
module.exports = { init };
""",
}

SHARED_PROMPT = (
    "Get the Hive microservice running. "
    "Run `bash start.sh` to start it. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may only edit config.toml."
)


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
        ["git", "commit", "-m", "initial: Hive complex scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True, env=git_env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive-complex.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )
    return repo_dir
