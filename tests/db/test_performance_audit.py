"""Tests for read-only performance label-audit queries."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.activity import ACTIVITY_METRICS_VERSION, DURATION_LOAD_METHOD
from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.base import Base
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
    PersonalBest,
    Trackpoint,
)
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


def test_training_dataset_uses_only_pre_event_evidence(db_session: Session) -> None:
    prior_id = UUID("018f0000-0000-7000-8000-000000000010")
    candidate_id = UUID("018f0000-0000-7000-8000-000000000020")
    _add_activity(
        db_session,
        activity_number=10,
        distance_m="12000.000",
        elapsed_time_ms=3_600_000,
    )
    _add_activity(
        db_session,
        activity_number=20,
        distance_m="5030.000",
        elapsed_time_ms=1_200_000,
    )
    db_session.add_all(
        (
            ActivityMetric(
                activity_id=prior_id,
                algorithm_version=ACTIVITY_METRICS_VERSION,
                input_hash="a" * 64,
                heart_rate_coverage_pct=Decimal("100.000"),
                gps_coverage_pct=Decimal("100.000"),
                cadence_coverage_pct=Decimal("100.000"),
                load_method=DURATION_LOAD_METHOD,
                training_load=Decimal("60.0000"),
                zone_distribution={},
                additional_metrics={},
            ),
            ActivityMetric(
                activity_id=candidate_id,
                algorithm_version=ACTIVITY_METRICS_VERSION,
                input_hash="b" * 64,
                heart_rate_coverage_pct=Decimal("100.000"),
                gps_coverage_pct=Decimal("100.000"),
                cadence_coverage_pct=Decimal("100.000"),
                load_method=DURATION_LOAD_METHOD,
                training_load=Decimal("999.0000"),
                zone_distribution={},
                additional_metrics={},
            ),
            DailyLoad(
                athlete_id=ATHLETE_ID,
                local_date=date(2026, 1, 19),
                load_method=DURATION_LOAD_METHOD,
                algorithm_version=DAILY_LOAD_ALGORITHM_VERSION,
                daily_load=Decimal("0.0000"),
                acute_load=Decimal("42.0000"),
                chronic_load=Decimal("38.0000"),
                fitness_index=Decimal("38.0000"),
                fatigue_index=Decimal("42.0000"),
                form_index=Decimal("-4.0000"),
                coverage_pct=Decimal("100.000"),
            ),
            PersonalBest(
                athlete_id=ATHLETE_ID,
                activity_id=prior_id,
                distance_m=Decimal("10000.000"),
                elapsed_time_ms=3_600_000,
                effort_type="provider_best_effort",
                verification_status="verified_max_effort",
                verification_source="synthetic_review",
                achieved_at=datetime(2026, 1, 10, tzinfo=UTC),
                algorithm_version="synthetic_review_v1",
            ),
            PersonalBest(
                athlete_id=ATHLETE_ID,
                activity_id=candidate_id,
                distance_m=Decimal("5000.000"),
                elapsed_time_ms=1_181_000,
                effort_type="provider_best_effort",
                verification_status="verified_max_effort",
                verification_source="synthetic_review",
                achieved_at=datetime(2026, 1, 20, tzinfo=UTC),
                algorithm_version="synthetic_review_v1",
            ),
        )
    )
    db_session.commit()

    dataset = PerformanceAuditQueryService(db_session).training_dataset(athlete_id=ATHLETE_ID)

    candidate = next(row for row in dataset.rows if row.activity_id == candidate_id)
    windows = {window.days: window for window in candidate.training_windows}
    assert dataset.dataset_version == "performance_training_features_v1"
    assert dataset.model_status == "evaluation_required"
    assert candidate.review_status == "verified"
    assert candidate.review_label == "verified_max_effort"
    assert candidate.verified_elapsed_time_seconds == 1181
    assert candidate.prior_history_runs == 1
    assert candidate.prior_acute_load == 42
    assert candidate.prior_chronic_load == 38
    assert candidate.prior_form_index == -4
    assert candidate.prior_10k_best_seconds == 3600
    assert windows[7].runs == 0
    assert windows[7].duration_load_minutes == 0
    assert windows[28].runs == 1
    assert windows[28].distance_km == 12
    assert windows[28].duration_load_minutes == 60
    assert windows[28].weighted_pace_seconds_per_km == 300


def test_training_dataset_keeps_unreviewed_candidates_unlabeled(
    db_session: Session,
) -> None:
    _add_activity(
        db_session,
        activity_number=1,
        distance_m="5000.000",
        elapsed_time_ms=1_200_000,
    )
    db_session.commit()

    dataset = PerformanceAuditQueryService(db_session).training_dataset(athlete_id=ATHLETE_ID)

    assert dataset.candidate_rows == 1
    assert dataset.verified_rows == 0
    assert dataset.unreviewed_rows == 1
    assert dataset.model_status == "label_audit_required"
    assert dataset.rows[0].review_status == "unreviewed"
    assert dataset.rows[0].review_label is None
    assert dataset.rows[0].verified_elapsed_time_seconds is None
