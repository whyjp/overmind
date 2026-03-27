"""Shared fixtures for plugin tests."""

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_state_file(tmp_path):
    """Temporary state file for hook tests."""
    return tmp_path / "test_state.json"


@pytest.fixture
def plugin_env(tmp_state_file):
    """Environment variables for isolated hook testing."""
    return {
        **os.environ,
        "OVERMIND_URL": "http://127.0.0.1:19999",
        "OVERMIND_REPO_ID": "github.com/test/repo",
        "OVERMIND_USER": "test_user",
        "OVERMIND_STATE_FILE": str(tmp_state_file),
        "PYTHONIOENCODING": "utf-8",
    }


@pytest.fixture
def scripts_dir():
    """Path to plugin/scripts/ directory."""
    return Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def hooks_dir():
    """Path to plugin/hooks/ directory."""
    return Path(__file__).resolve().parents[1] / "hooks"
