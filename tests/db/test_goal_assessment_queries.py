"""Tests for personalized goal-assessment database queries."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.activity import DURATION_LOAD_METHOD
from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.base import Base
from runcoach.db.goal_assessments import (
    GoalAssessmentQueryError,
    GoalAssessmentQueryService,
)
from runcoach.db.models import Activity, Athlete, DailyLoad, PersonalBest

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
MISSING_ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000099")


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


def _activity(
    *,
    number: int,
    local_date: date,
    distance_m: str = "8000.000",
    elapsed_time_ms: int = 2_400_000,
) -> Activity:
    return Activity(
        id=UUID(f"018f0000-0000-7000-8000-{number:012d}"),
        athlete_id=ATHLETE_ID,
        sport="running",
        activity_type="unknown",
        name="Synthetic Run",
        start_time_utc=datetime.combine(local_date, datetime.min.time(), tzinfo=UTC),
        original_timezone="Africa/Casablanca",
        local_start_date=local_date,
        distance_m=Decimal(distance_m),
        moving_time_ms=elapsed_time_ms,
        elapsed_time_ms=elapsed_time_ms,
        verification_status="unverified",
    )


def _seed_assessment_evidence(session: Session) -> UUID:
    baseline = tuple(
        _activity(number=number, local_date=date(2026, 1, number), distance_m="8000.000")
        for number in range(1, 7)
    )
    candidate = _activity(
        number=20,
        local_date=date(2026, 1, 20),
        distance_m="5030.000",
        elapsed_time_ms=1_200_000,
    )
    current = tuple(
        _activity(
            number=100 + number,
            local_date=date(2026, 3, number),
            distance_m="9000.000",
        )
        for number in range(1, 7)
    )
    session.add_all((*baseline, candidate, *current))
    session.add_all(
        (
            PersonalBest(
                athlete_id=ATHLETE_ID,
                activity_id=candidate.id,
                distance_m=Decimal("5000.000"),
                elapsed_time_ms=1_181_000,
                effort_type="provider_best_effort",
                verification_status="verified_max_effort",
                verification_source="synthetic_review",
                achieved_at=candidate.start_time_utc,
                algorithm_version="synthetic_review_v1",
            ),
            DailyLoad(
                athlete_id=ATHLETE_ID,
                local_date=date(2026, 3, 31),
                load_method=DURATION_LOAD_METHOD,
                algorithm_version=DAILY_LOAD_ALGORITHM_VERSION,
                daily_load=Decimal("0.0000"),
                acute_load=Decimal("35.0000"),
                chronic_load=Decimal("40.0000"),
                fitness_index=Decimal("40.0000"),
                fatigue_index=Decimal("35.0000"),
                form_index=Decimal("5.0000"),
                coverage_pct=Decimal("100.000"),
            ),
        )
    )
    session.commit()
    return candidate.id


def test_assessment_compares_current_and_pre_pb_training(db_session: Session) -> None:
    _seed_assessment_evidence(db_session)

    report = GoalAssessmentQueryService(db_session).assess(athlete_id=ATHLETE_ID)

    assert report.as_of_date == date(2026, 3, 31)
    assert report.data_through_date == date(2026, 3, 6)
    assert report.method_status == "experimental_not_validated"
    assert len(report.assessments) == 1
    assessment = report.assessments[0]
    assert assessment.distance is StandardDistance.FIVE_K
    assert assessment.reference_pb_time == "19:41"
    assert assessment.current_42_day_block.runs == 6
    assert assessment.current_42_day_block.distance_km == 54
    assert assessment.current_42_day_block.form_index == 5
    assert assessment.reference_42_day_block.runs == 6
    assert assessment.reference_42_day_block.distance_km == 48
    assert report.unavailable_distances == (
        StandardDistance.TEN_K,
        StandardDistance.HALF_MARATHON,
        StandardDistance.MARATHON,
    )


def test_explicit_date_excludes_future_pb_evidence(db_session: Session) -> None:
    _seed_assessment_evidence(db_session)

    with pytest.raises(GoalAssessmentQueryError, match="No verified PB"):
        GoalAssessmentQueryService(db_session).assess(
            athlete_id=ATHLETE_ID,
            as_of_date=date(2026, 1, 10),
        )


def test_assessment_requires_existing_athlete(db_session: Session) -> None:
    with pytest.raises(GoalAssessmentQueryError, match="does not exist"):
        GoalAssessmentQueryService(db_session).assess(athlete_id=MISSING_ATHLETE_ID)


def test_assessment_requires_running_history(db_session: Session) -> None:
    with pytest.raises(GoalAssessmentQueryError, match="No eligible running"):
        GoalAssessmentQueryService(db_session).assess(athlete_id=ATHLETE_ID)
