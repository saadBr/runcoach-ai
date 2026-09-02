"""Tests for transactional personal-best persistence."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.db.base import Base
from runcoach.db.models import Activity, Athlete, PersonalBest
from runcoach.db.personal_bests import (
    PersonalBestConflictError,
    PersonalBestError,
    PersonalBestInput,
    PersonalBestService,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
FIRST_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000010")
SECOND_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000011")


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        session.add(
            Athlete(
                id=ATHLETE_ID,
                display_name="Synthetic Athlete",
                timezone="Africa/Casablanca",
            )
        )
        session.add_all(
            (
                _activity(FIRST_ACTIVITY_ID, day=1),
                _activity(SECOND_ACTIVITY_ID, day=2),
            )
        )
        session.commit()
        yield session

    engine.dispose()


def _activity(activity_id: UUID, *, day: int) -> Activity:
    return Activity(
        id=activity_id,
        athlete_id=ATHLETE_ID,
        sport="running",
        activity_type="unknown",
        name="Synthetic Run",
        start_time_utc=datetime(2026, 1, day, tzinfo=UTC),
        original_timezone="Africa/Casablanca",
        local_start_date=date(2026, 1, day),
        distance_m=Decimal("5010.000"),
        moving_time_ms=1_200_000,
        elapsed_time_ms=1_202_000,
        verification_status="unverified",
    )


def _input(
    *,
    activity_id: UUID = FIRST_ACTIVITY_ID,
    elapsed_time_ms: int = 1_181_000,
) -> PersonalBestInput:
    return PersonalBestInput(
        athlete_id=ATHLETE_ID,
        activity_id=activity_id,
        distance=StandardDistance.FIVE_K,
        elapsed_time_ms=elapsed_time_ms,
        label=PerformanceLabel.VERIFIED_MAX_EFFORT,
    )


def test_record_is_created_and_identical_request_is_reused(db_session: Session) -> None:
    service = PersonalBestService(db_session)

    first = service.record(_input())
    second = service.record(_input())

    assert first.created is True
    assert second.created is False
    assert second.personal_best_id == first.personal_best_id
    assert db_session.scalar(select(func.count()).select_from(PersonalBest)) == 1

    personal_best = db_session.get(PersonalBest, first.personal_best_id)
    assert personal_best is not None
    assert personal_best.elapsed_time_ms == 1_181_000
    assert personal_best.verification_source == "strava_best_effort"
    assert personal_best.effort_type == "provider_best_effort"


def test_faster_later_result_supersedes_current_record(db_session: Session) -> None:
    service = PersonalBestService(db_session)
    first = service.record(_input())
    second = service.record(
        _input(
            activity_id=SECOND_ACTIVITY_ID,
            elapsed_time_ms=1_128_000,
        )
    )

    assert second.created is True
    assert second.superseded_personal_best_id == first.personal_best_id

    previous = db_session.get(PersonalBest, first.personal_best_id)
    current = db_session.get(PersonalBest, second.personal_best_id)
    assert previous is not None
    assert current is not None
    assert previous.superseded_at == current.achieved_at
    assert current.superseded_at is None


def test_slower_later_result_is_rejected(db_session: Session) -> None:
    service = PersonalBestService(db_session)
    service.record(_input())

    with pytest.raises(PersonalBestConflictError, match="does not improve"):
        service.record(
            _input(
                activity_id=SECOND_ACTIVITY_ID,
                elapsed_time_ms=1_200_000,
            )
        )

    assert db_session.scalar(select(func.count()).select_from(PersonalBest)) == 1


def test_missing_activity_is_rejected(db_session: Session) -> None:
    with pytest.raises(PersonalBestError, match="eligible running activity"):
        PersonalBestService(db_session).record(
            _input(
                activity_id=UUID("018f0000-0000-7000-8000-000000000099"),
            )
        )


def test_input_rejects_nonpositive_time() -> None:
    with pytest.raises(ValueError, match="positive"):
        _input(elapsed_time_ms=0)
