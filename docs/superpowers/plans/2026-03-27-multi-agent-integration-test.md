# Multi-Agent Integration Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hook 시뮬레이션(C)과 Claude CLI(A) 두 레벨의 multi-agent 통합 테스트를 구축한다.

**Architecture:** scaffold_hive.py가 임시 git repo를 생성하고, test_multi_agent_sim.py가 hook subprocess 교차 호출로 결정적 테스트를 수행하며, test_live_agents.py가 실제 claude -p로 E2E 검증한다. 기존 test_hooks_e2e.py의 ServerThread/run_hook 패턴을 재사용한다.

**Tech Stack:** Python 3.11+, pytest, subprocess, uvicorn ServerThread

**Spec:** `docs/superpowers/specs/2026-03-27-multi-agent-integration-test-design.md`

---

### Task 1: Hive scaffold 생성기

**Files:**
- Create: `server/tests/fixtures/__init__.py`
- Create: `server/tests/fixtures/scaffold_hive.py`

- [ ] **Step 1: Create fixtures package**

```python
# server/tests/fixtures/__init__.py
# (empty)
```

- [ ] **Step 2: Create scaffold_hive.py**

```python
# server/tests/fixtures/scaffold_hive.py
"""Generate a scaffolded 'Hive' project as a temporary git repo for testing."""

import subprocess
from pathlib import Path

# File tree: path -> stub content
HIVE_FILES: dict[str, str] = {
    "package.json": """{
  "name": "hive",
  "version": "1.0.0",
  "description": "Team task management API",
  "main": "src/index.ts",
  "scripts": { "dev": "ts-node src/index.ts", "test": "jest" },
  "dependencies": {
    "express": "^4.18.0",
    "jsonwebtoken": "^9.0.0",
    "passport": "^0.7.0",
    "passport-oauth2": "^1.8.0",
    "redis": "^4.6.0",
    "nodemailer": "^6.9.0"
  }
}""",
    ".env.example": """# Database
DATABASE_URL=postgres://localhost:5432/hive

# JWT
JWT_SECRET=your-secret-here
JWT_EXPIRES_IN=24h

# Redis
REDIS_URL=redis://localhost:6379
""",
    "src/index.ts": """import express from 'express';
import { authRouter } from './auth/routes';
import { usersRouter } from './api/users';
import { tasksRouter } from './api/tasks';
import { teamsRouter } from './api/teams';
import { loadEnv } from './config/env';
import { connectDB } from './config/database';
import { errorHandler } from './utils/errors';
import { logger } from './utils/logger';

const app = express();
app.use(express.json());

loadEnv();

app.use('/auth', authRouter);
app.use('/api/users', usersRouter);
app.use('/api/tasks', tasksRouter);
app.use('/api/teams', teamsRouter);
app.use(errorHandler);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => logger.info(`Hive API running on port ${PORT}`));

export default app;
""",
    "src/config/database.ts": """import { logger } from '../utils/logger';

export interface DBConfig {
  url: string;
  pool: { min: number; max: number };
}

export function connectDB(): void {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error('DATABASE_URL not set');
  logger.info('Connected to database');
}

export function disconnectDB(): void {
  logger.info('Disconnected from database');
}
""",
    "src/config/env.ts": """import { config } from 'dotenv';

export function loadEnv(): void {
  config();
  const required = ['DATABASE_URL', 'JWT_SECRET'];
  for (const key of required) {
    if (!process.env[key]) {
      throw new Error(`Missing required env var: ${key}`);
    }
  }
}

export function getEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`Env var ${key} not set`);
  return value;
}
""",
    "src/models/user.ts": """export interface User {
  id: string;
  email: string;
  name: string;
  passwordHash: string;
  role: 'admin' | 'member' | 'viewer';
  createdAt: Date;
  updatedAt: Date;
}

export interface CreateUserInput {
  email: string;
  name: string;
  password: string;
}

// TODO: Add user validation
export function validateUser(input: CreateUserInput): boolean {
  return !!(input.email && input.name && input.password);
}
""",
    "src/models/task.ts": """export type TaskStatus = 'todo' | 'in_progress' | 'review' | 'done';
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  creatorId: string;
  teamId: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface CreateTaskInput {
  title: string;
  description?: string;
  priority?: TaskPriority;
  teamId: string;
}

// TODO: Add task validation and assignment logic
export function validateTask(input: CreateTaskInput): boolean {
  return !!(input.title && input.teamId);
}
""",
    "src/models/team.ts": """export interface Team {
  id: string;
  name: string;
  ownerId: string;
  memberIds: string[];
  createdAt: Date;
}

export interface CreateTeamInput {
  name: string;
  memberIds?: string[];
}
""",
    "src/auth/jwt.ts": """import jwt from 'jsonwebtoken';
import { getEnv } from '../config/env';

export interface TokenPayload {
  userId: string;
  email: string;
  role: string;
}

export function signToken(payload: TokenPayload): string {
  return jwt.sign(payload, getEnv('JWT_SECRET'), {
    expiresIn: getEnv('JWT_EXPIRES_IN') || '24h',
  });
}

export function verifyToken(token: string): TokenPayload {
  return jwt.verify(token, getEnv('JWT_SECRET')) as TokenPayload;
}
""",
    "src/auth/middleware.ts": """import { Request, Response, NextFunction } from 'express';
import { verifyToken } from './jwt';

export function authMiddleware(req: Request, res: Response, next: NextFunction): void {
  const header = req.headers.authorization;
  if (!header || !header.startsWith('Bearer ')) {
    res.status(401).json({ error: 'No token provided' });
    return;
  }
  try {
    const token = header.split(' ')[1];
    const payload = verifyToken(token);
    (req as any).user = payload;
    next();
  } catch (err) {
    res.status(401).json({ error: 'Invalid token' });
  }
}
""",
    "src/auth/routes.ts": """import { Router } from 'express';
import { signToken } from './jwt';

export const authRouter = Router();

authRouter.post('/login', async (req, res) => {
  const { email, password } = req.body;
  // TODO: Validate credentials against database
  const token = signToken({ userId: '1', email, role: 'member' });
  res.json({ token, expiresIn: '24h' });
});

authRouter.post('/register', async (req, res) => {
  const { email, name, password } = req.body;
  // TODO: Create user in database
  const token = signToken({ userId: '1', email, role: 'member' });
  res.status(201).json({ token, user: { email, name } });
});
""",
    "src/api/users.ts": """import { Router } from 'express';
import { authMiddleware } from '../auth/middleware';

export const usersRouter = Router();

usersRouter.get('/me', authMiddleware, (req, res) => {
  res.json((req as any).user);
});

usersRouter.get('/:id', authMiddleware, (req, res) => {
  // TODO: Fetch user from database
  res.json({ id: req.params.id, name: 'Test User' });
});

usersRouter.patch('/:id', authMiddleware, (req, res) => {
  // TODO: Update user in database
  res.json({ id: req.params.id, ...req.body });
});
""",
    "src/api/tasks.ts": """import { Router } from 'express';
import { authMiddleware } from '../auth/middleware';
import { validateTask, CreateTaskInput } from '../models/task';

export const tasksRouter = Router();

tasksRouter.get('/', authMiddleware, (req, res) => {
  // TODO: Fetch tasks from database with filters
  res.json({ tasks: [], total: 0 });
});

tasksRouter.post('/', authMiddleware, (req, res) => {
  const input: CreateTaskInput = req.body;
  if (!validateTask(input)) {
    res.status(400).json({ error: 'Invalid task input' });
    return;
  }
  // TODO: Create task in database
  res.status(201).json({ id: 'new-task-id', ...input, status: 'todo' });
});

tasksRouter.patch('/:id', authMiddleware, (req, res) => {
  // TODO: Update task in database
  res.json({ id: req.params.id, ...req.body });
});

tasksRouter.delete('/:id', authMiddleware, (req, res) => {
  // TODO: Delete task from database
  res.status(204).send();
});
""",
    "src/api/teams.ts": """import { Router } from 'express';
import { authMiddleware } from '../auth/middleware';

export const teamsRouter = Router();

teamsRouter.post('/', authMiddleware, (req, res) => {
  // TODO: Create team
  res.status(201).json({ id: 'new-team', ...req.body });
});

teamsRouter.get('/:id/members', authMiddleware, (req, res) => {
  // TODO: Fetch team members
  res.json({ members: [] });
});
""",
    "src/services/notification.ts": """import { logger } from '../utils/logger';

export interface NotificationPayload {
  to: string;
  subject: string;
  body: string;
}

export async function sendNotification(payload: NotificationPayload): Promise<boolean> {
  // TODO: Implement email sending via nodemailer
  logger.info(`Notification sent to ${payload.to}: ${payload.subject}`);
  return true;
}
""",
    "src/services/cache.ts": """import { logger } from '../utils/logger';

let redisClient: any = null;

export async function connectCache(): Promise<void> {
  const url = process.env.REDIS_URL || 'redis://localhost:6379';
  // TODO: Initialize Redis client
  logger.info(`Cache connected: ${url}`);
}

export async function cacheGet(key: string): Promise<string | null> {
  // TODO: Implement cache get
  return null;
}

export async function cacheSet(key: string, value: string, ttlSeconds?: number): Promise<void> {
  // TODO: Implement cache set with TTL
}

export async function cacheDelete(key: string): Promise<void> {
  // TODO: Implement cache delete
}
""",
    "src/utils/logger.ts": """export const logger = {
  info: (msg: string) => console.log(`[INFO] ${new Date().toISOString()} ${msg}`),
  warn: (msg: string) => console.warn(`[WARN] ${new Date().toISOString()} ${msg}`),
  error: (msg: string) => console.error(`[ERROR] ${new Date().toISOString()} ${msg}`),
};
""",
    "src/utils/errors.ts": """import { Request, Response, NextFunction } from 'express';
import { logger } from './logger';

export class AppError extends Error {
  statusCode: number;
  constructor(message: string, statusCode: number = 500) {
    super(message);
    this.statusCode = statusCode;
  }
}

export function errorHandler(err: Error, req: Request, res: Response, next: NextFunction): void {
  logger.error(`${err.message}`);
  if (err instanceof AppError) {
    res.status(err.statusCode).json({ error: err.message });
  } else {
    res.status(500).json({ error: 'Internal server error' });
  }
}
""",
    "tests/auth.test.ts": """import { signToken, verifyToken } from '../src/auth/jwt';

describe('Auth', () => {
  test('sign and verify token', () => {
    // TODO: Set JWT_SECRET env var for test
    // const token = signToken({ userId: '1', email: 'test@test.com', role: 'member' });
    // const payload = verifyToken(token);
    // expect(payload.userId).toBe('1');
  });
});
""",
    "tests/tasks.test.ts": """import { validateTask } from '../src/models/task';

describe('Tasks', () => {
  test('validate valid task', () => {
    expect(validateTask({ title: 'Test', teamId: 'team-1' })).toBe(true);
  });

  test('reject invalid task', () => {
    expect(validateTask({ title: '', teamId: '' })).toBe(false);
  });
});
""",
    "docs/api.md": """# Hive API Documentation

## Authentication
- POST /auth/login — Login with email/password, returns JWT
- POST /auth/register — Register new user

## Users
- GET /api/users/me — Current user profile
- GET /api/users/:id — User by ID
- PATCH /api/users/:id — Update user

## Tasks
- GET /api/tasks — List tasks (with filters)
- POST /api/tasks — Create task
- PATCH /api/tasks/:id — Update task
- DELETE /api/tasks/:id — Delete task

## Teams
- POST /api/teams — Create team
- GET /api/teams/:id/members — List team members
""",
}


def create_hive_repo(base_dir: Path) -> Path:
    """Create a scaffolded 'Hive' project as a git repo. Returns repo path."""
    repo_dir = base_dir / "hive"
    repo_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in HIVE_FILES.items():
        file_path = repo_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial: Hive project scaffold"],
        cwd=str(repo_dir), capture_output=True, check=True,
        env={**__import__("os").environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/hive.git"],
        cwd=str(repo_dir), capture_output=True, check=True,
    )

    return repo_dir
```

- [ ] **Step 3: Verify scaffold creates valid repo**

Run: `cd D:/github/overmind/server && python -c "from tests.fixtures.scaffold_hive import create_hive_repo; from pathlib import Path; import tempfile; p = create_hive_repo(Path(tempfile.mkdtemp())); print(f'Created {len(list(p.rglob(\"*\")))} files'); import subprocess; r = subprocess.run(['git', 'log', '--oneline'], cwd=str(p), capture_output=True, text=True); print(r.stdout)"`
Expected: file count ~20+, one git commit

- [ ] **Step 4: Commit**

```bash
git add server/tests/fixtures/__init__.py server/tests/fixtures/scaffold_hive.py
git commit -m "feat: add Hive scaffold repo generator for multi-agent tests"
```

---

### Task 2: pytest 마커 등록

**Files:**
- Modify: `server/pyproject.toml`

- [ ] **Step 1: Add pytest config to pyproject.toml**

Append to `server/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "strict"
markers = [
    "e2e_live: requires real Claude CLI, run manually only",
    "multi_agent: multi-agent simulation tests",
]
addopts = "-m 'not e2e_live'"
```

- [ ] **Step 2: Verify markers registered**

Run: `cd D:/github/overmind/server && python -m pytest --markers 2>&1 | grep -E "e2e_live|multi_agent"`
Expected: both markers listed

- [ ] **Step 3: Commit**

```bash
git add server/pyproject.toml
git commit -m "chore: add e2e_live and multi_agent pytest markers"
```

---

### Task 3: Multi-agent hook 시뮬레이션 테스트 (C)

**Files:**
- Create: `server/tests/scenarios/test_multi_agent_sim.py`

- [ ] **Step 1: Create the simulation test**

```python
# server/tests/scenarios/test_multi_agent_sim.py
"""Multi-agent simulation: two agents work on overlapping scopes.

Uses real Overmind server (thread) + hook subprocesses to simulate
the full PostToolUse → PreToolUse → SessionEnd pipeline with two agents
working on a Hive project scaffold.

Scenario:
  Agent A: OAuth2+PKCE authentication (auth/*, config/*)
  Agent B: Task assignment + notifications (api/*, models/*, auth/*, config/*)
  Overlap: auth/middleware.ts, config/env.ts
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
import uvicorn

from overmind.api import create_app
from tests.fixtures.scaffold_hive import create_hive_repo

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
HOOKS_DIR = PLUGIN_DIR / "hooks"
REPO_ID = "github.com/test/hive"
PORT = 17888


class ServerThread:
    """Run uvicorn in a daemon thread with graceful shutdown."""

    def __init__(self, app, port: int):
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(50):
            time.sleep(0.1)
            if self.server.started:
                break
        else:
            raise RuntimeError("Server failed to start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _make_env(base_url: str, state_file: Path, user: str) -> dict:
    return {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": "5",
        "PYTHONIOENCODING": "utf-8",
    }


def run_hook(script_name: str, env: dict, stdin_data: str = "") -> str:
    """Run a hook script as subprocess, return stdout."""
    script = HOOKS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=str(PLUGIN_DIR),
    )
    return result.stdout.strip()


def _post_tool_use(env: dict, file_path: str, tool: str = "Edit") -> str:
    """Simulate PostToolUse hook for a file edit."""
    return run_hook("on_post_tool_use.py", env, json.dumps({
        "tool_name": tool,
        "tool_input": {"file_path": file_path},
    }))


def _pre_tool_use(env: dict, file_path: str) -> str:
    """Simulate PreToolUse hook for a file edit."""
    return run_hook("on_pre_tool_use.py", env, json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
    }))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("multi_agent_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=PORT)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def hive_repo(tmp_path_factory):
    base = tmp_path_factory.mktemp("hive_scaffold")
    return create_hive_repo(base)


@pytest.fixture(scope="module")
def state_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("agent_states")


@pytest.mark.multi_agent
class TestMultiAgentSimulation:
    """Full cross-agent simulation: PostToolUse → PreToolUse → flush → verify."""

    def test_full_sequence(self, server, base_url, hive_repo, state_dir):
        env_a = _make_env(base_url, state_dir / "state_a.json", "agent_a")
        env_b = _make_env(base_url, state_dir / "state_b.json", "agent_b")

        # ── Phase 1: Agent A starts OAuth2 work ──
        # SessionStart: no events yet
        out = run_hook("on_session_start.py", env_a)
        assert out == "", "No events yet — SessionStart should be silent"

        # Agent A edits auth files (3 PostToolUse calls)
        _post_tool_use(env_a, "src/auth/jwt.ts")
        _post_tool_use(env_a, "src/auth/routes.ts")
        _post_tool_use(env_a, "src/auth/middleware.ts")

        # Verify accumulation in state
        state_a = json.loads((state_dir / "state_a.json").read_text())
        assert len(state_a["pending_changes"]) == 3
        assert state_a["current_scope"] == "src/auth/*"

        # ── Phase 2: Agent B starts, enters auth scope ──
        out = run_hook("on_session_start.py", env_b)
        assert out == "", "No pushed events yet — still accumulating"

        # Agent B: PreToolUse on auth/middleware.ts
        # A hasn't flushed yet, so no cross-agent warning
        out = _pre_tool_use(env_b, "src/auth/middleware.ts")
        # At this point A hasn't pushed, so B sees nothing
        assert out == "", "A hasn't flushed yet — no warning expected"

        # Agent B edits non-overlapping files
        _post_tool_use(env_b, "src/api/tasks.ts")
        _post_tool_use(env_b, "src/models/task.ts")

        # ── Phase 3: Agent A hits flush threshold ──
        _post_tool_use(env_a, "src/config/env.ts")  # scope change → flush auth/*
        _post_tool_use(env_a, ".env.example")  # 5th total → also triggers count

        # Verify A's auth/* events are now on server
        pull = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
            "exclude_user": "agent_b",
        })
        assert pull["count"] >= 1, "Agent A's auth scope events should be on server"
        assert any("src/auth/*" in e.get("scope", "") or
                    any("src/auth/" in f for f in e.get("files", []))
                    for e in pull["events"])

        # ── Phase 4: Agent B enters auth scope again — NOW sees A's events ──
        out = _pre_tool_use(env_b, "src/auth/middleware.ts")
        assert out != "", "B should now see A's auth/* events"
        parsed = json.loads(out)
        assert "systemMessage" in parsed
        assert "agent_a" in parsed["systemMessage"]
        assert "OVERMIND" in parsed["systemMessage"]

        # Agent B continues working, hits overlapping scopes
        _post_tool_use(env_b, "src/services/notification.ts")
        _post_tool_use(env_b, "src/auth/middleware.ts")
        _post_tool_use(env_b, "src/config/env.ts")  # scope change → flush previous

        # ── Phase 5: Verify cross-agent visibility ──
        # Agent A checks config scope — should see B's changes
        out = _pre_tool_use(env_a, "src/config/env.ts")
        # B's config/env.ts change should be visible after B's flush
        # (B had scope change from api/* to auth/* to config/*)

        # ── Phase 6: SessionEnd — flush remaining ──
        run_hook("on_session_end.py", env_a, "{}")
        run_hook("on_session_end.py", env_b, "{}")

        # ── Phase 7: Verify final server state ──
        # Both agents should have events
        pull_all = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "limit": "50",
        })
        assert pull_all["count"] >= 2, "Both agents should have pushed events"
        users = {e["user"] for e in pull_all["events"]}
        assert "agent_a" in users, "Agent A events missing"
        assert "agent_b" in users, "Agent B events missing"

        # Report stats
        report = _api_get(base_url, "/api/report", {"repo_id": REPO_ID})
        assert report["unique_users"] >= 2
        assert report["events_by_type"].get("change", 0) >= 2

        # Graph: polymorphism detection on auth/* scope
        graph = _api_get(base_url, "/api/report/graph", {"repo_id": REPO_ID})
        auth_polys = [
            p for p in graph.get("polymorphisms", [])
            if "auth" in p.get("scope", "")
        ]
        assert len(auth_polys) >= 1, (
            f"Expected polymorphism on auth/* scope, got: {graph.get('polymorphisms', [])}"
        )
        poly_users = set(auth_polys[0]["users"])
        assert poly_users == {"agent_a", "agent_b"}

    def test_scope_isolation(self, server, base_url, state_dir):
        """Events in api/* scope should not appear in auth/* pull."""
        pull_api = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/api/*",
        })
        pull_auth = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
        })
        api_ids = {e["id"] for e in pull_api["events"]}
        auth_ids = {e["id"] for e in pull_auth["events"]}
        assert not api_ids.intersection(auth_ids), "api/* and auth/* events should not overlap"
```

- [ ] **Step 2: Run the simulation test**

Run: `cd D:/github/overmind/server && python -m pytest tests/scenarios/test_multi_agent_sim.py -v`
Expected: 2 PASSED

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_multi_agent_sim.py
git commit -m "test: add multi-agent hook simulation test (C)"
```

---

### Task 4: Claude CLI live agent 테스트 (A)

**Files:**
- Create: `server/tests/scenarios/test_live_agents.py`

- [ ] **Step 1: Create the live agents test**

```python
# server/tests/scenarios/test_live_agents.py
"""Live multi-agent E2E: run real Claude CLI agents against Hive scaffold.

Requires:
  - `claude` CLI installed and authenticated
  - Overmind plugin at plugin/ directory
  - Run manually: pytest tests/scenarios/test_live_agents.py -m e2e_live

This test is EXCLUDED from normal test runs via addopts in pyproject.toml.
"""

import json
import os
import subprocess
import sys
import shutil
import threading
import time
import warnings
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
import uvicorn

from overmind.api import create_app
from tests.fixtures.scaffold_hive import create_hive_repo

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
PORT = 17999


class ServerThread:
    def __init__(self, app, port: int):
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(50):
            time.sleep(0.1)
            if self.server.started:
                break
        else:
            raise RuntimeError("Server failed to start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module")
def claude_cli():
    """Check that claude CLI is available."""
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found — install Claude Code to run this test")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("live_agent_data")
    app = create_app(data_dir=data_dir)
    srv = ServerThread(app, port=PORT)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def hive_repo(tmp_path_factory):
    base = tmp_path_factory.mktemp("live_hive")
    return create_hive_repo(base)


REPO_ID = "github.com/test/hive"

AGENT_A_PROMPT = (
    "You are working on a TypeScript Express API project. "
    "Add OAuth2+PKCE authentication support. Specifically:\n"
    "1. In src/auth/jwt.ts — add an OAuth2 token exchange function\n"
    "2. In src/auth/routes.ts — add a GET /auth/oauth2/callback endpoint\n"
    "3. In src/auth/middleware.ts — support both JWT and OAuth2 tokens\n"
    "4. In src/config/env.ts — add OAUTH_CLIENT_ID and OAUTH_SECRET to required vars\n"
    "5. In .env.example — document the new OAuth2 environment variables\n"
    "Important: passport-oauth2 v3.x does NOT support PKCE. Use v4.x.\n"
    "Make minimal, focused edits. Do not create new files."
)

AGENT_B_PROMPT = (
    "You are working on a TypeScript Express API project. "
    "Add task assignment with email notifications. Specifically:\n"
    "1. In src/api/tasks.ts — add POST /api/tasks/:id/assign endpoint\n"
    "2. In src/models/task.ts — add assigneeId and assignedAt fields to Task interface\n"
    "3. In src/services/notification.ts — implement sendAssignmentNotification using nodemailer\n"
    "4. In src/auth/middleware.ts — add a requireRole('admin') middleware function\n"
    "5. In src/config/env.ts — add SMTP_HOST, SMTP_PORT, SMTP_USER to required vars\n"
    "Make minimal, focused edits. Do not create new files."
)


def _run_claude_agent(
    prompt: str,
    cwd: Path,
    user: str,
    state_file: Path,
    base_url: str,
) -> subprocess.CompletedProcess:
    """Run claude -p with Overmind plugin and env overrides."""
    env = {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": REPO_ID,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
        "OVERMIND_FLUSH_THRESHOLD": "3",
    }
    return subprocess.run(
        [
            "claude", "-p", prompt,
            "--max-turns", "10",
            "--plugin-dir", str(PLUGIN_DIR),
        ],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.e2e_live
class TestLiveAgents:
    """Run real Claude CLI agents in parallel against Hive scaffold."""

    def test_parallel_agents(self, claude_cli, server, base_url, hive_repo, tmp_path):
        state_a = tmp_path / "state_a.json"
        state_b = tmp_path / "state_b.json"

        # Run both agents in parallel via threads
        results = {}

        def run_agent(name, prompt, state_file):
            results[name] = _run_claude_agent(
                prompt, hive_repo, name, state_file, base_url,
            )

        thread_a = threading.Thread(target=run_agent, args=("agent_a", AGENT_A_PROMPT, state_a))
        thread_b = threading.Thread(target=run_agent, args=("agent_b", AGENT_B_PROMPT, state_b))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=180)
        thread_b.join(timeout=180)

        # Check agents completed
        assert "agent_a" in results, "Agent A did not complete"
        assert "agent_b" in results, "Agent B did not complete"

        proc_a = results["agent_a"]
        proc_b = results["agent_b"]

        if proc_a.returncode != 0:
            warnings.warn(f"Agent A exited with code {proc_a.returncode}: {proc_a.stderr[:500]}")
        if proc_b.returncode != 0:
            warnings.warn(f"Agent B exited with code {proc_b.returncode}: {proc_b.stderr[:500]}")

        # ── Verify Overmind server state ──

        # Hard: both agents should have pushed at least 1 event
        pull = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "limit": "100",
        })
        assert pull["count"] >= 2, (
            f"Expected >= 2 events from 2 agents, got {pull['count']}"
        )
        users = {e["user"] for e in pull["events"]}
        assert "agent_a" in users, "Agent A events missing from server"
        assert "agent_b" in users, "Agent B events missing from server"

        # Hard: change events should exist
        types = {e["type"] for e in pull["events"]}
        assert "change" in types, f"Expected 'change' type events, got: {types}"

        # Report
        report = _api_get(base_url, "/api/report", {"repo_id": REPO_ID})
        assert report["unique_users"] >= 2
        print(f"\n📊 Report: {report['total_pushes']} pushes, "
              f"{report['unique_users']} users, "
              f"types: {report['events_by_type']}")

        # Soft: polymorphism detection (agents may not overlap)
        graph = _api_get(base_url, "/api/report/graph", {"repo_id": REPO_ID})
        if graph.get("polymorphisms"):
            poly_scopes = [p["scope"] for p in graph["polymorphisms"]]
            print(f"🔀 Polymorphisms detected: {poly_scopes}")
        else:
            warnings.warn(
                "No polymorphism detected — agents may not have overlapped on auth/*. "
                "This is non-deterministic and acceptable."
            )

        # Soft: auth/* scope should have events from both
        pull_auth = _api_get(base_url, "/api/memory/pull", {
            "repo_id": REPO_ID,
            "scope": "src/auth/*",
        })
        auth_users = {e["user"] for e in pull_auth["events"]}
        if auth_users != {"agent_a", "agent_b"}:
            warnings.warn(
                f"Expected both agents in auth/* scope, got: {auth_users}. "
                "Non-deterministic — agent may not have edited auth files."
            )
        else:
            print("✅ Both agents touched auth/* scope — cross-agent visibility confirmed")
```

- [ ] **Step 2: Verify test is skipped in normal runs**

Run: `cd D:/github/overmind/server && python -m pytest tests/scenarios/test_live_agents.py -v`
Expected: 1 deselected (e2e_live marker excluded by addopts)

- [ ] **Step 3: Commit**

```bash
git add server/tests/scenarios/test_live_agents.py
git commit -m "test: add Claude CLI live multi-agent test (A)"
```

---

### Task 5: 전체 검증 + 기존 테스트 호환성

**Files:** (none — verification only)

- [ ] **Step 1: Run all server tests (e2e_live excluded)**

Run: `cd D:/github/overmind/server && python -m pytest tests/ -v`
Expected: All pass (51 existing + 2 multi_agent_sim + 0 e2e_live = ~53)

- [ ] **Step 2: Run all plugin tests**

Run: `cd D:/github/overmind/plugin && python -m pytest tests/ -v`
Expected: 59 PASSED (unchanged)

- [ ] **Step 3: Verify e2e_live can be selected manually**

Run: `cd D:/github/overmind/server && python -m pytest tests/scenarios/test_live_agents.py -m e2e_live --co`
Expected: 1 test collected (test_parallel_agents)

- [ ] **Step 4: Commit if any fixes needed**

```bash
git commit -m "fix: test compatibility adjustments" # only if needed
```
