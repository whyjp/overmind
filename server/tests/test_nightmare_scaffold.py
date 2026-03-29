"""Tests for the nightmare config scaffold — structure + trap sequence."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.ab_scaffolds import SCAFFOLDS
from tests.fixtures.ab_scaffolds import nightmare
from tests.fixtures.ab_scaffolds.nightmare import (
    MAX_TURNS,
    REPO_ID,
    REPO_NAME,
    SCAFFOLD_FILES,
    SHARED_PROMPT,
    check_config,
    create_scaffold,
)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestNightmareScaffoldStructure:
    """Verify module exports, constants, and scaffold file inventory."""

    def test_module_exports(self):
        """All expected names are exported from the nightmare module."""
        for name in (
            "SCAFFOLD_FILES",
            "SHARED_PROMPT",
            "REPO_NAME",
            "REPO_ID",
            "MAX_TURNS",
            "create_scaffold",
            "check_config",
        ):
            assert hasattr(nightmare, name), f"Missing export: {name}"

    def test_registered_in_scaffolds(self):
        """nightmare is registered in the SCAFFOLDS dict."""
        assert "nightmare" in SCAFFOLDS
        assert SCAFFOLDS["nightmare"] is nightmare

    def test_constants(self):
        assert REPO_NAME == "hive-nightmare"
        assert REPO_ID == "github.com/test/hive-nightmare"
        assert MAX_TURNS == 40

    def test_scaffold_files_has_required_keys(self):
        """All 14 expected files are present in SCAFFOLD_FILES."""
        expected = {
            "CLAUDE.md",
            "start.sh",
            "config.toml",
            ".env",
            "secrets/hmac.key",
            "plugins/registry.json",
            "src/config_loader.py",
            "src/server.py",
            "src/db.py",
            "src/auth.py",
            "src/session.py",
            "src/cache.py",
            "src/metrics.py",
            "src/plugins.py",
        }
        assert set(SCAFFOLD_FILES.keys()) == expected

    def test_create_scaffold(self, tmp_path: Path):
        """create_scaffold produces a git repo with all files."""
        repo = create_scaffold(tmp_path)
        assert repo.is_dir()
        assert (repo / ".git").is_dir()
        for rel in SCAFFOLD_FILES:
            assert (repo / rel).exists(), f"Missing file: {rel}"


# ---------------------------------------------------------------------------
# Trap sequence tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def nightmare_repo(tmp_path: Path) -> Path:
    """Create a fresh nightmare scaffold repo."""
    return create_scaffold(tmp_path)


def _run_server(repo_dir: Path) -> tuple[int, str, str]:
    """Run server.py directly (cross-platform; avoids bash dependency)."""
    result = subprocess.run(
        [sys.executable, "src/server.py"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


class TestNightmareTrapSequence:
    """Walk through traps cumulatively, fixing each one."""

    def test_trap1_misleading_db_error(self, nightmare_repo: Path):
        """Initial state: TRAP 1 fires with misleading db error."""
        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc != 0
        output = stdout + stderr
        assert "ConnectionError" in output or "database" in output.lower()
        assert "parse" in output.lower() or "URL" in output or "scheme" in output.lower()

    def test_trap2_after_fixing_db(self, nightmare_repo: Path):
        """Fix .env DATABASE_URL -> TRAP 2 fires (HMAC mismatch)."""
        # Fix TRAP 1: valid database URL
        env_path = nightmare_repo / ".env"
        env_content = env_path.read_text(encoding="utf-8")
        env_content = env_content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        env_path.write_text(env_content, encoding="utf-8")

        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc != 0
        output = stdout + stderr
        assert "HMAC" in output or "key" in output.lower() or "digest" in output.lower()

    def test_trap3_after_fixing_auth(self, nightmare_repo: Path):
        """Fix SECRET_KEY + hmac.key SHA256 pair -> TRAP 3 fires (session missing)."""
        # Fix TRAP 1
        env_path = nightmare_repo / ".env"
        env_content = env_path.read_text(encoding="utf-8")
        env_content = env_content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        # Fix TRAP 2: SECRET_KEY + matching hmac.key
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        env_content = env_content.replace(
            "SECRET_KEY=dev-placeholder-key",
            f"SECRET_KEY={secret}",
        )
        env_path.write_text(env_content, encoding="utf-8")
        (nightmare_repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc != 0
        output = stdout + stderr
        assert "session" in output.lower()

    def test_trap4_after_fixing_session_cache(self, nightmare_repo: Path):
        """Fix session + cache -> TRAP 4 fires (port conflict / missing sections)."""
        env_path = nightmare_repo / ".env"
        env_content = env_path.read_text(encoding="utf-8")
        env_content = env_content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        env_content = env_content.replace(
            "SECRET_KEY=dev-placeholder-key",
            f"SECRET_KEY={secret}",
        )
        env_path.write_text(env_content, encoding="utf-8")
        (nightmare_repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix TRAP 3: add [session] and [cache] to config.toml
        config_path = nightmare_repo / "config.toml"
        config_content = config_path.read_text(encoding="utf-8")
        config_content += """
[session]
timeout = 120

[cache]
backend = "memory"
ttl_seconds = 60
max_items = 1000
"""
        config_path.write_text(config_content, encoding="utf-8")

        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc != 0
        output = stdout + stderr
        # Should mention server/metrics/health or port
        assert (
            "server" in output.lower()
            or "metrics" in output.lower()
            or "health" in output.lower()
            or "port" in output.lower()
        )

    def test_trap5_after_fixing_ports(self, nightmare_repo: Path):
        """Fix ports -> TRAP 5 fires (plugin chain)."""
        env_path = nightmare_repo / ".env"
        env_content = env_path.read_text(encoding="utf-8")
        env_content = env_content.replace(
            "DATABASE_URL=changeme://localhost/db",
            "DATABASE_URL=postgresql://localhost:5432/hive",
        )
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        env_content = env_content.replace(
            "SECRET_KEY=dev-placeholder-key",
            f"SECRET_KEY={secret}",
        )
        env_path.write_text(env_content, encoding="utf-8")
        (nightmare_repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        config_path = nightmare_repo / "config.toml"
        config_content = config_path.read_text(encoding="utf-8")
        config_content += """
[session]
timeout = 120

[cache]
backend = "memory"
ttl_seconds = 60
max_items = 1000

[server]
port = 8000

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30
"""
        config_path.write_text(config_content, encoding="utf-8")

        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc != 0
        output = stdout + stderr
        assert "plugin" in output.lower() or "registry" in output.lower()

    def test_all_traps_fixed_success(self, nightmare_repo: Path):
        """Fix everything -> server starts successfully."""
        # Fix .env
        env_path = nightmare_repo / ".env"
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        env_path.write_text(
            f"DATABASE_URL=postgresql://localhost:5432/hive\n"
            f"SECRET_KEY={secret}\n"
            f"NODE_ENV=development\n"
            f"PLUGIN_PATH=./plugins\n",
            encoding="utf-8",
        )
        # Fix hmac.key
        (nightmare_repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")

        # Fix config.toml
        config_path = nightmare_repo / "config.toml"
        config_path.write_text(
            """# Hive Server Configuration

[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600

[session]
timeout = 120

[cache]
backend = "memory"
ttl_seconds = 60
max_items = 1000

[server]
port = 8000

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30

[plugins]
registry_path = "plugins/registry.json"
""",
            encoding="utf-8",
        )

        # Fix registry.json — add enabled field
        registry_path = nightmare_repo / "plugins" / "registry.json"
        registry_path.write_text(
            json.dumps(
                {"plugins": [{"name": "audit-log", "module": "audit", "enabled": True}]}
            ),
            encoding="utf-8",
        )

        rc, stdout, stderr = _run_server(nightmare_repo)
        assert rc == 0, f"Expected success but got rc={rc}\nstdout: {stdout}\nstderr: {stderr}"
        assert "Configuration validated successfully" in stdout


# ---------------------------------------------------------------------------
# analyze_conversation multi-file config tracking tests
# ---------------------------------------------------------------------------


from tests.fixtures.ab_runner import analyze_conversation


class TestAnalyzeConversationMultiFile:
    def test_tracks_env_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_tracks_hmac_key_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/hive/secrets/hmac.key", "content": "abc"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_tracks_registry_json_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/plugins/registry.json", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_proactive_config_fix_includes_env(self):
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"}}
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "bash start.sh"}}
            ]}},
        ]
        result = analyze_conversation(events)
        assert result["proactive_config_fix"] is True

    def test_config_toml_edits_still_tracked_separately(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/config.toml", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_toml_edits"] >= 1
        assert result["config_file_edits"] >= 1


# ---------------------------------------------------------------------------
# check_config tests
# ---------------------------------------------------------------------------


class TestNightmareCheckConfig:
    """Validate the check_config helper against initial and fully-fixed states."""

    @pytest.fixture()
    def repo(self, tmp_path):
        return create_scaffold(tmp_path)

    def test_initial_state_all_not_ok(self, repo):
        result = check_config(repo)
        assert result["db_ok"] is False
        assert result["auth_ok"] is False
        assert result["session_ok"] is False
        assert result["cache_ok"] is False
        assert result["ports_ok"] is False
        assert result["plugins_ok"] is False
        assert result["all_ok"] is False

    def test_fully_fixed_state(self, repo):
        import hashlib
        import json

        # Fix .env
        secret = "my-production-secret-key-2026"
        hmac_hex = hashlib.sha256(secret.encode()).hexdigest()
        (repo / ".env").write_text(
            f"DATABASE_URL=postgresql://localhost:5432/hive\n"
            f"SECRET_KEY={secret}\n"
            f"NODE_ENV=development\n"
            f"PLUGIN_PATH=./plugins\n",
            encoding="utf-8",
        )
        # Fix secrets/hmac.key
        (repo / "secrets" / "hmac.key").write_text(hmac_hex, encoding="utf-8")
        # Fix registry.json
        reg_path = repo / "plugins" / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["plugins"][0]["enabled"] = True
        reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        # Fix config.toml — add all missing sections
        (repo / "config.toml").write_text(
            """[database]
pool_size = 5
timeout = 30

[auth]
algorithm = "HS256"
token_expiry = 3600

[session]
timeout = 3600

[cache]
ttl_seconds = 1800
backend = "memory"
max_items = 1000

[server]
port = 8080

[metrics]
port = 9090
enabled = true

[health]
port = 9091
interval_seconds = 30

[plugins]
enabled = true
registry_path = "plugins/registry.json"
""",
            encoding="utf-8",
        )

        result = check_config(repo)
        assert result["all_ok"] is True, f"Failed: {result}"


# ---------------------------------------------------------------------------
# analyze_conversation multi-file config tracking tests
# ---------------------------------------------------------------------------


from tests.fixtures.ab_runner import analyze_conversation


class TestAnalyzeConversationMultiFile:
    def test_tracks_env_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_tracks_hmac_key_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/hive/secrets/hmac.key", "content": "abc"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_tracks_registry_json_edit(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/plugins/registry.json", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_file_edits"] >= 1

    def test_proactive_config_fix_includes_env(self):
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/.env", "old_string": "x", "new_string": "y"}}
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "bash start.sh"}}
            ]}},
        ]
        result = analyze_conversation(events)
        assert result["proactive_config_fix"] is True

    def test_config_toml_edits_still_tracked_separately(self):
        events = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/hive/config.toml", "old_string": "x", "new_string": "y"}}
        ]}}]
        result = analyze_conversation(events)
        assert result["config_toml_edits"] >= 1
        assert result["config_file_edits"] >= 1
