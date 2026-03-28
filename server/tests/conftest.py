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


def pytest_addoption(parser):
    parser.addoption("--student-n", type=int, default=3,
                     help="Number of student (Overmind-enabled) iterations for statistical tests")
    parser.addoption("--naive-m", type=int, default=3,
                     help="Number of naive (no-Overmind) iterations for statistical tests")
    parser.addoption("--agent-model", type=str, default="",
                     help="Claude model for all agents (haiku/sonnet/opus)")


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for store tests."""
    return tmp_path / "data"
