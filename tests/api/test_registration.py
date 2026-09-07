"""Tests for new-athlete registration and pending account state."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import authentication as authentication_routes
from runcoach.db.identity import (
    AuthenticatedAthlete,
    IdentityConflictError,
    NewAthleteRegistration,
    RegisteredAthlete,
)
from runcoach.db.session import get_db_session
from runcoach.main import app

ACCESS_TOKEN = "pending-opaque-test-token-with-sufficient-length"
ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000051")
ACCOUNT_ID = UUID("018f0000-0000-7000-8000-000000000052")
GOAL_ID = UUID("018f0000-0000-7000-8000-000000000053")
SESSION_ID = UUID("018f0000-0000-7000-8000-000000000054")
EXPIRES_AT = datetime(2026, 10, 7, 12, tzinfo=UTC)


def _pending_identity() -> AuthenticatedAthlete:
    return AuthenticatedAthlete(
        session_id=SESSION_ID,
        account_id=ACCOUNT_ID,
        athlete_id=ATHLETE_ID,
        display_name="New Athlete",
        timezone="Africa/Casablanca",
        onboarding_status="awaiting_strava_archive",
        expires_at=EXPIRES_AT,
    )


def _payload() -> dict[str, object]:
    return {
        "display_name": "New Athlete",
        "email": "new@example.com",
        "password": "new athlete private password",
        "timezone": "Africa/Casablanca",
        "goal_distance": "marathon",
        "race_date": "2027-01-31",
        "target_time_seconds": 12_600,
        "days_per_week": 5,
        "benchmark_distance": "5k",
        "benchmark_elapsed_time_seconds": 1_200.25,
        "benchmark_date": "2026-09-01",
        "benchmark_label": "verified_max_effort",
        "research_consent": True,
    }


@pytest.fixture
def registration_client(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_db_session] = lambda: object()
    yield client
    app.dependency_overrides.clear()


def test_registration_returns_pending_session_and_converts_benchmark_time(
    registration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[NewAthleteRegistration] = []

    class FakeRegistrationService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def register(self, registration: NewAthleteRegistration) -> RegisteredAthlete:
            captured.append(registration)
            return RegisteredAthlete(
                access_token=ACCESS_TOKEN,
                identity=_pending_identity(),
                goal_id=GOAL_ID,
            )

    monkeypatch.setattr(
        authentication_routes,
        "NewAthleteRegistrationService",
        FakeRegistrationService,
    )

    response = registration_client.post("/api/v1/auth/register", json=_payload())

    assert response.status_code == 201
    assert response.json()["access_token"] == ACCESS_TOKEN
    assert response.json()["athlete"]["onboarding_status"] == "awaiting_strava_archive"
    assert captured[0].benchmark_elapsed_time_ms == 1_200_250
    assert captured[0].race_date == date(2027, 1, 31)
    assert captured[0].research_consent


def test_registration_conflict_is_explicit_but_private(
    registration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConflictingRegistrationService:
        def __init__(self, session: object) -> None:
            del session

        def register(self, registration: NewAthleteRegistration) -> RegisteredAthlete:
            del registration
            raise IdentityConflictError("private conflict detail")

    monkeypatch.setattr(
        authentication_routes,
        "NewAthleteRegistrationService",
        ConflictingRegistrationService,
    )

    response = registration_client.post("/api/v1/auth/register", json=_payload())

    assert response.status_code == 409
    assert response.json() == {"detail": "An account already uses that email address."}
    assert "private conflict detail" not in response.text


def test_registration_requires_valid_benchmark_and_password(
    registration_client: TestClient,
) -> None:
    invalid = _payload()
    invalid["password"] = "short"
    invalid["benchmark_elapsed_time_seconds"] = 0

    response = registration_client.post("/api/v1/auth/register", json=invalid)

    assert response.status_code == 422
