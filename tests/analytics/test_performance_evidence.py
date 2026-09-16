"""Tests for representative performance-evidence selection."""

from datetime import date
from uuid import UUID

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.performance_evidence import (
    ActivityPerformanceCandidate,
    PerformanceEvidenceKind,
    select_activity_performance_evidence,
)
from runcoach.analytics.session_classification import SessionKind


def _candidate(
    suffix: int,
    *,
    name: str,
    achieved_on: date,
    distance_km: float,
    moving_seconds: float,
    elapsed_seconds: float | None = None,
    activity_type: str = "unknown",
    session_kind: SessionKind = SessionKind.UNCLASSIFIED,
) -> ActivityPerformanceCandidate:
    return ActivityPerformanceCandidate(
        activity_id=UUID(f"018f0000-0000-7000-8000-{suffix:012d}"),
        name=name,
        achieved_on=achieved_on,
        distance_km=distance_km,
        moving_time_seconds=moving_seconds,
        elapsed_time_seconds=elapsed_seconds or moving_seconds,
        activity_type=activity_type,
        session_kind=session_kind,
    )


def test_explicit_race_is_retained_without_standard_distance_match() -> None:
    race = _candidate(
        1,
        name="City 15K race",
        achieved_on=date(2026, 3, 1),
        distance_km=15.2,
        moving_seconds=3_900,
        activity_type="race",
        session_kind=SessionKind.RACE,
    )

    selected = select_activity_performance_evidence((race,))

    assert len(selected) == 1
    assert selected[0].evidence_kind is PerformanceEvidenceKind.RACE_PERFORMANCE
    assert selected[0].target_distance is None


def test_requested_standard_distance_benchmarks_are_selected() -> None:
    ten_k = _candidate(
        2,
        name="Morning Run",
        achieved_on=date(2026, 4, 1),
        distance_km=10.05,
        moving_seconds=2_500,
    )
    half = _candidate(
        3,
        name="City Running",
        achieved_on=date(2026, 5, 1),
        distance_km=21.05,
        moving_seconds=6_200,
    )

    selected = select_activity_performance_evidence((ten_k, half))

    by_distance = {item.target_distance: item for item in selected}
    assert by_distance[StandardDistance.TEN_K].evidence_kind is (
        PerformanceEvidenceKind.STANDARD_DISTANCE_PERFORMANCE
    )
    assert by_distance[StandardDistance.HALF_MARATHON].evidence_kind is (
        PerformanceEvidenceKind.STANDARD_DISTANCE_PERFORMANCE
    )


def test_strong_training_keeps_fastest_and_most_recent_per_distance_band() -> None:
    fastest = _candidate(
        4,
        name="Fast 3K",
        achieved_on=date(2026, 1, 1),
        distance_km=3.2,
        moving_seconds=780,
        session_kind=SessionKind.INTERVALS,
    )
    middle = _candidate(
        5,
        name="Tempo 3K",
        achieved_on=date(2026, 2, 1),
        distance_km=3.5,
        moving_seconds=900,
        session_kind=SessionKind.TEMPO,
    )
    recent = _candidate(
        6,
        name="Recent 4K",
        achieved_on=date(2026, 3, 1),
        distance_km=4.0,
        moving_seconds=1_040,
        session_kind=SessionKind.PROGRESSIVE,
    )

    selected = select_activity_performance_evidence((fastest, middle, recent))

    assert {item.activity_id for item in selected} == {
        fastest.activity_id,
        recent.activity_id,
    }
    assert all(item.evidence_kind is PerformanceEvidenceKind.STRONG_TRAINING for item in selected)


def test_stopped_or_already_verified_activities_are_not_reselected() -> None:
    stopped = _candidate(
        7,
        name="Interrupted fast run",
        achieved_on=date(2026, 4, 1),
        distance_km=10.0,
        moving_seconds=2_300,
        elapsed_seconds=3_000,
    )
    verified = _candidate(
        8,
        name="Verified 10K",
        achieved_on=date(2026, 4, 2),
        distance_km=10.0,
        moving_seconds=2_400,
    )

    selected = select_activity_performance_evidence(
        (stopped, verified),
        already_verified_activity_ids=frozenset({verified.activity_id}),
    )

    assert selected == ()
