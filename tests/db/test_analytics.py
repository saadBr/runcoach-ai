"""Tests for deterministic analytics persistence."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
    HEART_RATE_ZONE_METHOD,
)
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.analytics import (
    AnalyticsPersistenceError,
    DeterministicAnalyticsService,
)
from runcoach.db.base import Base
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
    PhysiologyProfile,
    Trackpoint,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
PROFILE_ID = UUID("018f0000-0000-7000-8000-000000000002")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000003")
SECOND_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000004")


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


def _add_profile(
    session: Session,
    *,
    valid_from: date = date(2026, 4, 1),
) -> PhysiologyProfile:
    profile = PhysiologyProfile(
        id=PROFILE_ID,
        athlete_id=ATHLETE_ID,
        valid_from=valid_from,
        valid_to=None,
        observed_max_hr_bpm=195,
        resting_hr_bpm=45,
        lactate_threshold_hr_bpm=None,
        threshold_pace_seconds_per_km=None,
        zone_method=HEART_RATE_ZONE_METHOD,
        notes="Synthetic test profile.",
    )
    session.add(profile)
    return profile


def _add_activity(
    session: Session,
    *,
    activity_id: UUID = ACTIVITY_ID,
    local_date: date = date(2026, 4, 1),
    distance_m: Decimal = Decimal("2000.000"),
    moving_time_ms: int = 120_000,
    elapsed_time_ms: int = 120_000,
    verification_status: str = "unverified",
) -> Activity:
    start_time = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        7,
        0,
        tzinfo=UTC,
    )
    activity = Activity(
        id=activity_id,
        athlete_id=ATHLETE_ID,
        sport="running",
        activity_type="workout",
        name="Synthetic Run",
        start_time_utc=start_time,
        original_timezone="Africa/Casablanca",
        local_start_date=local_date,
        distance_m=distance_m,
        moving_time_ms=moving_time_ms,
        elapsed_time_ms=elapsed_time_ms,
        verification_status=verification_status,
    )
    session.add(activity)
    return activity


def _add_trackpoints(
    session: Session,
    activity: Activity,
) -> None:
    values = (
        (0, 0, 100),
        (1, 60_000, 130),
        (2, 120_000, 170),
    )

    for sequence, elapsed_ms, heart_rate in values:
        session.add(
            Trackpoint(
                activity_id=activity.id,
                sequence_number=sequence,
                recorded_at=activity.start_time_utc + timedelta(milliseconds=elapsed_ms),
                elapsed_ms=elapsed_ms,
                distance_m=Decimal(str(sequence * 1000)),
                latitude=Decimal("33.500000"),
                longitude=Decimal("-7.600000"),
                altitude_m=Decimal("20.000"),
                heart_rate_bpm=heart_rate,
                cadence_spm=Decimal("176.000"),
                speed_mps=Decimal("4.0000"),
                power_watts=None,
                temperature_c=None,
                is_paused=False,
            )
        )


def test_calculation_persists_versioned_metrics_and_rest_days(
    db_session: Session,
) -> None:
    _add_profile(db_session)
    activity = _add_activity(db_session)
    _add_trackpoints(db_session, activity)
    db_session.commit()

    summary = DeterministicAnalyticsService(db_session).calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 3),
    )

    assert summary.activities_processed == 1
    assert summary.activities_with_profile == 1
    assert summary.activities_with_heart_rate_load == 1
    assert summary.activity_metrics_created == 1
    assert summary.activity_metrics_reused == 0
    assert summary.daily_loads_created == 3
    assert summary.daily_loads_updated == 0
    assert summary.daily_loads_reused == 0

    metric = db_session.scalar(select(ActivityMetric))
    assert metric is not None
    assert metric.activity_id == ACTIVITY_ID
    assert metric.algorithm_version == ACTIVITY_METRICS_VERSION
    assert metric.profile_id == PROFILE_ID
    assert metric.average_pace_seconds_per_km == Decimal("60.000")
    assert metric.training_load == Decimal("2.0000")
    assert metric.load_method == DURATION_LOAD_METHOD
    assert metric.zone_distribution["method"] == HEART_RATE_ZONE_METHOD
    assert metric.additional_metrics["edwards_trimp"] == 0.5
    assert metric.additional_metrics["sample_count"] == 3
    assert "latitude" not in metric.additional_metrics
    assert "longitude" not in metric.additional_metrics

    daily_loads = list(db_session.scalars(select(DailyLoad).order_by(DailyLoad.local_date)))
    assert [row.local_date for row in daily_loads] == [
        date(2026, 4, 1),
        date(2026, 4, 2),
        date(2026, 4, 3),
    ]
    assert [row.daily_load for row in daily_loads] == [
        Decimal("2.0000"),
        Decimal("0.0000"),
        Decimal("0.0000"),
    ]
    assert all(row.coverage_pct == Decimal("100.000") for row in daily_loads)
    assert all(row.acute_load is None for row in daily_loads)


def test_identical_calculation_reuses_all_results(
    db_session: Session,
) -> None:
    _add_profile(db_session)
    activity = _add_activity(db_session)
    _add_trackpoints(db_session, activity)
    db_session.commit()

    service = DeterministicAnalyticsService(db_session)
    first = service.calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 3),
    )
    second = service.calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 3),
    )

    assert first.activity_metrics_created == 1
    assert second.activity_metrics_created == 0
    assert second.activity_metrics_reused == 1
    assert second.daily_loads_created == 0
    assert second.daily_loads_updated == 0
    assert second.daily_loads_reused == 3

    assert db_session.scalar(select(func.count()).select_from(ActivityMetric)) == 1
    assert db_session.scalar(select(func.count()).select_from(DailyLoad)) == 3


def test_activity_before_profile_has_no_profile_dependent_metrics(
    db_session: Session,
) -> None:
    _add_profile(db_session, valid_from=date(2026, 4, 1))
    activity = _add_activity(
        db_session,
        local_date=date(2026, 3, 31),
    )
    _add_trackpoints(db_session, activity)
    db_session.commit()

    summary = DeterministicAnalyticsService(db_session).calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 3, 31),
    )

    assert summary.activities_with_profile == 0
    assert summary.activities_with_heart_rate_load == 0

    metric = db_session.scalar(select(ActivityMetric))
    assert metric is not None
    assert metric.profile_id is None
    assert metric.zone_distribution["method"] is None
    assert metric.zone_distribution["zones"] == []
    assert metric.additional_metrics["edwards_trimp"] is None


def test_changed_activity_creates_new_metric_and_updates_daily_load(
    db_session: Session,
) -> None:
    _add_profile(db_session)
    activity = _add_activity(db_session)
    _add_trackpoints(db_session, activity)
    db_session.commit()

    service = DeterministicAnalyticsService(db_session)
    service.calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 1),
    )

    with db_session.begin():
        stored_activity = db_session.get(Activity, ACTIVITY_ID)
        assert stored_activity is not None
        stored_activity.moving_time_ms = 180_000
        stored_activity.elapsed_time_ms = 180_000

    second = service.calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 1),
    )

    assert second.activity_metrics_created == 1
    assert second.activity_metrics_reused == 0
    assert second.daily_loads_created == 0
    assert second.daily_loads_updated == 1
    assert second.daily_loads_reused == 0

    assert db_session.scalar(select(func.count()).select_from(ActivityMetric)) == 2

    daily_load = db_session.scalar(select(DailyLoad))
    assert daily_load is not None
    assert daily_load.daily_load == Decimal("3.0000")


def test_excluded_and_future_activities_are_not_calculated(
    db_session: Session,
) -> None:
    _add_activity(
        db_session,
        activity_id=ACTIVITY_ID,
        local_date=date(2026, 4, 1),
    )
    _add_activity(
        db_session,
        activity_id=SECOND_ACTIVITY_ID,
        local_date=date(2026, 4, 2),
        verification_status="excluded",
    )
    db_session.commit()

    summary = DeterministicAnalyticsService(db_session).calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 1),
    )

    assert summary.activities_processed == 1
    assert summary.activity_metrics_created == 1


def test_missing_eligible_activities_rolls_back(
    db_session: Session,
) -> None:
    with pytest.raises(
        AnalyticsPersistenceError,
        match="No eligible activities",
    ):
        DeterministicAnalyticsService(db_session).calculate(
            athlete_id=ATHLETE_ID,
            as_of_date=date(2026, 4, 1),
        )

    assert db_session.scalar(select(func.count()).select_from(ActivityMetric)) == 0
    assert db_session.scalar(select(func.count()).select_from(DailyLoad)) == 0


def test_persisted_daily_load_uses_expected_versions(
    db_session: Session,
) -> None:
    _add_activity(db_session)
    db_session.commit()

    DeterministicAnalyticsService(db_session).calculate(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 4, 1),
    )

    daily_load = db_session.scalar(select(DailyLoad))
    assert daily_load is not None
    assert daily_load.load_method == DURATION_LOAD_METHOD
    assert daily_load.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION
