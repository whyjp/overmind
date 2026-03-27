"""Test configuration and shared fixtures.

Port allocation for scenario tests (must not conflict):
  17777 — test_hooks_e2e.py
  17888 — test_multi_agent_sim.py
  17999 — test_live_agents.py
  18888 — test_e2e_server.py

These tests run sequentially (not pytest-xdist). If parallel execution
is needed, use dynamic port allocation instead of fixed ports.
"""

import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for store tests."""
    return tmp_path / "data"
