"""Tests for read-only analytics presentation queries."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
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
from runcoach.db.analytics_queries import (
    AnalyticsQueryError,
    AnalyticsQueryService,
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
THIRD_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000012")
EXCLUDED_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000013")


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
    verification_status: str = "unverified",
) -> Activity:
    activity = Activity(
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
        verification_status=verification_status,
    )
    session.add(activity)
    return activity


def _add_metric(
    session: Session,
    *,
    activity_id: UUID,
    hash_character: str,
    calculated_at: datetime,
    heart_rate_coverage_pct: Decimal,
    gps_coverage_pct: Decimal,
    cadence_coverage_pct: Decimal,
    edwards_trimp: float | None,
) -> None:
    session.add(
        ActivityMetric(
            activity_id=activity_id,
            algorithm_version=ACTIVITY_METRICS_VERSION,
            profile_id=None,
            calculated_at=calculated_at,
            input_hash=hash_character * 64,
            average_pace_seconds_per_km=Decimal("300.000"),
            heart_rate_coverage_pct=heart_rate_coverage_pct,
            gps_coverage_pct=gps_coverage_pct,
            cadence_coverage_pct=cadence_coverage_pct,
            load_method=DURATION_LOAD_METHOD,
            training_load=Decimal("60.0000"),
            zone_distribution={},
            additional_metrics={
                "edwards_trimp": edwards_trimp,
            },
        )
    )


def _add_daily_load(
    session: Session,
    *,
    local_date: date,
    daily_load: Decimal,
    acute_load: Decimal,
    chronic_load: Decimal,
    form_index: Decimal,
) -> None:
    session.add(
        DailyLoad(
            athlete_id=ATHLETE_ID,
            local_date=local_date,
            load_method=DURATION_LOAD_METHOD,
            algorithm_version=DAILY_LOAD_ALGORITHM_VERSION,
            daily_load=daily_load,
            acute_load=acute_load,
            chronic_load=chronic_load,
            fitness_index=chronic_load,
            fatigue_index=acute_load,
            form_index=form_index,
            coverage_pct=Decimal("100.000"),
        )
    )


def _seed_overview(session: Session) -> None:
    _add_activity(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        local_date=date(2026, 8, 23),
        distance_m=Decimal("25000.000"),
        moving_time_ms=7_200_000,
    )
    _add_activity(
        session,
        activity_id=SECOND_ACTIVITY_ID,
        local_date=date(2026, 8, 10),
        distance_m=Decimal("10000.000"),
        moving_time_ms=3_600_000,
    )
    _add_activity(
        session,
        activity_id=THIRD_ACTIVITY_ID,
        local_date=date(2026, 7, 1),
        distance_m=Decimal("5000.000"),
        moving_time_ms=1_800_000,
    )
    _add_activity(
        session,
        activity_id=EXCLUDED_ACTIVITY_ID,
        local_date=date(2026, 8, 26),
        distance_m=Decimal("100000.000"),
        moving_time_ms=36_000_000,
        verification_status="excluded",
    )

    _add_metric(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        hash_character="a",
        calculated_at=datetime(2026, 8, 26, tzinfo=UTC),
        heart_rate_coverage_pct=Decimal("0.000"),
        gps_coverage_pct=Decimal("0.000"),
        cadence_coverage_pct=Decimal("0.000"),
        edwards_trimp=None,
    )
    _add_metric(
        session,
        activity_id=FIRST_ACTIVITY_ID,
        hash_character="b",
        calculated_at=datetime(2026, 8, 27, tzinfo=UTC),
        heart_rate_coverage_pct=Decimal("100.000"),
        gps_coverage_pct=Decimal("90.000"),
        cadence_coverage_pct=Decimal("80.000"),
        edwards_trimp=300.0,
    )
    _add_metric(
        session,
        activity_id=SECOND_ACTIVITY_ID,
        hash_character="c",
        calculated_at=datetime(2026, 8, 27, tzinfo=UTC),
        heart_rate_coverage_pct=Decimal("50.000"),
        gps_coverage_pct=Decimal("100.000"),
        cadence_coverage_pct=Decimal("50.000"),
        edwards_trimp=None,
    )
    _add_metric(
        session,
        activity_id=THIRD_ACTIVITY_ID,
        hash_character="d",
        calculated_at=datetime(2026, 8, 27, tzinfo=UTC),
        heart_rate_coverage_pct=Decimal("0.000"),
        gps_coverage_pct=Decimal("100.000"),
        cadence_coverage_pct=Decimal("0.000"),
        edwards_trimp=None,
    )

    _add_daily_load(
        session,
        local_date=date(2026, 8, 26),
        daily_load=Decimal("0.0000"),
        acute_load=Decimal("45.0000"),
        chronic_load=Decimal("45.9000"),
        form_index=Decimal("0.9000"),
    )
    _add_daily_load(
        session,
        local_date=date(2026, 8, 27),
        daily_load=Decimal("0.0000"),
        acute_load=Decimal("38.5700"),
        chronic_load=Decimal("44.8100"),
        form_index=Decimal("6.2400"),
    )
    session.commit()


def test_overview_returns_dashboard_ready_aggregates(
    db_session: Session,
) -> None:
    _seed_overview(db_session)

    overview = AnalyticsQueryService(db_session).overview(
        athlete_id=ATHLETE_ID,
    )

    assert overview.as_of_date == date(2026, 8, 27)
    assert overview.data_start_date == date(2026, 7, 1)
    assert overview.data_end_date == date(2026, 8, 23)
    assert overview.total_runs == 3
    assert overview.total_distance_km == 40.0
    assert overview.total_moving_hours == 3.5

    assert overview.last_7_days.start_date == date(2026, 8, 21)
    assert overview.last_7_days.runs == 1
    assert overview.last_7_days.distance_km == 25.0
    assert overview.last_7_days.moving_hours == 2.0

    assert overview.last_28_days.start_date == date(2026, 7, 31)
    assert overview.last_28_days.runs == 2
    assert overview.last_28_days.distance_km == 35.0
    assert overview.last_28_days.moving_hours == 3.0

    assert overview.sensor_coverage.activities_with_metrics == 3
    assert overview.sensor_coverage.activities_with_heart_rate_load == 1
    assert overview.sensor_coverage.average_heart_rate_coverage_pct == 50.0
    assert overview.sensor_coverage.average_gps_coverage_pct == 96.667
    assert overview.sensor_coverage.average_cadence_coverage_pct == 43.333

    assert overview.workload.daily_load == 0.0
    assert overview.workload.acute_load == 38.57
    assert overview.workload.chronic_load == 44.81
    assert overview.workload.form_index == 6.24


def test_requested_date_selects_exact_workload_snapshot(
    db_session: Session,
) -> None:
    _seed_overview(db_session)

    overview = AnalyticsQueryService(db_session).overview(
        athlete_id=ATHLETE_ID,
        as_of_date=date(2026, 8, 26),
    )

    assert overview.as_of_date == date(2026, 8, 26)
    assert overview.workload.acute_load == 45.0
    assert overview.workload.chronic_load == 45.9
    assert overview.workload.form_index == 0.9


def test_overview_reports_zero_coverage_without_activity_metrics(
    db_session: Session,
) -> None:
    _add_activity(
        db_session,
        activity_id=FIRST_ACTIVITY_ID,
        local_date=date(2026, 8, 27),
        distance_m=Decimal("5000.000"),
        moving_time_ms=1_500_000,
    )
    _add_daily_load(
        db_session,
        local_date=date(2026, 8, 27),
        daily_load=Decimal("25.0000"),
        acute_load=Decimal("20.0000"),
        chronic_load=Decimal("15.0000"),
        form_index=Decimal("-5.0000"),
    )
    db_session.commit()

    overview = AnalyticsQueryService(db_session).overview(
        athlete_id=ATHLETE_ID,
    )

    assert overview.sensor_coverage.activities_with_metrics == 0
    assert overview.sensor_coverage.activities_with_heart_rate_load == 0
    assert overview.sensor_coverage.average_heart_rate_coverage_pct == 0.0
    assert overview.sensor_coverage.average_gps_coverage_pct == 0.0
    assert overview.sensor_coverage.average_cadence_coverage_pct == 0.0


def test_requested_date_requires_an_exact_calculated_snapshot(
    db_session: Session,
) -> None:
    _seed_overview(db_session)

    with pytest.raises(
        AnalyticsQueryError,
        match="requested date",
    ):
        AnalyticsQueryService(db_session).overview(
            athlete_id=ATHLETE_ID,
            as_of_date=date(2026, 8, 25),
        )


def test_missing_workload_is_reported(
    db_session: Session,
) -> None:
    with pytest.raises(
        AnalyticsQueryError,
        match="No calculated daily workload",
    ):
        AnalyticsQueryService(db_session).overview(
            athlete_id=ATHLETE_ID,
        )


def test_missing_athlete_is_reported(
    db_session: Session,
) -> None:
    with pytest.raises(
        AnalyticsQueryError,
        match="does not exist",
    ):
        AnalyticsQueryService(db_session).overview(
            athlete_id=MISSING_ATHLETE_ID,
        )
