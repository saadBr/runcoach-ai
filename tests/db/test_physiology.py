"""Tests for time-valid physiology-profile persistence."""

from collections.abc import Iterator
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.db.base import Base
from runcoach.db.models import Athlete, PhysiologyProfile
from runcoach.db.physiology import (
    PhysiologyProfileConflictError,
    PhysiologyProfileError,
    PhysiologyProfileInput,
    PhysiologyProfileService,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


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
                display_name="Test Athlete",
                timezone="Africa/Casablanca",
            )
        )
        session.commit()
        yield session

    engine.dispose()


def _profile_input(
    *,
    valid_from: date = date(2026, 4, 1),
    valid_to: date | None = None,
    notes: str | None = "Observed values; threshold not tested.",
) -> PhysiologyProfileInput:
    return PhysiologyProfileInput(
        athlete_id=ATHLETE_ID,
        valid_from=valid_from,
        valid_to=valid_to,
        observed_max_hr_bpm=195,
        resting_hr_bpm=45,
        lactate_threshold_hr_bpm=None,
        threshold_pace_seconds_per_km=None,
        notes=notes,
    )


def test_profile_is_created_and_identical_request_is_reused(
    db_session: Session,
) -> None:
    service = PhysiologyProfileService(db_session)
    profile_input = _profile_input()

    first = service.configure(profile_input)
    second = service.configure(profile_input)

    assert first.created is True
    assert second.created is False
    assert second.profile_id == first.profile_id
    assert db_session.scalar(select(func.count()).select_from(PhysiologyProfile)) == 1

    profile = db_session.get(
        PhysiologyProfile,
        first.profile_id,
    )
    assert profile is not None
    assert profile.observed_max_hr_bpm == 195
    assert profile.resting_hr_bpm == 45
    assert profile.lactate_threshold_hr_bpm is None


def test_overlapping_profile_is_rejected(
    db_session: Session,
) -> None:
    service = PhysiologyProfileService(db_session)
    service.configure(
        _profile_input(
            valid_to=date(2026, 7, 1),
        )
    )

    with pytest.raises(
        PhysiologyProfileConflictError,
        match="overlaps",
    ):
        service.configure(
            _profile_input(
                valid_from=date(2026, 6, 1),
                valid_to=date(2026, 8, 1),
                notes="Conflicting profile",
            )
        )

    assert db_session.scalar(select(func.count()).select_from(PhysiologyProfile)) == 1


def test_adjacent_profiles_do_not_overlap(
    db_session: Session,
) -> None:
    service = PhysiologyProfileService(db_session)

    first = service.configure(
        _profile_input(
            valid_from=date(2026, 4, 1),
            valid_to=date(2026, 7, 1),
        )
    )
    second = service.configure(
        _profile_input(
            valid_from=date(2026, 7, 1),
            valid_to=None,
            notes="New observation period",
        )
    )

    assert first.created is True
    assert second.created is True
    assert first.profile_id != second.profile_id


def test_same_period_with_changed_values_is_a_conflict(
    db_session: Session,
) -> None:
    service = PhysiologyProfileService(db_session)
    service.configure(_profile_input())

    with pytest.raises(
        PhysiologyProfileConflictError,
        match="overlaps",
    ):
        service.configure(_profile_input(notes="Different interpretation"))


def test_missing_athlete_rolls_back() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        with pytest.raises(
            PhysiologyProfileError,
            match="athlete must exist",
        ):
            PhysiologyProfileService(session).configure(_profile_input())

        assert session.scalar(select(func.count()).select_from(PhysiologyProfile)) == 0

    engine.dispose()


def test_profile_input_rejects_invalid_physiology() -> None:
    with pytest.raises(ValueError, match="Resting heart rate"):
        PhysiologyProfileInput(
            athlete_id=ATHLETE_ID,
            valid_from=date(2026, 4, 1),
            observed_max_hr_bpm=195,
            resting_hr_bpm=200,
        )

    with pytest.raises(ValueError, match="Threshold heart rate"):
        PhysiologyProfileInput(
            athlete_id=ATHLETE_ID,
            valid_from=date(2026, 4, 1),
            observed_max_hr_bpm=195,
            lactate_threshold_hr_bpm=195,
        )

    with pytest.raises(ValueError, match="later than"):
        PhysiologyProfileInput(
            athlete_id=ATHLETE_ID,
            valid_from=date(2026, 4, 1),
            valid_to=date(2026, 4, 1),
        )
