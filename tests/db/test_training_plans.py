"""Tests for training-plan query orchestration."""

from datetime import date
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from runcoach.analytics.current_fitness import CurrentFitnessAssessment
from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import TrainingGoal, TrainingPlanPreview
from runcoach.db import training_plans
from runcoach.db.performance_queries import PerformanceQueryError
from runcoach.db.training_plans import TrainingPlanQueryError, TrainingPlanQueryService

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def test_preview_builds_goal_from_request_and_current_fitness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fitness = cast(CurrentFitnessAssessment, object())
    expected = cast(TrainingPlanPreview, object())
    captured: list[tuple[UUID, TrainingGoal, CurrentFitnessAssessment]] = []

    class FakePerformanceQueryService:
        def __init__(self, session: Session) -> None:
            assert session is not None

        def overview(self, *, athlete_id: UUID) -> object:
            class Overview:
                current_fitness = fitness

            self.athlete_id = athlete_id
            return Overview()

    def fake_build_training_plan_preview(
        *,
        goal: TrainingGoal,
        fitness: CurrentFitnessAssessment,
    ) -> TrainingPlanPreview:
        captured.append((ATHLETE_ID, goal, fitness))
        return expected

    monkeypatch.setattr(
        training_plans,
        "PerformanceQueryService",
        FakePerformanceQueryService,
    )
    monkeypatch.setattr(
        training_plans,
        "build_training_plan_preview",
        fake_build_training_plan_preview,
    )

    result = TrainingPlanQueryService(cast(Session, object())).preview(
        athlete_id=ATHLETE_ID,
        distance=StandardDistance.HALF_MARATHON,
        race_date=date(2026, 11, 29),
        target_time_seconds=5_100.0,
        days_per_week=5,
    )

    assert result is expected
    assert captured[0][0] == ATHLETE_ID
    assert captured[0][1] == TrainingGoal(
        distance=StandardDistance.HALF_MARATHON,
        race_date=date(2026, 11, 29),
        target_time_seconds=5_100.0,
        days_per_week=5,
    )
    assert captured[0][2] is fitness


@pytest.mark.parametrize(
    "error",
    (
        PerformanceQueryError("No verified performance."),
        ValueError("Race date must allow at least two training weeks."),
    ),
)
def test_preview_translates_evidence_and_goal_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    class FailingPerformanceQueryService:
        def __init__(self, session: Session) -> None:
            assert session is not None

        def overview(self, *, athlete_id: UUID) -> object:
            del athlete_id
            raise error

    monkeypatch.setattr(
        training_plans,
        "PerformanceQueryService",
        FailingPerformanceQueryService,
    )

    with pytest.raises(TrainingPlanQueryError, match=str(error)):
        TrainingPlanQueryService(cast(Session, object())).preview(
            athlete_id=ATHLETE_ID,
            distance=StandardDistance.FIVE_K,
            race_date=date(2026, 11, 29),
            target_time_seconds=None,
            days_per_week=4,
        )
