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
