"""Tests for read-only performance label-audit queries."""

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
from runcoach.db.models import Activity, Athlete, Trackpoint
from runcoach.db.performance_audit import (
    PerformanceAuditQueryError,
    PerformanceAuditQueryService,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
MISSING_ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000099")


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


def _add_activity(
    session: Session,
    *,
    activity_number: int,
    distance_m: str,
    elapsed_time_ms: int,
    verification_status: str = "unverified",
) -> None:
    session.add(
        Activity(
            id=UUID(f"018f0000-0000-7000-8000-{activity_number:012d}"),
            athlete_id=ATHLETE_ID,
            sport="running",
            activity_type="unknown",
            name="Synthetic Run",
            start_time_utc=datetime(2026, 1, activity_number, tzinfo=UTC),
            original_timezone="Africa/Casablanca",
            local_start_date=date(2026, 1, activity_number),
            distance_m=Decimal(distance_m),
            moving_time_ms=elapsed_time_ms,
            elapsed_time_ms=elapsed_time_ms,
            verification_status=verification_status,
        )
    )


def test_audit_returns_candidates_without_labeling_them(db_session: Session) -> None:
    _add_activity(
        db_session,
        activity_number=1,
        distance_m="5030.000",
        elapsed_time_ms=1_200_000,
    )
    _add_activity(
        db_session,
        activity_number=2,
        distance_m="10100.000",
        elapsed_time_ms=2_500_000,
    )
    _add_activity(
        db_session,
        activity_number=3,
        distance_m="15000.000",
        elapsed_time_ms=4_000_000,
    )
    _add_activity(
        db_session,
        activity_number=4,
        distance_m="5000.000",
        elapsed_time_ms=1_100_000,
        verification_status="excluded",
    )
    db_session.commit()

    audit = PerformanceAuditQueryService(db_session).audit(athlete_id=ATHLETE_ID)

    assert audit.audit_version == "standard_distance_audit_v1"
    assert audit.distance_tolerance_pct == 3
    assert audit.eligible_activities == 3
    assert len(audit.candidates) == 2
    assert [candidate.matched_distance for candidate in audit.candidates] == [
        StandardDistance.FIVE_K,
        StandardDistance.TEN_K,
    ]
    assert audit.candidates[0].distance_deviation_pct == pytest.approx(0.6)
    assert audit.candidates[0].elapsed_pace_seconds_per_km == pytest.approx(238.568588)
    assert all(candidate.verification_status == "unverified" for candidate in audit.candidates)


def test_audit_respects_a_narrower_distance_tolerance(db_session: Session) -> None:
    _add_activity(
        db_session,
        activity_number=1,
        distance_m="5030.000",
        elapsed_time_ms=1_200_000,
    )
    db_session.commit()

    audit = PerformanceAuditQueryService(db_session).audit(
        athlete_id=ATHLETE_ID,
        distance_tolerance_pct=0.5,
    )

    assert audit.eligible_activities == 1
    assert audit.candidates == ()


def test_audit_requires_an_existing_athlete(db_session: Session) -> None:
    with pytest.raises(PerformanceAuditQueryError, match="does not exist"):
        PerformanceAuditQueryService(db_session).audit(athlete_id=MISSING_ATHLETE_ID)


def test_evidence_interpolates_standard_distance_from_trackpoints(
    db_session: Session,
) -> None:
    activity_id = UUID("018f0000-0000-7000-8000-000000000010")
    _add_activity(
        db_session,
        activity_number=10,
        distance_m="6000.000",
        elapsed_time_ms=1_400_000,
    )
    db_session.add_all(
        (
            Trackpoint(
                activity_id=activity_id,
                sequence_number=0,
                recorded_at=datetime(2026, 1, 10, tzinfo=UTC),
                elapsed_ms=0,
                distance_m=Decimal("0.000"),
                is_paused=False,
            ),
            Trackpoint(
                activity_id=activity_id,
                sequence_number=1,
                recorded_at=datetime(2026, 1, 10, 0, 16, 40, tzinfo=UTC),
                elapsed_ms=1_000_000,
                distance_m=Decimal("4000.000"),
                is_paused=False,
            ),
            Trackpoint(
                activity_id=activity_id,
                sequence_number=2,
                recorded_at=datetime(2026, 1, 10, 0, 23, 20, tzinfo=UTC),
                elapsed_ms=1_400_000,
                distance_m=Decimal("6000.000"),
                is_paused=False,
            ),
        )
    )
    db_session.commit()

    evidence = PerformanceAuditQueryService(db_session).evidence(
        athlete_id=ATHLETE_ID,
        activity_id=activity_id,
        target_distance=StandardDistance.FIVE_K,
    )

    assert evidence.recorded_distance_m == 6_000
    assert evidence.recorded_elapsed_time_seconds == 1_400
    assert evidence.distance_samples == 3
    assert evidence.derived_effort is not None
    assert evidence.derived_effort.elapsed_time_seconds == 1_200


def test_evidence_reports_missing_trackpoint_support(db_session: Session) -> None:
    activity_id = UUID("018f0000-0000-7000-8000-000000000011")
    _add_activity(
        db_session,
        activity_number=11,
        distance_m="5000.000",
        elapsed_time_ms=1_200_000,
    )
    db_session.commit()

    evidence = PerformanceAuditQueryService(db_session).evidence(
        athlete_id=ATHLETE_ID,
        activity_id=activity_id,
        target_distance=StandardDistance.FIVE_K,
    )

    assert evidence.distance_samples == 0
    assert evidence.derived_effort is None


def test_evidence_requires_an_eligible_activity(db_session: Session) -> None:
    with pytest.raises(PerformanceAuditQueryError, match="does not exist"):
        PerformanceAuditQueryService(db_session).evidence(
            athlete_id=ATHLETE_ID,
            activity_id=UUID("018f0000-0000-7000-8000-000000000099"),
            target_distance=StandardDistance.FIVE_K,
        )
