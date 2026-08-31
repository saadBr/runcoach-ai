"""Tests for weekly training and daily workload trend queries."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
)
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.analytics_trends import (
    AnalyticsTrendsQueryError,
    AnalyticsTrendsQueryService,
)
from runcoach.db.base import Base
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
MISSING_ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000099")
FIRST_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000010")
SECOND_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000011")
EXCLUDED_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000012")


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


def _add_activity(
    session: Session,
    *,
    activity_id: UUID,
    local_date: date,
    distance_m: Decimal,
    moving_time_ms: int,
    elevation_gain_m: Decimal | None,
    verification_status: str = "unverified",
) -> None:
    session.add(
        Activity(
            id=activity_id,
            athlete_id=ATHLETE_ID,
            sport="running",
            activity_type="workout",
            name="Synthetic Run",
            start_time_utc=datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                7,
                0,
                tzinfo=UTC,
            ),
            original_timezone="Africa/Casablanca",
            local_start_date=local_date,
            distance_m=distance_m,
            moving_time_ms=moving_time_ms,
            elapsed_time_ms=moving_time_ms,
            elevation_gain_m=elevation_gain_m,
            verification_status=verification_status,
        )
    )


def _add_metric(
    session: Session,
    *,
    activity_id: UUID,
    hash_character: str,
    calculated_at: datetime,
    edwards_trimp: float | None,
) -> None:
    session.add(
        ActivityMetric(
            activity_id=activity_id,
            algorithm_version=ACTIVITY_METRICS_VERSION,
            profile_id=None,
            calculated_at=calculated_at,
            input_hash=hash_character * 64,
            average_pace_seconds_per_km=Decimal("360.000"),
            heart_rate_coverage_pct=Decimal("100.000"),
            gps_coverage_pct=Decimal("100.000"),
            cadence_coverage_pct=Decimal("100.000"),
            load_method=DURATION_LOAD_METHOD,
            training_load=Decimal("60.0000"),
            zone_distribution={},
            additional_metrics={
                "edwards_trimp": edwards_trimp,
            },
        )
    )


def _add_daily_series(
    session: Session,
    *,
    start_date: date = date(2026, 8, 17),
    end_date: date = date(2026, 8, 27),
) -> None:
    current_date = start_date
    sequence = 0

    while current_date <= end_date:
        session.add(
            DailyLoad(
                athlete_id=ATHLETE_ID,
                local_date=current_date,
                load_method=DURATION_LOAD_METHOD,
                algorithm_version=DAILY_LOAD_ALGORITHM_VERSION,
                daily_load=Decimal(str(sequence)),
                acute_load=Decimal("40.0000"),
                chronic_load=Decimal("45.0000"),
                fitness_index=Decimal("45.0000"),
                fatigue_index=Decimal("40.0000"),
                form_index=Decimal("5.0000"),
                coverage_pct=Decimal("100.000"),
            )
        )
        sequence += 1
        current_date += timedelta(days=1)


def _seed_trends(session: Session) -> None:
    _add_activity(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        local_date=date(2026, 8, 17),
        distance_m=Decimal("10000.000"),
        moving_time_ms=3_600_000,
        elevation_gain_m=Decimal("100.000"),
    )
    _add_activity(
        session,
        activity_id=SECOND_ACTIVITY_ID,
        local_date=date(2026, 8, 23),
        distance_m=Decimal("20000.000"),
        moving_time_ms=7_200_000,
        elevation_gain_m=Decimal("200.000"),
    )
    _add_activity(
        session,
        activity_id=EXCLUDED_ACTIVITY_ID,
        local_date=date(2026, 8, 26),
        distance_m=Decimal("100000.000"),
        moving_time_ms=36_000_000,
        elevation_gain_m=Decimal("1000.000"),
        verification_status="excluded",
    )

    _add_metric(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        hash_character="a",
        calculated_at=datetime(2026, 8, 26, tzinfo=UTC),
        edwards_trimp=999.0,
    )
    _add_metric(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        hash_character="b",
        calculated_at=datetime(2026, 8, 27, tzinfo=UTC),
        edwards_trimp=100.0,
    )
    _add_metric(
        session,
        activity_id=SECOND_ACTIVITY_ID,
        hash_character="c",
        calculated_at=datetime(2026, 8, 27, tzinfo=UTC),
        edwards_trimp=None,
    )
    _add_daily_series(session)
    session.commit()


def test_trends_return_complete_calendar_weeks_and_daily_series(
    db_session: Session,
) -> None:
    _seed_trends(db_session)

    trends = AnalyticsTrendsQueryService(db_session).trends(
        athlete_id=ATHLETE_ID,
        weeks=2,
    )

    assert trends.start_date == date(2026, 8, 17)
    assert trends.end_date == date(2026, 8, 27)
    assert trends.requested_weeks == 2
    assert len(trends.weekly_training) == 2
    assert len(trends.daily_workload) == 11

    first_week = trends.weekly_training[0]
    assert first_week.week_start == date(2026, 8, 17)
    assert first_week.week_end == date(2026, 8, 23)
    assert first_week.runs == 2
    assert first_week.distance_km == 30.0
    assert first_week.moving_hours == 3.0
    assert first_week.duration_load_minutes == 180.0
    assert first_week.weighted_pace_seconds_per_km == 360.0
    assert first_week.elevation_gain_m == 300.0
    assert first_week.heart_rate_load_activities == 1
    assert first_week.edwards_trimp == 100.0

    partial_week = trends.weekly_training[1]
    assert partial_week.week_start == date(2026, 8, 24)
    assert partial_week.week_end == date(2026, 8, 27)
    assert partial_week.runs == 0
    assert partial_week.distance_km == 0.0
    assert partial_week.moving_hours == 0.0
    assert partial_week.duration_load_minutes == 0.0
    assert partial_week.weighted_pace_seconds_per_km is None
    assert partial_week.elevation_gain_m is None
    assert partial_week.heart_rate_load_activities == 0
    assert partial_week.edwards_trimp is None

    assert trends.daily_workload[0].local_date == date(2026, 8, 17)
    assert trends.daily_workload[-1].local_date == date(2026, 8, 27)
    assert trends.daily_workload[-1].daily_load == 10.0
    assert trends.daily_workload[-1].form_index == 5.0


def test_requested_end_date_is_exact_and_produces_partial_week(
    db_session: Session,
) -> None:
    _seed_trends(db_session)

    trends = AnalyticsTrendsQueryService(db_session).trends(
        athlete_id=ATHLETE_ID,
        weeks=1,
        end_date=date(2026, 8, 24),
    )

    assert trends.start_date == date(2026, 8, 24)
    assert trends.end_date == date(2026, 8, 24)
    assert len(trends.weekly_training) == 1
    assert trends.weekly_training[0].week_end == date(2026, 8, 24)
    assert trends.weekly_training[0].runs == 0
    assert len(trends.daily_workload) == 1


@pytest.mark.parametrize("weeks", [0, 53])
def test_invalid_week_count_is_rejected(
    db_session: Session,
    weeks: int,
) -> None:
    with pytest.raises(
        AnalyticsTrendsQueryError,
        match="between 1 and 52",
    ):
        AnalyticsTrendsQueryService(db_session).trends(
            athlete_id=ATHLETE_ID,
            weeks=weeks,
        )


def test_missing_requested_end_date_is_reported(
    db_session: Session,
) -> None:
    _seed_trends(db_session)

    with pytest.raises(
        AnalyticsTrendsQueryError,
        match="requested end date",
    ):
        AnalyticsTrendsQueryService(db_session).trends(
            athlete_id=ATHLETE_ID,
            weeks=2,
            end_date=date(2026, 8, 16),
        )


def test_missing_workload_is_reported(
    db_session: Session,
) -> None:
    with pytest.raises(
        AnalyticsTrendsQueryError,
        match="No calculated daily workload",
    ):
        AnalyticsTrendsQueryService(db_session).trends(
            athlete_id=ATHLETE_ID,
        )


def test_missing_athlete_is_reported(
    db_session: Session,
) -> None:
    with pytest.raises(
        AnalyticsTrendsQueryError,
        match="does not exist",
    ):
        AnalyticsTrendsQueryService(db_session).trends(
            athlete_id=MISSING_ATHLETE_ID,
        )
