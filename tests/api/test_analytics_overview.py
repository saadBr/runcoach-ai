"""Tests for deterministic analytics API endpoints."""

from collections.abc import Iterator
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import analytics as analytics_routes
from runcoach.config import Settings, get_settings
from runcoach.db.analytics_queries import (
    AnalyticsOverview,
    AnalyticsQueryError,
    SensorCoverageSummary,
    TrainingWindowSummary,
    WorkloadSnapshot,
)
from runcoach.db.session import get_db_session
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _overview(
    *,
    as_of_date: date = date(2026, 8, 27),
) -> AnalyticsOverview:
    return AnalyticsOverview(
        as_of_date=as_of_date,
        data_start_date=date(2024, 5, 21),
        data_end_date=date(2026, 8, 23),
        total_runs=130,
        total_distance_km=1376.08,
        total_moving_hours=132.5,
        last_7_days=TrainingWindowSummary(
            days=7,
            start_date=date(2026, 8, 21),
            end_date=as_of_date,
            runs=3,
            distance_km=44.03,
            moving_hours=4.45,
        ),
        last_28_days=TrainingWindowSummary(
            days=28,
            start_date=date(2026, 7, 31),
            end_date=as_of_date,
            runs=26,
            distance_km=297.37,
            moving_hours=28.9,
        ),
        sensor_coverage=SensorCoverageSummary(
            activities_with_metrics=130,
            activities_with_heart_rate_load=85,
            average_heart_rate_coverage_pct=65.08,
            average_gps_coverage_pct=96.86,
            average_cadence_coverage_pct=65.08,
        ),
        workload=WorkloadSnapshot(
            local_date=as_of_date,
            load_method="duration_minutes_v1",
            algorithm_version="daily_load_v1",
            daily_load=0.0,
            acute_load=38.57,
            chronic_load=44.81,
            fitness_index=44.81,
            fatigue_index=38.57,
            form_index=6.24,
            coverage_pct=100.0,
        ),
    )


@pytest.fixture
def configured_client(
    client: TestClient,
) -> Iterator[TestClient]:
    fake_session = object()

    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
    )
    app.dependency_overrides[get_db_session] = lambda: fake_session

    yield client

    app.dependency_overrides.clear()


def test_overview_returns_validated_analytics_response(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[UUID, date | None]] = []

    class FakeAnalyticsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(
            self,
            *,
            athlete_id: UUID,
            as_of_date: date | None = None,
        ) -> AnalyticsOverview:
            received.append((athlete_id, as_of_date))
            return _overview()

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsQueryService",
        FakeAnalyticsQueryService,
    )

    response = configured_client.get("/api/v1/analytics/overview")

    assert response.status_code == 200
    assert received == [(ATHLETE_ID, None)]

    body = response.json()
    assert body["as_of_date"] == "2026-08-27"
    assert body["data_start_date"] == "2024-05-21"
    assert body["data_end_date"] == "2026-08-23"
    assert body["total_runs"] == 130
    assert body["total_distance_km"] == 1376.08
    assert body["last_7_days"]["runs"] == 3
    assert body["last_28_days"]["distance_km"] == 297.37
    assert body["sensor_coverage"]["activities_with_heart_rate_load"] == 85
    assert body["workload"]["form_index"] == 6.24


def test_overview_passes_requested_date_to_query_service(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[date | None] = []

    class FakeAnalyticsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(
            self,
            *,
            athlete_id: UUID,
            as_of_date: date | None = None,
        ) -> AnalyticsOverview:
            assert athlete_id == ATHLETE_ID
            received.append(as_of_date)
            assert as_of_date is not None
            return _overview(as_of_date=as_of_date)

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsQueryService",
        FakeAnalyticsQueryService,
    )

    response = configured_client.get(
        "/api/v1/analytics/overview",
        params={"as_of_date": "2026-08-26"},
    )

    assert response.status_code == 200
    assert received == [date(2026, 8, 26)]
    assert response.json()["as_of_date"] == "2026-08-26"


def test_query_error_is_returned_as_not_found(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAnalyticsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(
            self,
            *,
            athlete_id: UUID,
            as_of_date: date | None = None,
        ) -> AnalyticsOverview:
            raise AnalyticsQueryError("No calculated daily workload exists for the requested date.")

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsQueryService",
        FailingAnalyticsQueryService,
    )

    response = configured_client.get(
        "/api/v1/analytics/overview",
        params={"as_of_date": "2026-08-25"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": ("No calculated daily workload exists for the requested date.")
    }


def test_missing_athlete_configuration_returns_service_unavailable(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=None,
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    try:
        response = client.get("/api/v1/analytics/overview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Athlete configuration is unavailable."}


def test_invalid_as_of_date_is_rejected(
    configured_client: TestClient,
) -> None:
    response = configured_client.get(
        "/api/v1/analytics/overview",
        params={"as_of_date": "27-08-2026"},
    )

    assert response.status_code == 422
