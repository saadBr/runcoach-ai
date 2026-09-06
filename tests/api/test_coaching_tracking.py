"""Tests for active training-plan adherence and revision history API."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import coaching as coaching_routes
from runcoach.config import Settings, get_settings
from runcoach.db.session import get_db_session
from runcoach.db.training_plan_tracking import (
    ActivePlanTracking,
    PlanSessionProgress,
    PlanVersionSummary,
    PlanWeekProgress,
    TrainingPlanTrackingError,
)
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
GOAL_ID = UUID("018f0000-0000-7000-8000-000000000010")
PLAN_ID = UUID("018f0000-0000-7000-8000-000000000011")


@pytest.fixture
def configured_client(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
    )
    app.dependency_overrides[get_db_session] = lambda: object()
    yield client
    app.dependency_overrides.clear()


def _tracking() -> ActivePlanTracking:
    return ActivePlanTracking(
        goal_id=GOAL_ID,
        plan_id=PLAN_ID,
        active_version=2,
        as_of_date=date(2026, 9, 13),
        plan_start_date=date(2026, 9, 7),
        race_date=date(2027, 1, 31),
        status="in_progress",
        completed_weeks=0,
        total_weeks=21,
        current_week_number=1,
        planned_distance_to_date_km=70.0,
        actual_distance_to_date_km=72.0,
        adherence_pct=102.9,
        weeks=(
            PlanWeekProgress(
                week_number=1,
                start_date=date(2026, 9, 7),
                end_date=date(2026, 9, 13),
                phase="base",
                status="in_progress",
                target_distance_km=70.0,
                target_long_run_km=24.0,
                actual_runs=6,
                actual_distance_km=72.0,
                actual_long_run_km=25.0,
                distance_completion_pct=102.9,
                long_run_completion_pct=104.2,
            ),
        ),
        sessions=(
            PlanSessionProgress(
                scheduled_date=date(2026, 9, 13),
                kind="long",
                title="Long aerobic run",
                target_distance_km=24.0,
                status="completed",
                matched_activity_date=date(2026, 9, 13),
                matched_activity_name="Progressive long run",
                actual_distance_km=25.0,
                actual_pace_seconds_per_km=330.0,
                classified_as="progressive",
                distance_completion_pct=104.2,
                pace_status="within_range",
            ),
        ),
        recommendation_code="continue_as_planned",
        recommendation="Continue with the next scheduled session.",
        versions=(
            PlanVersionSummary(
                plan_id=PLAN_ID,
                version=2,
                status="active",
                evidence_as_of_date=date(2026, 9, 6),
                created_at=datetime(2026, 9, 6, tzinfo=UTC),
                superseded_at=None,
                recent_weekly_distance_km=80.0,
                first_week_target_km=70.0,
                peak_week_target_km=85.0,
                peak_long_run_km=32.0,
            ),
        ),
    )


def test_tracking_endpoint_returns_typed_plan_progress(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[UUID, date | None]] = []

    class FakeTrackingService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(
            self,
            *,
            athlete_id: UUID,
            as_of_date: date | None,
        ) -> ActivePlanTracking:
            requests.append((athlete_id, as_of_date))
            return _tracking()

    monkeypatch.setattr(coaching_routes, "TrainingPlanTrackingService", FakeTrackingService)

    response = configured_client.get(
        "/api/v1/coaching/plans/active/tracking",
        params={"as_of_date": "2026-09-13"},
    )

    assert response.status_code == 200
    assert requests == [(ATHLETE_ID, date(2026, 9, 13))]
    body = response.json()
    assert body["active_version"] == 2
    assert body["adherence_pct"] == pytest.approx(102.9)
    assert body["weeks"][0]["actual_long_run_km"] == pytest.approx(25.0)
    assert body["sessions"][0]["status"] == "completed"
    assert body["recommendation_code"] == "continue_as_planned"
    assert body["versions"][0]["status"] == "active"


def test_tracking_endpoint_translates_missing_plan(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingTrackingService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def overview(self, **kwargs: object) -> ActivePlanTracking:
            del kwargs
            raise TrainingPlanTrackingError("No active persisted training plan exists.")

    monkeypatch.setattr(coaching_routes, "TrainingPlanTrackingService", MissingTrackingService)

    response = configured_client.get("/api/v1/coaching/plans/active/tracking")

    assert response.status_code == 404
    assert response.json() == {"detail": "No active persisted training plan exists."}
