"""Shared pytest fixtures."""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RUNCOACH_ENVIRONMENT", "test")

from runcoach.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide a FastAPI test client."""

    with TestClient(app) as test_client:
        yield test_client
