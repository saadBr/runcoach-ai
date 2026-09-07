"""Tests for the authenticated required Strava archive boundary."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import authentication as authentication_routes
from runcoach.api.routes import onboarding as onboarding_routes
from runcoach.db.session import get_db_session
from runcoach.main import app
from runcoach.onboarding.service import CompletedOnboarding, OnboardingError

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000061")
PLAN_ID = UUID("018f0000-0000-7000-8000-000000000062")


@pytest.fixture
def onboarding_client(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    app.dependency_overrides[authentication_routes.onboarding_athlete] = lambda: SimpleNamespace(
        athlete_id=ATHLETE_ID
    )
    app.dependency_overrides[get_db_session] = lambda: object()
    monkeypatch.setattr(
        "runcoach.api.routes.onboarding.get_settings",
        lambda: SimpleNamespace(private_data_dir=tmp_path),
    )
    yield client
    app.dependency_overrides.clear()


def test_archive_upload_uses_private_temporary_storage_and_returns_plan(
    onboarding_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[UUID, bytes, bool]] = []

    class FakeOnboardingService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def process_archive(
            self,
            *,
            athlete_id: UUID,
            archive_path: Path,
            extraction_directory: Path,
        ) -> CompletedOnboarding:
            observed.append((athlete_id, archive_path.read_bytes(), extraction_directory.is_dir()))
            return CompletedOnboarding(
                status="ready",
                canonical_runs=42,
                sensor_runs=40,
                parser_findings=0,
                plan_id=PLAN_ID,
            )

    monkeypatch.setattr(onboarding_routes, "StravaOnboardingService", FakeOnboardingService)

    response = onboarding_client.post(
        "/api/v1/onboarding/strava-archive",
        content=b"synthetic zip bytes",
        headers={"X-RunCoach-Filename": "strava-export.zip"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "canonical_runs": 42,
        "sensor_runs": 40,
        "parser_findings": 0,
        "plan_id": str(PLAN_ID),
    }
    assert observed == [(ATHLETE_ID, b"synthetic zip bytes", False)]


def test_archive_upload_rejects_wrong_extension_and_empty_body(
    onboarding_client: TestClient,
) -> None:
    wrong_extension = onboarding_client.post(
        "/api/v1/onboarding/strava-archive",
        content=b"data",
        headers={"X-RunCoach-Filename": "activities.csv"},
    )
    empty = onboarding_client.post(
        "/api/v1/onboarding/strava-archive",
        content=b"",
        headers={"X-RunCoach-Filename": "strava.zip"},
    )

    assert wrong_extension.status_code == 422
    assert empty.status_code == 422


def test_archive_pipeline_errors_expose_only_sanitized_code_and_message(
    onboarding_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingOnboardingService:
        def __init__(self, session: object) -> None:
            del session

        def process_archive(self, **kwargs: object) -> CompletedOnboarding:
            del kwargs
            raise OnboardingError("MISSING_ACTIVITIES_CSV", "Archive lacks activities.csv.")

    monkeypatch.setattr(onboarding_routes, "StravaOnboardingService", FailingOnboardingService)

    response = onboarding_client.post(
        "/api/v1/onboarding/strava-archive",
        content=b"bad zip",
        headers={"X-RunCoach-Filename": "strava.zip"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "MISSING_ACTIVITIES_CSV",
        "message": "Archive lacks activities.csv.",
    }
