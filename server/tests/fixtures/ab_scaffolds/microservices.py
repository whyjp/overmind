"""Microservices scaffold: 3-service dependency resolution with hidden traps.

Scenario:
  A Python project simulates 3 microservices (gateway, auth, worker) via
  a single orchestrator. Each service reads its own TOML config plus shared
  .env and env_mapping.json. The orchestrator boots services in dependency
  order and runs health checks.

  Traps (5):
    T1: Port mismatch — gateway.toml upstream.auth.port ≠ auth.toml server.port
        Error in gateway ("Connection refused :8081"), fix in auth.toml (port=8082)
    T2: Env mapping indirection — .env has JWT_SECRET, but env_mapping.json
        renames it to AUTH_SECRET. Error: "JWT_SECRET not found" from validator,
        fix: update .env key OR env_mapping.json
    T3: Retry budget constraint — worker.retries × worker.poll_interval must be
        < gateway.timeout. Error: "retry budget exceeds timeout" without saying
        which value to change
    T4: Circular dependency — gateway→auth→worker→gateway. Must add lazy=true
        to worker.toml [dependencies] to break cycle. Only worker→gateway is async.
    T5: Cluster token — all 3 services + .env must agree. Service TOMLs store
        sha256(token), .env stores raw token. Error: "cluster token mismatch"
        without identifying which service diverges.

  Design criteria (all 4 met):
    ✓ Misleading error: every trap's error message ≠ actual fix location
    ✓ Cross-file: minimum 2 files per trap, T5 spans 4 files
    ✓ Cumulative/mutual: T1→T2→T3 sequential + T4 conceptual + T5 consistency
    ✓ Measurable: server_run_attempts, proactive_config_fix, success_rate
"""

import os
import subprocess
from pathlib import Path

REPO_NAME = "hive-microservices"
REPO_ID = "github.com/test/hive-microservices"
MAX_TURNS = 40

SHARED_PROMPT = (
    "Get the Hive microservices cluster running. "
    "Run `bash start.sh` to start the orchestrator. "
    "If it fails, investigate and fix the issue, then retry. "
    "You may edit services/*.toml, .env, services/env_mapping.json. "
    "Do NOT modify files under src/ or create new files."
)

PIONEER_PROMPT = (
    "Get the Hive microservices cluster running. I've solved this before — follow these exact steps:\n\n"
    "Step 1: Fix port mismatch — in services/auth.toml, change [server] port from 8082 to 8081\n"
    "  (gateway.toml [upstream.auth] expects port 8081, but auth listens on 8082)\n\n"
    "Step 2: Fix env mapping — in .env, rename JWT_SECRET to AUTH_SECRET\n"
    "  (services/env_mapping.json maps JWT_SECRET→AUTH_SECRET, but auth service reads AUTH_SECRET directly.\n"
    "   The validator checks that mapped names exist in .env. Either rename the key in .env,\n"
    "   or change the mapping. Renaming in .env is simpler.)\n\n"
    "Step 3: Fix retry budget — in services/worker.toml, change [queue] max_retries from 10 to 3\n"
    "  (constraint: retries × poll_interval < gateway timeout. Currently 10×5=50 > 30)\n\n"
    "Step 4: Break circular dependency — in services/worker.toml, add under [dependencies]:\n"
    "  lazy = true\n"
    "  (gateway→auth→worker→gateway is a cycle. Only worker→gateway is async/lazy.)\n\n"
    "Step 5: Fix cluster token — in services/worker.toml, change [cluster] token_hash to:\n"
    "  Run: python -c \"import hashlib; print(hashlib.sha256(b'hive-cluster-secret-2026').hexdigest())\"\n"
    "  Use that value for token_hash. Gateway and auth already have the correct hash.\n\n"
    "Step 6: Run `bash start.sh` to verify all 3 services pass health checks.\n\n"
    "You may edit services/*.toml, .env, services/env_mapping.json. "
    "Do NOT modify files under src/ or create new files."
)


# -- Precompute the correct token hash for consistency --
import hashlib as _hashlib

_CLUSTER_TOKEN = "hive-cluster-secret-2026"
_CORRECT_HASH = _hashlib.sha256(_CLUSTER_TOKEN.encode()).hexdigest()
_WRONG_HASH = _hashlib.sha256(b"old-cluster-token").hexdigest()

SCAFFOLD_FILES: dict[str, str] = {
    # ── Top-level files ───────────────────────────────────────────────
    "CLAUDE.md": """# Hive Microservices Cluster

## Start
Run `bash start.sh` to start the orchestrator.

## Architecture
Three services: gateway (HTTP entry), auth (JWT validation), worker (async jobs).
The orchestrator boots them in dependency order and runs health checks.

## Config
- `services/gateway.toml` — Gateway config (port, upstream refs, timeout)
- `services/auth.toml` — Auth service config (port, JWT, cluster token)
- `services/worker.toml` — Worker config (queue, retries, cluster token)
- `services/env_mapping.json` — Maps .env variable names to service-internal names
- `.env` — Shared environment variables
""",

    ".env": f"""# Shared environment for all services
CLUSTER_TOKEN={_CLUSTER_TOKEN}
JWT_SECRET=super-secret-jwt-key-2026
WORKER_KEY=worker-key-abcdef123456
GATEWAY_HOST=0.0.0.0
LOG_LEVEL=info
""",

    "start.sh": r"""#!/usr/bin/env bash
set -e
echo "[Hive] Starting microservices cluster..."
python src/orchestrator.py
""",

    # ── Service configs ───────────────────────────────────────────────
    # TRAP 1: gateway expects auth on port 8081, but auth.toml says 8082
    "services/gateway.toml": f"""[server]
port = 8080
host = "0.0.0.0"

[upstream.auth]
host = "localhost"
port = 8081

[upstream.worker]
host = "localhost"
port = 9000

[timeout]
max_seconds = 30

[dependencies]
requires = ["auth"]

[cluster]
token_hash = "{_CORRECT_HASH}"
""",

    # TRAP 1 target: port is 8082, should be 8081 to match gateway
    # TRAP 2 target: auth reads AUTH_SECRET (mapped from JWT_SECRET via env_mapping)
    "services/auth.toml": f"""[server]
port = 8082

[jwt]
algorithm = "HS256"
env_key = "AUTH_SECRET"
expiry_seconds = 3600

[dependencies]
requires = ["worker"]

[cluster]
token_hash = "{_CORRECT_HASH}"
""",

    # TRAP 3: retries(10) × poll_interval(5) = 50 > gateway timeout(30)
    # TRAP 4: depends on gateway, creating cycle. needs lazy = true
    # TRAP 5: wrong token_hash
    "services/worker.toml": f"""[server]
port = 9000

[queue]
max_retries = 10
poll_interval = 5
batch_size = 10

[dependencies]
requires = ["gateway"]

[cluster]
token_hash = "{_WRONG_HASH}"
""",

    # TRAP 2: maps JWT_SECRET → AUTH_SECRET.
    # .env has JWT_SECRET, auth reads AUTH_SECRET.
    # Validator checks that MAPPED names exist in .env.
    "services/env_mapping.json": """{
  "JWT_SECRET": "AUTH_SECRET",
  "WORKER_KEY": "WORKER_KEY",
  "CLUSTER_TOKEN": "CLUSTER_TOKEN"
}
""",

    # ── Source files (read-only) ──────────────────────────────────────
    "src/orchestrator.py": r'''"""Microservices orchestrator — boots services in dependency order."""
import sys
import os
import json
import hashlib

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("STARTUP FAILED: tomllib not available (Python 3.11+ required)")
        sys.exit(1)

SERVICES_DIR = os.path.join(os.path.dirname(__file__), "..", "services")
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def load_env():
    """Load .env file into dict."""
    env = {}
    if not os.path.exists(ENV_FILE):
        print("STARTUP FAILED: .env file not found")
        sys.exit(1)
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def load_service_config(name):
    """Load a service TOML config."""
    path = os.path.join(SERVICES_DIR, f"{name}.toml")
    if not os.path.exists(path):
        print(f"STARTUP FAILED: services/{name}.toml not found")
        sys.exit(1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def validate_env_mapping(env):
    """Validate that env_mapping.json target names exist in .env."""
    mapping_path = os.path.join(SERVICES_DIR, "env_mapping.json")
    if not os.path.exists(mapping_path):
        print("STARTUP FAILED: services/env_mapping.json not found")
        sys.exit(1)
    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)

    for source_key, target_key in mapping.items():
        # TRAP 2: validator checks that SOURCE keys exist in .env
        # env has JWT_SECRET, mapping says JWT_SECRET→AUTH_SECRET
        # But the check below looks for the SOURCE key in env
        if source_key not in env:
            print(f"STARTUP FAILED: {source_key} not found in .env "
                  f"(required by env_mapping for {target_key})")
            sys.exit(1)


def resolve_env(env, key):
    """Resolve an env key through the mapping."""
    mapping_path = os.path.join(SERVICES_DIR, "env_mapping.json")
    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)
    # Find which source key maps to the requested target
    for source, target in mapping.items():
        if target == key:
            return env.get(source)
    return env.get(key)


def check_dependencies(configs):
    """Check for circular dependencies. Lazy deps break cycles."""
    graph = {}
    for name, cfg in configs.items():
        deps = cfg.get("dependencies", {})
        requires = deps.get("requires", [])
        lazy = deps.get("lazy", False)
        if lazy:
            graph[name] = []  # lazy deps don't create hard edges
        else:
            graph[name] = list(requires)

    # Simple cycle detection via DFS
    visited = set()
    rec_stack = set()
    cycle_path = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for dep in graph.get(node, []):
            if dep not in visited:
                if dfs(dep, path):
                    return True
            elif dep in rec_stack:
                cycle_start = path.index(dep)
                cycle_path.extend(path[cycle_start:])
                cycle_path.append(dep)
                return True
        path.pop()
        rec_stack.discard(node)
        return False

    for node in graph:
        if node not in visited:
            if dfs(node, []):
                cycle_str = " -> ".join(cycle_path)
                print(f"STARTUP FAILED: circular dependency detected: {cycle_str}")
                sys.exit(1)


def check_port_connectivity(configs):
    """Verify upstream port references match service configs."""
    for name, cfg in configs.items():
        upstreams = {k: v for k, v in cfg.items() if k.startswith("upstream.")}
        for key, upstream_cfg in cfg.items():
            if not key.startswith("upstream"):
                continue
            if not isinstance(upstream_cfg, dict):
                continue
            target_name = key.split(".")[-1]
            expected_port = upstream_cfg.get("port")
            if target_name in configs:
                actual_port = configs[target_name].get("server", {}).get("port")
                if expected_port and actual_port and expected_port != actual_port:
                    print(f"STARTUP FAILED: {name} expects {target_name} on port "
                          f"{expected_port}, but {target_name} listens on {actual_port}")
                    sys.exit(1)


def check_retry_budget(configs):
    """Verify worker retry budget fits within gateway timeout."""
    worker_cfg = configs.get("worker", {})
    gateway_cfg = configs.get("gateway", {})

    queue = worker_cfg.get("queue", {})
    retries = queue.get("max_retries", 0)
    poll_interval = queue.get("poll_interval", 1)
    budget = retries * poll_interval

    timeout = gateway_cfg.get("timeout", {}).get("max_seconds", 60)

    if budget >= timeout:
        print(f"STARTUP FAILED: worker retry budget ({retries} retries × "
              f"{poll_interval}s interval = {budget}s) exceeds gateway "
              f"timeout ({timeout}s)")
        sys.exit(1)


def check_cluster_tokens(configs, env):
    """Verify all services agree on cluster token."""
    raw_token = env.get("CLUSTER_TOKEN", "")
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    mismatched = []
    for name, cfg in configs.items():
        cluster = cfg.get("cluster", {})
        token_hash = cluster.get("token_hash", "")
        if token_hash != expected_hash:
            mismatched.append(name)

    if mismatched:
        print(f"STARTUP FAILED: cluster token mismatch between services "
              f"({', '.join(mismatched)} differ from .env CLUSTER_TOKEN)")
        sys.exit(1)


def check_auth_env(configs, env):
    """Verify auth service can find its JWT secret via env mapping."""
    auth_cfg = configs.get("auth", {})
    jwt_env_key = auth_cfg.get("jwt", {}).get("env_key", "")
    if jwt_env_key:
        value = resolve_env(env, jwt_env_key)
        if not value:
            print(f"STARTUP FAILED: auth service requires {jwt_env_key} "
                  f"but it is not resolvable through env_mapping.json")
            sys.exit(1)


def boot_sequence(configs):
    """Determine boot order from dependencies (topological sort)."""
    graph = {}
    for name, cfg in configs.items():
        deps = cfg.get("dependencies", {})
        requires = deps.get("requires", [])
        lazy = deps.get("lazy", False)
        graph[name] = [] if lazy else list(requires)

    order = []
    visited = set()

    def topo(node):
        if node in visited:
            return
        visited.add(node)
        for dep in graph.get(node, []):
            topo(dep)
        order.append(node)

    for node in graph:
        topo(node)
    return order


def main():
    print("[Hive] Loading environment...")
    env = load_env()

    print("[Hive] Validating env mapping...")
    validate_env_mapping(env)

    print("[Hive] Loading service configs...")
    configs = {}
    for name in ("gateway", "auth", "worker"):
        configs[name] = load_service_config(name)

    print("[Hive] Checking dependencies...")
    check_dependencies(configs)

    print("[Hive] Checking port connectivity...")
    check_port_connectivity(configs)

    print("[Hive] Checking auth environment...")
    check_auth_env(configs, env)

    print("[Hive] Checking retry budget...")
    check_retry_budget(configs)

    print("[Hive] Checking cluster tokens...")
    check_cluster_tokens(configs, env)

    boot_order = boot_sequence(configs)
    print(f"[Hive] Boot order: {' -> '.join(boot_order)}")

    for name in boot_order:
        port = configs[name].get("server", {}).get("port", "?")
        print(f"[Hive] Starting {name} on port {port}... OK")

    print("[Hive] All services running. Cluster healthy.")
    print("[Hive] Server running on port 8080")


if __name__ == "__main__":
    main()
''',
}


def create_scaffold(base_dir: Path) -> Path:
    """Create microservices scaffold as a git repo."""
    repo_dir = base_dir / REPO_NAME
    repo_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in SCAFFOLD_FILES.items():
        fp = repo_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    # Make start.sh executable
    start_sh = repo_dir / "start.sh"
    if start_sh.exists():
        start_sh.chmod(0o755)

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
        ["git", "commit", "-m", "initial: Hive microservices scaffold"],
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
            f"https://github.com/test/{REPO_NAME}.git",
        ],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    return repo_dir


def check_config(repo_dir: Path) -> dict:
    """Validate the current state of all microservices scaffold configs.

    Returns a dict with boolean checks for each trap area plus ``all_ok``.
    """
    import hashlib
    import json

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    result = {
        "ports_ok": False,
        "env_mapping_ok": False,
        "retry_budget_ok": False,
        "no_cycle": False,
        "cluster_token_ok": False,
        "all_ok": False,
    }

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

    # -- Load service configs --
    configs: dict[str, dict] = {}
    for name in ("gateway", "auth", "worker"):
        toml_path = repo_dir / "services" / f"{name}.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                configs[name] = tomllib.load(f)
        else:
            configs[name] = {}

    # -- Load env_mapping --
    mapping: dict[str, str] = {}
    mapping_path = repo_dir / "services" / "env_mapping.json"
    if mapping_path.exists():
        with open(mapping_path, encoding="utf-8") as f:
            mapping = json.load(f)

    # T1: Port connectivity — TOML [upstream.auth] parses as nested dict
    gateway_upstream = configs.get("gateway", {}).get("upstream", {})
    gateway_auth_port = gateway_upstream.get("auth", {}).get("port")
    auth_port = configs.get("auth", {}).get("server", {}).get("port")
    result["ports_ok"] = (
        gateway_auth_port is not None
        and auth_port is not None
        and gateway_auth_port == auth_port
    )

    # T2: Env mapping — auth needs AUTH_SECRET resolvable
    auth_env_key = (configs.get("auth", {})
                    .get("jwt", {})
                    .get("env_key", ""))
    if auth_env_key:
        # Check if any mapping source→target where target==auth_env_key has source in env
        resolved = False
        for source, target in mapping.items():
            if target == auth_env_key and source in env:
                resolved = True
                break
        # Also check direct presence
        if auth_env_key in env:
            resolved = True
        result["env_mapping_ok"] = resolved
    else:
        result["env_mapping_ok"] = True

    # T3: Retry budget
    worker_queue = configs.get("worker", {}).get("queue", {})
    retries = worker_queue.get("max_retries", 0)
    poll_interval = worker_queue.get("poll_interval", 1)
    budget = retries * poll_interval
    gateway_timeout = (configs.get("gateway", {})
                       .get("timeout", {})
                       .get("max_seconds", 60))
    result["retry_budget_ok"] = budget < gateway_timeout

    # T4: Circular dependency
    graph: dict[str, list[str]] = {}
    for name, cfg in configs.items():
        deps = cfg.get("dependencies", {})
        requires = deps.get("requires", [])
        lazy = deps.get("lazy", False)
        graph[name] = [] if lazy else list(requires)

    visited: set[str] = set()
    rec_stack: set[str] = set()
    has_cycle = False

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for dep in graph.get(node, []):
            if dep not in visited:
                if dfs(dep):
                    return True
            elif dep in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    for node in graph:
        if node not in visited:
            if dfs(node):
                has_cycle = True
                break
    result["no_cycle"] = not has_cycle

    # T5: Cluster token consistency
    raw_token = env.get("CLUSTER_TOKEN", "")
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    all_match = True
    for name, cfg in configs.items():
        token_hash = cfg.get("cluster", {}).get("token_hash", "")
        if token_hash != expected_hash:
            all_match = False
            break
    result["cluster_token_ok"] = all_match

    result["all_ok"] = all(
        result[k] for k in result if k != "all_ok"
    )
    return result
