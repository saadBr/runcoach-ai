"""Tests for the analytics trends API endpoint."""

from collections.abc import Iterator
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import analytics as analytics_routes
from runcoach.config import Settings, get_settings
from runcoach.db.analytics_queries import WorkloadSnapshot
from runcoach.db.analytics_trends import (
    AnalyticsTrends,
    AnalyticsTrendsQueryError,
    WeeklyTrainingSummary,
)
from runcoach.db.session import get_db_session
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _trends(
    *,
    end_date: date = date(2026, 8, 27),
    requested_weeks: int = 2,
) -> AnalyticsTrends:
    start_date = date(2026, 8, 17)

    return AnalyticsTrends(
        start_date=start_date,
        end_date=end_date,
        requested_weeks=requested_weeks,
        weekly_training=(
            WeeklyTrainingSummary(
                week_start=date(2026, 8, 17),
                week_end=date(2026, 8, 23),
                runs=6,
                distance_km=76.04,
                moving_hours=7.68,
                duration_load_minutes=460.8,
                weighted_pace_seconds_per_km=363.7,
                elevation_gain_m=820.0,
                heart_rate_load_activities=6,
                edwards_trimp=1155.44,
            ),
            WeeklyTrainingSummary(
                week_start=date(2026, 8, 24),
                week_end=end_date,
                runs=0,
                distance_km=0.0,
                moving_hours=0.0,
                duration_load_minutes=0.0,
                weighted_pace_seconds_per_km=None,
                elevation_gain_m=None,
                heart_rate_load_activities=0,
                edwards_trimp=None,
            ),
        ),
        daily_workload=(
            WorkloadSnapshot(
                local_date=date(2026, 8, 26),
                load_method="duration_minutes_v1",
                algorithm_version="daily_load_v1",
                daily_load=0.0,
                acute_load=45.0,
                chronic_load=45.9,
                fitness_index=45.9,
                fatigue_index=45.0,
                form_index=0.9,
                coverage_pct=100.0,
            ),
            WorkloadSnapshot(
                local_date=end_date,
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
        ),
    )


@pytest.fixture
def configured_client(
    client: TestClient,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    yield client

    app.dependency_overrides.clear()


def test_trends_returns_weekly_and_daily_series(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[UUID, int, date | None]] = []

    class FakeTrendsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def trends(
            self,
            *,
            athlete_id: UUID,
            weeks: int = 12,
            end_date: date | None = None,
        ) -> AnalyticsTrends:
            received.append((athlete_id, weeks, end_date))
            return _trends(requested_weeks=weeks)

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsTrendsQueryService",
        FakeTrendsQueryService,
    )

    response = configured_client.get("/api/v1/analytics/trends")

    assert response.status_code == 200
    assert received == [(ATHLETE_ID, 12, None)]

    body = response.json()
    assert body["start_date"] == "2026-08-17"
    assert body["end_date"] == "2026-08-27"
    assert body["requested_weeks"] == 12
    assert body["weekly_training"][0]["runs"] == 6
    assert body["weekly_training"][0]["distance_km"] == 76.04
    assert body["weekly_training"][0]["weighted_pace_seconds_per_km"] == 363.7
    assert body["weekly_training"][1]["edwards_trimp"] is None
    assert body["daily_workload"][-1]["form_index"] == 6.24


def test_trends_passes_query_parameters(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[int, date | None]] = []

    class FakeTrendsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def trends(
            self,
            *,
            athlete_id: UUID,
            weeks: int = 12,
            end_date: date | None = None,
        ) -> AnalyticsTrends:
            assert athlete_id == ATHLETE_ID
            received.append((weeks, end_date))
            assert end_date is not None
            return _trends(
                end_date=end_date,
                requested_weeks=weeks,
            )

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsTrendsQueryService",
        FakeTrendsQueryService,
    )

    response = configured_client.get(
        "/api/v1/analytics/trends",
        params={
            "weeks": 2,
            "end_date": "2026-08-26",
        },
    )

    assert response.status_code == 200
    assert received == [(2, date(2026, 8, 26))]
    assert response.json()["end_date"] == "2026-08-26"


def test_trends_query_error_is_returned_as_not_found(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTrendsQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def trends(
            self,
            *,
            athlete_id: UUID,
            weeks: int = 12,
            end_date: date | None = None,
        ) -> AnalyticsTrends:
            raise AnalyticsTrendsQueryError(
                "No calculated daily workload exists for the requested end date."
            )

    monkeypatch.setattr(
        analytics_routes,
        "AnalyticsTrendsQueryService",
        FailingTrendsQueryService,
    )

    response = configured_client.get(
        "/api/v1/analytics/trends",
        params={"end_date": "2026-08-16"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": ("No calculated daily workload exists for the requested end date.")
    }


@pytest.mark.parametrize("weeks", [0, 53])
def test_trends_rejects_invalid_week_count(
    configured_client: TestClient,
    weeks: int,
) -> None:
    response = configured_client.get(
        "/api/v1/analytics/trends",
        params={"weeks": weeks},
    )

    assert response.status_code == 422
