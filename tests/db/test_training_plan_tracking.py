"""Tests for persisted training-plan adherence and revision history."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.db.base import Base
from runcoach.db.models import Activity, Athlete, Goal, TrainingPlan
from runcoach.db.training_plan_tracking import (
    TrainingPlanTrackingError,
    TrainingPlanTrackingService,
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


def _payload(*, evidence_date: str, recent_km: float, first_week_km: float) -> dict[str, object]:
    return {
        "algorithm_version": "goal_plan_preview_v1",
        "as_of_date": evidence_date,
        "plan_start_date": "2026-09-07",
        "recent_weekly_distance_km": recent_km,
        "first_week": [
            {
                "scheduled_date": "2026-09-07",
                "kind": "easy",
                "title": "Easy aerobic run",
                "distance_km": 10.0,
                "pace": {
                    "faster_seconds_per_km": 330.0,
                    "slower_seconds_per_km": 390.0,
                },
            },
            {
                "scheduled_date": "2026-09-09",
                "kind": "quality",
                "title": "Threshold session",
                "distance_km": 20.0,
                "pace": None,
            },
            {
                "scheduled_date": "2026-09-13",
                "kind": "long",
                "title": "Long aerobic run",
                "distance_km": 24.0,
                "pace": {
                    "faster_seconds_per_km": 300.0,
                    "slower_seconds_per_km": 360.0,
                },
            },
        ],
        "weekly_outline": [
            {
                "week_number": 1,
                "start_date": "2026-09-07",
                "end_date": "2026-09-13",
                "phase": "base",
                "target_distance_km": first_week_km,
                "long_run_km": 24.0,
            },
            {
                "week_number": 2,
                "start_date": "2026-09-14",
                "end_date": "2026-09-20",
                "phase": "build",
                "target_distance_km": 72.0,
                "long_run_km": 26.0,
            },
        ],
    }


def _add_run(
    session: Session,
    *,
    activity_date: date,
    distance_km: float,
    name: str,
    activity_type: str,
) -> None:
    session.add(
        Activity(
            athlete_id=ATHLETE_ID,
            sport="running",
            activity_type=activity_type,
            name=name,
            start_time_utc=datetime.combine(activity_date, datetime.min.time(), tzinfo=UTC),
            original_timezone="Africa/Casablanca",
            local_start_date=activity_date,
            distance_m=Decimal(str(distance_km * 1_000)),
            moving_time_ms=3_600_000,
            elapsed_time_ms=3_600_000,
            verification_status="unverified",
        )
    )


def _add_plan_history(session: Session) -> None:
    goal = Goal(
        athlete_id=ATHLETE_ID,
        race_type="marathon",
        race_date=date(2027, 1, 31),
        target_time_seconds=None,
        days_per_week=6,
        status="active",
        priority="primary",
    )
    session.add(goal)
    session.flush()
    session.add_all(
        (
            TrainingPlan(
                goal_id=goal.id,
                version=1,
                algorithm_version="goal_plan_preview_v1",
                evidence_as_of_date=date(2026, 9, 5),
                evidence_hash="1" * 64,
                status="superseded",
                plan_payload=_payload(
                    evidence_date="2026-09-05",
                    recent_km=75.0,
                    first_week_km=68.0,
                ),
                superseded_at=datetime(2026, 9, 6, tzinfo=UTC),
            ),
            TrainingPlan(
                goal_id=goal.id,
                version=2,
                algorithm_version="goal_plan_preview_v1",
                evidence_as_of_date=date(2026, 9, 6),
                evidence_hash="2" * 64,
                status="active",
                plan_payload=_payload(
                    evidence_date="2026-09-06",
                    recent_km=80.0,
                    first_week_km=70.0,
                ),
            ),
        )
    )
    for activity_date, distance_km, name, activity_type in (
        (date(2026, 9, 7), 10.0, "Easy aerobic run", "easy"),
        (date(2026, 9, 9), 20.0, "Tempo session", "workout"),
        (date(2026, 9, 13), 25.0, "Progressive long run", "long"),
        (date(2026, 9, 14), 8.0, "Easy run", "easy"),
    ):
        _add_run(
            session,
            activity_date=activity_date,
            distance_km=distance_km,
            name=name,
            activity_type=activity_type,
        )
    session.commit()


def test_tracking_reports_current_week_volume_and_long_run(db_session: Session) -> None:
    _add_plan_history(db_session)

    result = TrainingPlanTrackingService(db_session).overview(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 9, 13),
    )

    assert result.status == "in_progress"
    assert result.active_version == 2
    assert result.current_week_number == 1
    assert result.completed_weeks == 0
    assert result.planned_distance_to_date_km == pytest.approx(70.0)
    assert result.actual_distance_to_date_km == pytest.approx(55.0)
    assert result.adherence_pct == pytest.approx(78.6)
    assert result.weeks[0].actual_runs == 3
    assert result.weeks[0].actual_long_run_km == pytest.approx(25.0)
    assert result.weeks[0].long_run_completion_pct == pytest.approx(104.2)
    assert result.weeks[1].status == "upcoming"
    assert [session.status for session in result.sessions] == [
        "completed",
        "completed",
        "completed",
    ]
    assert result.recommendation_code == "first_week_complete"


def test_tracking_marks_completed_weeks_and_returns_history(db_session: Session) -> None:
    _add_plan_history(db_session)

    result = TrainingPlanTrackingService(db_session).overview(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 9, 14),
    )

    assert result.completed_weeks == 1
    assert result.current_week_number == 2
    assert result.weeks[0].status == "completed"
    assert result.weeks[1].status == "in_progress"
    assert result.actual_distance_to_date_km == pytest.approx(63.0)
    assert [version.version for version in result.versions] == [2, 1]
    assert result.versions[0].recent_weekly_distance_km == pytest.approx(80.0)
    assert result.versions[1].status == "superseded"


def test_tracking_reports_not_started_and_requires_active_plan(db_session: Session) -> None:
    service = TrainingPlanTrackingService(db_session)
    with pytest.raises(TrainingPlanTrackingError, match="No active"):
        service.overview(athlete_id=ATHLETE_ID, as_of_date=date(2026, 9, 6))

    _add_plan_history(db_session)
    result = service.overview(athlete_id=ATHLETE_ID, as_of_date=date(2026, 9, 6))

    assert result.status == "not_started"
    assert result.current_week_number is None
    assert result.adherence_pct is None
    assert result.actual_distance_to_date_km == 0
    assert result.sessions[0].status == "upcoming"
    assert result.recommendation_code == "plan_not_started"


def test_tracking_does_not_reschedule_missed_quality_work(db_session: Session) -> None:
    _add_plan_history(db_session)
    db_session.execute(delete(Activity).where(Activity.local_start_date == date(2026, 9, 9)))
    db_session.commit()

    result = TrainingPlanTrackingService(db_session).overview(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 9, 10),
    )

    assert result.sessions[1].status == "missed"
    assert result.recommendation_code == "avoid_makeup_quality"
    assert "Do not stack" in result.recommendation
