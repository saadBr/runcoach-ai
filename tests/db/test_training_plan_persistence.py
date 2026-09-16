"""Tests for durable, versioned training-plan persistence."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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
from runcoach.db.base import Base
from runcoach.db.models import Athlete, Goal, TrainingPlan
from runcoach.db.training_plans import (
    PersistedTrainingPlan,
    TrainingPlanPersistenceService,
    TrainingPlanQueryError,
    TrainingPlanQueryService,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            Athlete(
                id=ATHLETE_ID,
                display_name="Synthetic Athlete",
                timezone="Africa/Casablanca",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _preview(*, as_of_date: date = date(2026, 9, 4)) -> TrainingPlanPreview:
    return TrainingPlanPreview(
        algorithm_version="goal_plan_preview_v1",
        status="preview_not_persisted",
        as_of_date=as_of_date,
        plan_start_date=date(2026, 9, 7),
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=11_400,
            days_per_week=6,
        ),
        goal_status=GoalStatus.ACHIEVABLE,
        weeks_to_race=21,
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
                title="Marathon effort",
                distance_km=18,
                pace=PaceRange(266, 276),
                purpose="Develop marathon durability.",
            ),
        ),
        weekly_outline=(
            PlannedWeek(
                week_number=1,
                start_date=date(2026, 9, 7),
                end_date=date(2026, 9, 13),
                phase=PlanPhase.BASE,
                target_distance_km=68.9,
                long_run_km=22,
                quality_focus="marathon durability",
            ),
        ),
        rationale=("Synthetic rationale.",),
        guardrails=("Synthetic guardrail.",),
    )


def _stub_preview(
    monkeypatch: pytest.MonkeyPatch,
    preview: TrainingPlanPreview,
) -> None:
    def fake_preview(
        self: TrainingPlanQueryService,
        **kwargs: object,
    ) -> TrainingPlanPreview:
        del self, kwargs
        return preview

    monkeypatch.setattr(TrainingPlanQueryService, "preview", fake_preview)


def _persist(service: TrainingPlanPersistenceService) -> PersistedTrainingPlan:
    return service.create_or_refresh(
        athlete_id=ATHLETE_ID,
        distance=StandardDistance.MARATHON,
        race_date=date(2027, 1, 31),
        target_time_seconds=11_400,
        days_per_week=6,
    )


def test_create_and_identical_refresh_are_idempotent(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_preview(monkeypatch, _preview())
    service = TrainingPlanPersistenceService(db_session)

    first = _persist(service)
    second = _persist(service)

    assert first.created is True
    assert first.version == 1
    assert second.created is False
    assert second.plan_id == first.plan_id
    assert db_session.scalar(select(func.count()).select_from(Goal)) == 1
    assert db_session.scalar(select(func.count()).select_from(TrainingPlan)) == 1


def test_changed_evidence_creates_new_version_and_supersedes_previous(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TrainingPlanPersistenceService(db_session)
    _stub_preview(monkeypatch, _preview())
    first = _persist(service)
    changed = replace(
        _preview(as_of_date=date(2026, 9, 11)),
        recent_weekly_distance_km=80.5,
    )
    _stub_preview(monkeypatch, changed)

    second = _persist(service)

    assert second.created is True
    assert second.version == 2
    assert second.plan_id != first.plan_id
    rows = list(db_session.scalars(select(TrainingPlan).order_by(TrainingPlan.version)))
    assert [row.status for row in rows] == ["superseded", "active"]
    assert rows[0].superseded_at is not None


def test_load_and_refresh_active_plan(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TrainingPlanPersistenceService(db_session)
    with pytest.raises(TrainingPlanQueryError, match="No active"):
        service.load_active(athlete_id=ATHLETE_ID)
    db_session.rollback()

    _stub_preview(monkeypatch, _preview())
    created = _persist(service)
    loaded = service.load_active(athlete_id=ATHLETE_ID)
    db_session.rollback()
    captured_start_dates: list[date | None] = []

    def refreshed_preview(
        self: TrainingPlanQueryService,
        **kwargs: object,
    ) -> TrainingPlanPreview:
        del self
        start_date = kwargs.get("plan_start_date")
        assert start_date is None or isinstance(start_date, date)
        captured_start_dates.append(start_date)
        return _preview()

    monkeypatch.setattr(TrainingPlanQueryService, "preview", refreshed_preview)
    refreshed = service.refresh_active(athlete_id=ATHLETE_ID)

    assert loaded.plan_id == created.plan_id
    assert loaded.preview["goal"]["race_date"] == "2027-01-31"
    assert refreshed.created is False
    assert refreshed.version == 1
    assert captured_start_dates == [date(2026, 9, 7)]
