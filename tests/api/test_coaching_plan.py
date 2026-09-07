"""Tests for the goal-based training-plan preview endpoint."""

from collections.abc import Iterator
from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
    GoalStatus,
    PaceRange,
    PlannedSession,
    PlannedSessionKind,
    PlannedWeek,
    PlanPhase,
    TrainingGoal,
    TrainingPlanPreview,
)
from runcoach.api.routes import coaching as coaching_routes
from runcoach.config import Settings, get_settings
from runcoach.db.session import get_db_session
from runcoach.db.training_plans import PersistedTrainingPlan, TrainingPlanQueryError
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _preview() -> TrainingPlanPreview:
    goal = TrainingGoal(
        distance=StandardDistance.MARATHON,
        race_date=date(2026, 11, 29),
        target_time_seconds=11_400.0,
        days_per_week=6,
    )
    return TrainingPlanPreview(
        algorithm_version="goal_plan_preview_v1",
        status="preview_not_persisted",
        as_of_date=date(2026, 9, 4),
        plan_start_date=date(2026, 9, 7),
        goal=goal,
        goal_status=GoalStatus.ACHIEVABLE,
        weeks_to_race=12,
        fitness_potential_seconds=11_388.665,
        current_readiness_seconds=11_461.396,
        recommended_target_seconds=11_461.396,
        target_gap_seconds=-61.396,
        current_preparation_score=0.92,
        recent_weekly_distance_km=77.972,
        first_week=(
            PlannedSession(
                scheduled_date=date(2026, 9, 8),
                kind=PlannedSessionKind.QUALITY,
                title="3 x 4 km at controlled marathon effort",
                distance_km=12.0,
                pace=PaceRange(266.6, 276.6),
                purpose="Develop marathon pace and fueling durability.",
            ),
        ),
        weekly_outline=(
            PlannedWeek(
                week_number=1,
                start_date=date(2026, 9, 7),
                end_date=date(2026, 9, 13),
                phase=PlanPhase.BASE,
                target_distance_km=71.7,
                long_run_km=22.9,
                quality_focus="marathon pace and fueling durability",
            ),
        ),
        rationale=("Synthetic rationale.",),
        guardrails=("Synthetic guardrail.",),
    )


def _persisted(*, created: bool) -> PersistedTrainingPlan:
    payload = coaching_routes.TrainingPlanPreviewResponse.model_validate(_preview()).model_dump(
        mode="json"
    )
    return PersistedTrainingPlan(
        goal_id=UUID("018f0000-0000-7000-8000-000000000010"),
        plan_id=UUID("018f0000-0000-7000-8000-000000000011"),
        version=1,
        created=created,
        preview=payload,
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


def test_plan_preview_returns_typed_goal_and_sessions(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[UUID, StandardDistance, date, float | None, int]] = []

    class FakeTrainingPlanQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def preview(
            self,
            *,
            athlete_id: UUID,
            distance: StandardDistance,
            race_date: date,
            target_time_seconds: float | None,
            days_per_week: int,
        ) -> TrainingPlanPreview:
            requests.append((athlete_id, distance, race_date, target_time_seconds, days_per_week))
            return _preview()

    monkeypatch.setattr(
        coaching_routes,
        "TrainingPlanQueryService",
        FakeTrainingPlanQueryService,
    )

    response = configured_client.get(
        "/api/v1/coaching/plan-preview",
        params={
            "distance": "marathon",
            "race_date": "2026-11-29",
            "target_time_seconds": 11_400,
            "days_per_week": 6,
        },
    )

    assert response.status_code == 200
    assert requests == [
        (
            ATHLETE_ID,
            StandardDistance.MARATHON,
            date(2026, 11, 29),
            11_400.0,
            6,
        )
    ]
    body = response.json()
    assert body["algorithm_version"] == "goal_plan_preview_v1"
    assert body["goal_status"] == "achievable"
    assert body["goal"]["distance"] == "marathon"
    assert body["first_week"][0]["kind"] == "quality"
    assert body["weekly_outline"][0]["phase"] == "base"


def test_plan_preview_validates_query_parameters(configured_client: TestClient) -> None:
    response = configured_client.get(
        "/api/v1/coaching/plan-preview",
        params={
            "distance": "marathon",
            "race_date": "2026-11-29",
            "days_per_week": 2,
        },
    )

    assert response.status_code == 422


def test_plan_preview_returns_domain_error(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTrainingPlanQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def preview(self, **kwargs: object) -> TrainingPlanPreview:
            del kwargs
            raise TrainingPlanQueryError("Race date must allow at least two training weeks.")

    monkeypatch.setattr(
        coaching_routes,
        "TrainingPlanQueryService",
        FailingTrainingPlanQueryService,
    )

    response = configured_client.get(
        "/api/v1/coaching/plan-preview",
        params={"distance": "5k", "race_date": "2026-09-10"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Race date must allow at least two training weeks."}


def test_plan_preview_uses_authenticated_athlete_without_configured_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTrainingPlanQueryService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def preview(self, **kwargs: object) -> TrainingPlanPreview:
            assert kwargs["athlete_id"] == ATHLETE_ID
            return _preview()

    monkeypatch.setattr(
        coaching_routes,
        "TrainingPlanQueryService",
        FakeTrainingPlanQueryService,
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=None,
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    response = client.get(
        "/api/v1/coaching/plan-preview",
        params={"distance": "5k", "race_date": "2026-11-29"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_active_plan_can_be_saved_loaded_and_refreshed(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeTrainingPlanPersistenceService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def create_or_refresh(self, **kwargs: object) -> PersistedTrainingPlan:
            assert kwargs["athlete_id"] == ATHLETE_ID
            calls.append("save")
            return _persisted(created=True)

        def load_active(self, **kwargs: object) -> PersistedTrainingPlan:
            assert kwargs["athlete_id"] == ATHLETE_ID
            calls.append("load")
            return _persisted(created=False)

        def refresh_active(self, **kwargs: object) -> PersistedTrainingPlan:
            assert kwargs["athlete_id"] == ATHLETE_ID
            calls.append("refresh")
            return _persisted(created=False)

    monkeypatch.setattr(
        coaching_routes,
        "TrainingPlanPersistenceService",
        FakeTrainingPlanPersistenceService,
    )

    saved = configured_client.post(
        "/api/v1/coaching/plans/active",
        params={
            "distance": "marathon",
            "race_date": "2027-01-31",
            "target_time_seconds": 11_400,
            "days_per_week": 6,
        },
    )
    loaded = configured_client.get("/api/v1/coaching/plans/active")
    refreshed = configured_client.post("/api/v1/coaching/plans/active/refresh")

    assert [saved.status_code, loaded.status_code, refreshed.status_code] == [200, 200, 200]
    assert calls == ["save", "load", "refresh"]
    assert saved.json()["created"] is True
    assert loaded.json()["preview"]["goal"]["distance"] == "marathon"
    assert refreshed.json()["version"] == 1
