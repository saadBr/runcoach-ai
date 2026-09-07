"""Shared pytest fixtures."""

import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RUNCOACH_ENVIRONMENT", "test")

from runcoach.api.routes.authentication import authenticated_athlete
from runcoach.db.identity import AuthenticatedAthlete
from runcoach.main import app

TEST_ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _test_authenticated_athlete() -> AuthenticatedAthlete:
    return AuthenticatedAthlete(
        session_id=UUID("018f0000-0000-7000-8000-0000000000a1"),
        account_id=UUID("018f0000-0000-7000-8000-0000000000a2"),
        athlete_id=TEST_ATHLETE_ID,
        display_name="Synthetic Athlete",
        timezone="Africa/Casablanca",
        onboarding_status="ready",
        expires_at=datetime(2026, 10, 7, tzinfo=UTC),
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide a FastAPI test client."""

    app.dependency_overrides[authenticated_athlete] = _test_authenticated_athlete
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
