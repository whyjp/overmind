"""Tests for the microservices AB scaffold."""
import subprocess
import sys
from pathlib import Path

import pytest

from . import microservices
from .microservices import check_config, create_scaffold, SCAFFOLD_FILES


class TestCheckConfig:
    """Verify check_config detects each trap independently."""

    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        return create_scaffold(tmp_path)

    def test_initial_state_all_not_ok(self, repo: Path):
        """Fresh scaffold should have ALL 5 traps failing."""
        result = check_config(repo)
        assert not result["all_ok"]
        assert not result["ports_ok"], "T1: port mismatch should be detected"
        assert not result["env_mapping_ok"], "T2: AUTH_SECRET missing from .env"
        assert not result["retry_budget_ok"], "T3: retry budget should exceed timeout"
        assert not result["no_cycle"], "T4: circular dependency should be detected"
        assert not result["cluster_token_ok"], "T5: worker token hash should mismatch"

    def test_fix_env_mapping(self, repo: Path):
        """T2: adding AUTH_SECRET to .env resolves auth credential check."""
        env_file = repo / ".env"
        content = env_file.read_text(encoding="utf-8")
        content += "AUTH_SECRET=super-secret-jwt-key-2026\n"
        env_file.write_text(content, encoding="utf-8")
        result = check_config(repo)
        assert result["env_mapping_ok"]

    def test_fix_ports(self, repo: Path):
        """T1: fixing auth port to 8081 resolves port mismatch."""
        auth_toml = repo / "services" / "auth.toml"
        content = auth_toml.read_text(encoding="utf-8")
        content = content.replace("port = 8082", "port = 8081")
        auth_toml.write_text(content, encoding="utf-8")
        result = check_config(repo)
        assert result["ports_ok"]

    def test_fix_retry_budget(self, repo: Path):
        """T3: reducing retries to 3 makes budget (3×5=15) < timeout (30)."""
        worker_toml = repo / "services" / "worker.toml"
        content = worker_toml.read_text(encoding="utf-8")
        content = content.replace("max_retries = 10", "max_retries = 3")
        worker_toml.write_text(content, encoding="utf-8")
        result = check_config(repo)
        assert result["retry_budget_ok"]

    def test_fix_circular_dependency(self, repo: Path):
        """T4: adding lazy=true to worker breaks the cycle."""
        worker_toml = repo / "services" / "worker.toml"
        content = worker_toml.read_text(encoding="utf-8")
        content = content.replace(
            '[dependencies]\nrequires = ["gateway"]',
            '[dependencies]\nrequires = ["gateway"]\nlazy = true',
        )
        worker_toml.write_text(content, encoding="utf-8")
        result = check_config(repo)
        assert result["no_cycle"]

    def test_fix_cluster_token(self, repo: Path):
        """T5: setting correct hash in worker.toml resolves token mismatch."""
        import hashlib

        correct_hash = hashlib.sha256(b"hive-cluster-secret-2026").hexdigest()
        worker_toml = repo / "services" / "worker.toml"
        content = worker_toml.read_text(encoding="utf-8")
        # Replace the wrong hash
        wrong_hash = hashlib.sha256(b"old-cluster-token").hexdigest()
        content = content.replace(wrong_hash, correct_hash)
        worker_toml.write_text(content, encoding="utf-8")
        result = check_config(repo)
        assert result["cluster_token_ok"]

    def test_fully_fixed_state(self, repo: Path):
        """All 5 traps fixed → all_ok = True."""
        import hashlib

        correct_hash = hashlib.sha256(b"hive-cluster-secret-2026").hexdigest()
        wrong_hash = hashlib.sha256(b"old-cluster-token").hexdigest()

        # T1: fix port
        auth_toml = repo / "services" / "auth.toml"
        content = auth_toml.read_text(encoding="utf-8")
        content = content.replace("port = 8082", "port = 8081")
        auth_toml.write_text(content, encoding="utf-8")

        # T2: fix env mapping — add AUTH_SECRET to .env
        env_file = repo / ".env"
        env_content = env_file.read_text(encoding="utf-8")
        env_content += "AUTH_SECRET=super-secret-jwt-key-2026\n"
        env_file.write_text(env_content, encoding="utf-8")

        # T3: fix retry budget
        worker_toml = repo / "services" / "worker.toml"
        content = worker_toml.read_text(encoding="utf-8")
        content = content.replace("max_retries = 10", "max_retries = 3")
        # T4: fix circular dependency
        content = content.replace(
            '[dependencies]\nrequires = ["gateway"]',
            '[dependencies]\nrequires = ["gateway"]\nlazy = true',
        )
        # T5: fix cluster token
        content = content.replace(wrong_hash, correct_hash)
        worker_toml.write_text(content, encoding="utf-8")

        result = check_config(repo)
        assert result["all_ok"], f"Expected all_ok but got: {result}"


class TestCreateScaffold:
    """Verify scaffold creation produces correct structure."""

    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        return create_scaffold(tmp_path)

    def test_creates_all_files(self, repo: Path):
        for rel_path in SCAFFOLD_FILES:
            assert (repo / rel_path).exists(), f"Missing: {rel_path}"

    def test_has_git_repo(self, repo: Path):
        assert (repo / ".git").exists()

    def test_has_remote_origin(self, repo: Path):
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0
        assert "hive-microservices" in result.stdout

    def test_orchestrator_runs_and_fails(self, repo: Path):
        """Initial scaffold should fail with a meaningful error."""
        result = subprocess.run(
            [sys.executable, "src/orchestrator.py"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
            timeout=10,
        )
        assert result.returncode != 0
        assert "STARTUP FAILED" in result.stdout

    def test_orchestrator_succeeds_when_fixed(self, repo: Path):
        """Fully fixed scaffold should boot successfully."""
        import hashlib

        correct_hash = hashlib.sha256(b"hive-cluster-secret-2026").hexdigest()
        wrong_hash = hashlib.sha256(b"old-cluster-token").hexdigest()

        # T1: fix port
        auth_toml = repo / "services" / "auth.toml"
        content = auth_toml.read_text(encoding="utf-8")
        content = content.replace("port = 8082", "port = 8081")
        auth_toml.write_text(content, encoding="utf-8")

        # T2: fix env mapping
        env_file = repo / ".env"
        env_content = env_file.read_text(encoding="utf-8")
        env_content += "AUTH_SECRET=super-secret-jwt-key-2026\n"
        env_file.write_text(env_content, encoding="utf-8")

        # T3+T4+T5: fix worker
        worker_toml = repo / "services" / "worker.toml"
        content = worker_toml.read_text(encoding="utf-8")
        content = content.replace("max_retries = 10", "max_retries = 3")
        content = content.replace(
            '[dependencies]\nrequires = ["gateway"]',
            '[dependencies]\nrequires = ["gateway"]\nlazy = true',
        )
        content = content.replace(wrong_hash, correct_hash)
        worker_toml.write_text(content, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "src/orchestrator.py"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
            timeout=10,
        )
        assert result.returncode == 0
        assert "All services running" in result.stdout
        assert "Server running" in result.stdout


class TestModuleExports:
    """Verify scaffold module has required exports."""

    def test_constants(self):
        assert microservices.REPO_NAME == "hive-microservices"
        assert microservices.REPO_ID == "github.com/test/hive-microservices"
        assert microservices.MAX_TURNS == 40

    def test_has_prompts(self):
        assert len(microservices.SHARED_PROMPT) > 0
        assert len(microservices.PIONEER_PROMPT) > 0
        assert "start.sh" in microservices.SHARED_PROMPT

    def test_registered_in_scaffolds(self):
        from . import SCAFFOLDS
        assert "microservices" in SCAFFOLDS
