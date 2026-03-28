"""E2E test: start server as subprocess, run real HTTP requests.

Unlike test_hooks_e2e.py (thread-based), this test uses subprocess for full isolation.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

PORT = 18888
BASE_URL = f"http://127.0.0.1:{PORT}"


def _api_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _api_get(path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _wait_for_server(timeout: float = 10.0) -> bool:
    """Poll until server responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = Request(f"{BASE_URL}/api/repos", method="GET")
            with urlopen(req, timeout=2):
                return True
        except (URLError, OSError):
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server_process(tmp_path_factory):
    """Start overmind server as a subprocess."""
    data_dir = tmp_path_factory.mktemp("e2e_subprocess_data")
    server_dir = Path(__file__).resolve().parents[2]

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "overmind.main:create_standalone_app",
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--log-level", "error",
            "--factory",
        ],
        cwd=str(server_dir),
        env={**os.environ, "OVERMIND_DATA_DIR": str(data_dir)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if not _wait_for_server():
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(f"Server failed to start. stderr: {stderr.decode()}")

    yield proc

    proc.terminate()
    proc.wait(timeout=5)


class TestE2ESubprocess:
    def test_push_and_pull(self, server_process):
        """Push events and pull them back via real HTTP."""
        result = _api_post("/api/memory/push", {
            "repo_id": "github.com/e2e/subprocess",
            "user": "dev_a",
            "events": [{
                "id": "e2e_sub_001",
                "type": "correction",
                "ts": "2026-03-27T10:00:00Z",
                "result": "subprocess test correction",
                "files": ["src/test/file.ts"],
            }],
        })
        assert result["accepted"] == 1

        pull = _api_get("/api/memory/pull", {
            "repo_id": "github.com/e2e/subprocess",
            "exclude_user": "dev_b",
        })
        assert pull["count"] == 1
        assert pull["events"][0]["result"] == "subprocess test correction"

    def test_broadcast_and_pull(self, server_process):
        """Broadcast and verify it appears in pull."""
        result = _api_post("/api/memory/broadcast", {
            "repo_id": "github.com/e2e/subprocess",
            "user": "master",
            "message": "subprocess broadcast test",
            "priority": "high_priority",
        })
        assert result["delivered"] is True

        pull = _api_get("/api/memory/pull", {
            "repo_id": "github.com/e2e/subprocess",
            "exclude_user": "dev_b",
        })
        # High-priority broadcast should be first
        assert pull["events"][0]["type"] == "broadcast"
        assert pull["events"][0]["priority"] == "high_priority"

    def test_report(self, server_process):
        """Report endpoint returns correct stats."""
        report = _api_get("/api/report", {
            "repo_id": "github.com/e2e/subprocess",
        })
        assert report["total_pushes"] >= 2
        assert report["unique_users"] >= 2

    def test_repos_list(self, server_process):
        """Repos endpoint lists known repos."""
        repos = _api_get("/api/repos")
        assert "github.com/e2e/subprocess" in repos
