import os
import sys
import pytest
from pathlib import Path

# Add the project root to Python path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory as a Path object."""
    return Path(__file__).parent.parent

@pytest.fixture(scope="session")
def sister_sto_root():
    """Return the sister_sto package root directory as a Path object."""
    return Path(__file__).parent.parent / "sister_sto"

@pytest.fixture(scope="session")
def test_resources():
    """Return the test resources directory as a Path object."""
    return Path(__file__).parent / "resources" 