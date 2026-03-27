"""Shared test helpers: ServerThread, run_hook, HTTP client functions.

Used by scenario tests to avoid duplication across test_hooks_e2e,
test_multi_agent_sim, test_live_agents, and test_e2e_server.
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

import uvicorn


PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugin"
HOOKS_DIR = PLUGIN_DIR / "hooks"


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


def api_post(base_url: str, path: str, body: dict) -> dict:
    """POST JSON to Overmind server."""
    data = json.dumps(body).encode("utf-8")
    req = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def api_get(base_url: str, path: str, params: dict | None = None) -> dict:
    """GET from Overmind server."""
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def make_hook_env(base_url: str, state_file: Path, user: str, repo_id: str) -> dict:
    """Create environment dict for hook subprocess execution."""
    return {
        **os.environ,
        "OVERMIND_URL": base_url,
        "OVERMIND_REPO_ID": repo_id,
        "OVERMIND_USER": user,
        "OVERMIND_STATE_FILE": str(state_file),
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
    if result.returncode != 0 and result.stderr:
        print(f"Hook stderr: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()
