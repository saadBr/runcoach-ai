"""Tests for the verified-performance analytics endpoint."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.api.routes import analytics as analytics_routes
from runcoach.config import Settings, get_settings
from runcoach.db.performance_queries import (
    PerformanceOverview,
    PerformanceQueryError,
    PersonalBestSummary,
)
from runcoach.db.session import get_db_session
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
PERSONAL_BEST_ID = UUID("018f0000-0000-7000-8000-000000000020")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000010")


def _performance_overview() -> PerformanceOverview:
    return PerformanceOverview(
        personal_bests=(
            PersonalBestSummary(
                personal_best_id=PERSONAL_BEST_ID,
                activity_id=ACTIVITY_ID,
                distance=StandardDistance.TEN_K,
                distance_m=10_000.0,
                elapsed_time_seconds=2_464.0,
                pace_seconds_per_km=246.4,
                achieved_at=datetime(2026, 3, 29, tzinfo=UTC),
                verification_status=PerformanceLabel.VERIFIED_RACE,
                effort_type=PerformanceEffortType.PROVIDER_BEST_EFFORT,
                verification_source="strava_best_effort",
                algorithm_version="strava_best_effort_import_v1",
            ),
        ),
        prediction_status="label_audit_required",
        prediction_method="training_feature_model",
        verified_labels=1,
        interpretation_role="openai_explains_validated_outputs_only",
        limitations=("No prediction is published before evaluation.",),
    )


@pytest.fixture
def configured_client(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    yield client

    app.dependency_overrides.clear()


def test_performance_returns_verified_records_and_model_readiness(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[UUID] = []

    class FakePerformanceQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(self, *, athlete_id: UUID) -> PerformanceOverview:
            received.append(athlete_id)
            return _performance_overview()

    monkeypatch.setattr(
        analytics_routes,
        "PerformanceQueryService",
        FakePerformanceQueryService,
    )

    response = configured_client.get("/api/v1/analytics/performance")

    assert response.status_code == 200
    assert received == [ATHLETE_ID]
    body = response.json()
    assert body["personal_bests"][0]["distance"] == "10k"
    assert body["personal_bests"][0]["elapsed_time_seconds"] == 2464.0
    assert body["personal_bests"][0]["verification_status"] == "verified_race"
    assert body["prediction_status"] == "label_audit_required"
    assert body["prediction_method"] == "training_feature_model"
    assert body["verified_labels"] == 1
    assert body["interpretation_role"] == "openai_explains_validated_outputs_only"
    assert len(body["limitations"]) == 1


def test_performance_query_error_is_returned_as_not_found(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPerformanceQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(self, *, athlete_id: UUID) -> PerformanceOverview:
            del athlete_id
            raise PerformanceQueryError("No verified personal bests are available.")

    monkeypatch.setattr(
        analytics_routes,
        "PerformanceQueryService",
        FailingPerformanceQueryService,
    )

    response = configured_client.get("/api/v1/analytics/performance")

    assert response.status_code == 404
    assert response.json() == {"detail": "No verified personal bests are available."}
