"""Tests for verified-performance API query models."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.performance import StandardDistance
from runcoach.db.base import Base
from runcoach.db.models import Activity, Athlete, PersonalBest
from runcoach.db.performance_queries import (
    PerformanceQueryError,
    PerformanceQueryService,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
OTHER_ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000002")
ACTIVITY_IDS = (
    UUID("018f0000-0000-7000-8000-000000000010"),
    UUID("018f0000-0000-7000-8000-000000000011"),
    UUID("018f0000-0000-7000-8000-000000000012"),
    UUID("018f0000-0000-7000-8000-000000000013"),
)
PERSONAL_BEST_IDS = (
    UUID("018f0000-0000-7000-8000-000000000020"),
    UUID("018f0000-0000-7000-8000-000000000021"),
    UUID("018f0000-0000-7000-8000-000000000022"),
    UUID("018f0000-0000-7000-8000-000000000023"),
)


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
        session.commit()
        yield session

    engine.dispose()


def _activity(activity_id: UUID, *, month: int) -> Activity:
    return Activity(
        id=activity_id,
        athlete_id=ATHLETE_ID,
        sport="running",
        activity_type="unknown",
        name="Synthetic Run",
        start_time_utc=datetime(2026, month, 1, tzinfo=UTC),
        original_timezone="Africa/Casablanca",
        local_start_date=date(2026, month, 1),
        distance_m=Decimal("5000.000"),
        moving_time_ms=1_200_000,
        elapsed_time_ms=1_202_000,
        verification_status="unverified",
    )


def _seed_personal_bests(session: Session) -> None:
    distances = (
        Decimal("5000.000"),
        Decimal("10000.000"),
        Decimal("21097.500"),
        Decimal("42195.000"),
    )
    elapsed_times = (1_181_000, 2_464_000, 5_606_000, 13_266_000)
    labels = (
        "verified_max_effort",
        "verified_race",
        "verified_race",
        "verified_race",
    )
    months = (9, 3, 6, 4)

    for (
        activity_id,
        personal_best_id,
        distance_m,
        elapsed_time_ms,
        label,
        month,
    ) in zip(
        ACTIVITY_IDS,
        PERSONAL_BEST_IDS,
        distances,
        elapsed_times,
        labels,
        months,
        strict=True,
    ):
        activity = _activity(activity_id, month=month)
        session.add(activity)
        session.add(
            PersonalBest(
                id=personal_best_id,
                athlete_id=ATHLETE_ID,
                activity_id=activity_id,
                distance_m=distance_m,
                elapsed_time_ms=elapsed_time_ms,
                effort_type="provider_best_effort",
                verification_status=label,
                verification_source="strava_best_effort",
                achieved_at=activity.start_time_utc,
                algorithm_version="strava_best_effort_import_v1",
            )
        )
    session.commit()


def test_overview_returns_current_records_and_fitness_estimates(
    db_session: Session,
) -> None:
    _seed_personal_bests(db_session)

    overview = PerformanceQueryService(db_session).overview(athlete_id=ATHLETE_ID)

    assert [personal_best.distance for personal_best in overview.personal_bests] == list(
        StandardDistance
    )
    assert [personal_best.elapsed_time_seconds for personal_best in overview.personal_bests] == [
        1181.0,
        2464.0,
        5606.0,
        13266.0,
    ]
    assert overview.personal_bests[0].pace_seconds_per_km == pytest.approx(236.2)
    assert overview.prediction_status == "experimental_not_validated"
    assert overview.prediction_method == "training_context_fitness_v2"
    assert overview.verified_labels == 4
    assert overview.interpretation_role == "openai_explains_validated_outputs_only"
    assert len(overview.limitations) == 4
    assert overview.current_fitness.anchor.distance is StandardDistance.FIVE_K
    assert overview.current_fitness.anchor_capacity_factor == 0.985
    assert overview.current_fitness.training.runs_168d == 3
    assert overview.current_fitness.training.runs_365d == 4
    assert [
        estimate.fitness_potential_time_seconds for estimate in overview.current_fitness.estimates
    ] == pytest.approx([1163.285, 2427.04, 5521.91, 13067.01])


def test_superseded_record_is_not_returned(db_session: Session) -> None:
    _seed_personal_bests(db_session)
    old_activity_id = UUID("018f0000-0000-7000-8000-000000000030")
    old_activity = _activity(old_activity_id, month=1)
    old_activity.start_time_utc = datetime(2025, 1, 1, tzinfo=UTC)
    old_activity.local_start_date = date(2025, 1, 1)
    db_session.add(old_activity)
    db_session.add(
        PersonalBest(
            athlete_id=ATHLETE_ID,
            activity_id=old_activity_id,
            distance_m=Decimal("5000.000"),
            elapsed_time_ms=1_250_000,
            effort_type="provider_best_effort",
            verification_status="verified_max_effort",
            verification_source="strava_best_effort",
            achieved_at=old_activity.start_time_utc,
            algorithm_version="strava_best_effort_import_v1",
            superseded_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    db_session.commit()

    overview = PerformanceQueryService(db_session).overview(athlete_id=ATHLETE_ID)

    assert len(overview.personal_bests) == 4
    assert overview.personal_bests[0].personal_best_id == PERSONAL_BEST_IDS[0]


def test_missing_athlete_is_rejected(db_session: Session) -> None:
    with pytest.raises(PerformanceQueryError, match="does not exist"):
        PerformanceQueryService(db_session).overview(athlete_id=OTHER_ATHLETE_ID)


def test_athlete_without_verified_records_is_rejected(db_session: Session) -> None:
    with pytest.raises(PerformanceQueryError, match="No verified personal bests"):
        PerformanceQueryService(db_session).overview(athlete_id=ATHLETE_ID)


def test_multiple_current_records_for_one_distance_are_rejected(
    db_session: Session,
) -> None:
    _seed_personal_bests(db_session)
    duplicate_activity_id = UUID("018f0000-0000-7000-8000-000000000031")
    duplicate_activity = _activity(duplicate_activity_id, month=5)
    db_session.add(duplicate_activity)
    db_session.add(
        PersonalBest(
            athlete_id=ATHLETE_ID,
            activity_id=duplicate_activity_id,
            distance_m=Decimal("5000.000"),
            elapsed_time_ms=1_170_000,
            effort_type="provider_best_effort",
            verification_status="verified_max_effort",
            verification_source="strava_best_effort",
            achieved_at=duplicate_activity.start_time_utc,
            algorithm_version="strava_best_effort_import_v1",
        )
    )
    db_session.commit()

    with pytest.raises(PerformanceQueryError, match="Multiple current personal bests"):
        PerformanceQueryService(db_session).overview(athlete_id=ATHLETE_ID)
