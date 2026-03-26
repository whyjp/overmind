import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for store tests."""
    return tmp_path / "data"
