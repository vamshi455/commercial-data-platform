"""Shared pytest fixtures for the commercial-data-platform test suite."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def repo_root() -> str:
    """Absolute path to the repository root (parent of tests/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir))


@pytest.fixture(scope="session")
def bundle_path(repo_root: str) -> str:
    """Absolute path to the root databricks.yml bundle config."""
    return os.path.join(repo_root, "databricks.yml")
