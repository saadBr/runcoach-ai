"""Golden tests for deterministic performance analysis."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from runcoach.analytics.performance import (
    DEFAULT_DISTANCE_TOLERANCE_PCT,
    DEFAULT_RIEGEL_EXPONENT,
    DISTANCE_INTERPOLATION_VERSION,
    RIEGEL_ALGORITHM_VERSION,
    ROLLING_DISTANCE_INTERPOLATION_VERSION,
    DistanceSample,
    PerformanceLabel,
    StandardDistance,
    VerifiedPerformance,
    calculate_fastest_rolling_distance_effort,
    calculate_personal_best_progression,
    calculate_standard_distance_effort,
    match_standard_distance,
    predict_riegel_time,
    standard_distance_meters,
)

FIRST_ID = UUID("018f0000-0000-7000-8000-000000000001")
SECOND_ID = UUID("018f0000-0000-7000-8000-000000000002")
THIRD_ID = UUID("018f0000-0000-7000-8000-000000000003")
FOURTH_ID = UUID("018f0000-0000-7000-8000-000000000004")


def _performance(
    *,
    activity_id: UUID,
    distance: StandardDistance,
    elapsed_time_seconds: float,
    achieved_at: datetime,
) -> VerifiedPerformance:
    return VerifiedPerformance(
        activity_id=activity_id,
        distance=distance,
        elapsed_time_seconds=elapsed_time_seconds,
        achieved_at=achieved_at,
        label=PerformanceLabel.VERIFIED_RACE,
    )


def test_standard_distances_use_official_metric_lengths() -> None:
    assert standard_distance_meters(StandardDistance.FIVE_K) == 5_000
    assert standard_distance_meters(StandardDistance.TEN_K) == 10_000
    assert standard_distance_meters(StandardDistance.HALF_MARATHON) == 21_097.5
    assert standard_distance_meters(StandardDistance.MARATHON) == 42_195


def test_riegel_prediction_matches_known_five_k_baseline() -> None:
    source = _performance(
        activity_id=FIRST_ID,
        distance=StandardDistance.FIVE_K,
        elapsed_time_seconds=19 * 60 + 41,
        achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    prediction = predict_riegel_time(source, StandardDistance.HALF_MARATHON)

    assert prediction.algorithm_version == RIEGEL_ALGORITHM_VERSION
    assert prediction.exponent == DEFAULT_RIEGEL_EXPONENT
    assert prediction.source_performance is source
    assert prediction.target_distance is StandardDistance.HALF_MARATHON
    assert prediction.predicted_time_seconds == pytest.approx(5_432.835413)
    assert prediction.predicted_pace_seconds_per_km == pytest.approx(257.510862)


def test_distance_audit_matches_nearest_standard_distance() -> None:
    match = match_standard_distance(5_030)

    assert match is not None
    assert match.distance is StandardDistance.FIVE_K
    assert match.official_distance_m == 5_000
    assert match.measured_distance_m == 5_030
    assert match.deviation_m == 30
    assert match.deviation_pct == pytest.approx(0.6)
    assert DEFAULT_DISTANCE_TOLERANCE_PCT == 3


def test_distance_audit_does_not_promote_nonstandard_distance() -> None:
    assert match_standard_distance(15_000) is None


def test_standard_distance_effort_interpolates_an_over_distance_activity() -> None:
    effort = calculate_standard_distance_effort(
        (
            DistanceSample(elapsed_ms=0, distance_m=0),
            DistanceSample(elapsed_ms=1_000_000, distance_m=4_000),
            DistanceSample(elapsed_ms=1_400_000, distance_m=6_000),
        ),
        StandardDistance.FIVE_K,
    )

    assert effort is not None
    assert effort.algorithm_version == DISTANCE_INTERPOLATION_VERSION
    assert effort.target_distance is StandardDistance.FIVE_K
    assert effort.target_distance_m == 5_000
    assert effort.finish_elapsed_ms == 1_200_000
    assert effort.elapsed_time_seconds == 1_200
    assert effort.pace_seconds_per_km == 240


def test_standard_distance_effort_returns_none_when_distance_is_not_reached() -> None:
    effort = calculate_standard_distance_effort(
        (
            DistanceSample(elapsed_ms=0, distance_m=0),
            DistanceSample(elapsed_ms=1_000_000, distance_m=4_999),
        ),
        StandardDistance.FIVE_K,
    )

    assert effort is None


def test_standard_distance_effort_rejects_non_monotonic_samples() -> None:
    with pytest.raises(ValueError, match="elapsed time"):
        calculate_standard_distance_effort(
            (
                DistanceSample(elapsed_ms=1_000, distance_m=100),
                DistanceSample(elapsed_ms=500, distance_m=200),
            ),
            StandardDistance.FIVE_K,
        )

    with pytest.raises(ValueError, match="non-decreasing"):
        calculate_standard_distance_effort(
            (
                DistanceSample(elapsed_ms=500, distance_m=200),
                DistanceSample(elapsed_ms=1_000, distance_m=100),
            ),
            StandardDistance.FIVE_K,
        )


def test_fastest_rolling_effort_finds_a_quick_segment_after_warmup() -> None:
    samples = (
        DistanceSample(elapsed_ms=0, distance_m=0),
        DistanceSample(elapsed_ms=360_000, distance_m=1_000),
        DistanceSample(elapsed_ms=600_000, distance_m=2_000),
        DistanceSample(elapsed_ms=840_000, distance_m=3_000),
        DistanceSample(elapsed_ms=1_080_000, distance_m=4_000),
        DistanceSample(elapsed_ms=1_320_000, distance_m=5_000),
        DistanceSample(elapsed_ms=1_560_000, distance_m=6_000),
    )

    effort = calculate_fastest_rolling_distance_effort(samples, StandardDistance.FIVE_K)

    assert effort is not None
    assert effort.algorithm_version == ROLLING_DISTANCE_INTERPOLATION_VERSION
    assert effort.start_elapsed_ms == 360_000
    assert effort.finish_elapsed_ms == 1_560_000
    assert effort.elapsed_time_seconds == 1_200
    assert effort.pace_seconds_per_km == 240


def test_fastest_rolling_effort_interpolates_a_segment_boundary() -> None:
    effort = calculate_fastest_rolling_distance_effort(
        (
            DistanceSample(elapsed_ms=0, distance_m=0),
            DistanceSample(elapsed_ms=300_000, distance_m=1_000),
            DistanceSample(elapsed_ms=900_000, distance_m=3_500),
            DistanceSample(elapsed_ms=1_500_000, distance_m=6_000),
        ),
        StandardDistance.FIVE_K,
    )

    assert effort is not None
    assert effort.start_elapsed_ms == 300_000
    assert effort.finish_elapsed_ms == 1_500_000
    assert effort.elapsed_time_seconds == 1_200


def test_fastest_rolling_effort_returns_none_without_enough_distance() -> None:
    effort = calculate_fastest_rolling_distance_effort(
        (
            DistanceSample(elapsed_ms=0, distance_m=0),
            DistanceSample(elapsed_ms=1_000_000, distance_m=4_999),
        ),
        StandardDistance.FIVE_K,
    )

    assert effort is None


def test_fastest_rolling_effort_excludes_distance_plateau_time() -> None:
    effort = calculate_fastest_rolling_distance_effort(
        (
            DistanceSample(elapsed_ms=0, distance_m=0),
            DistanceSample(elapsed_ms=300_000, distance_m=1_000),
            DistanceSample(elapsed_ms=400_000, distance_m=1_000),
            DistanceSample(elapsed_ms=1_400_000, distance_m=6_000),
            DistanceSample(elapsed_ms=1_500_000, distance_m=6_000),
        ),
        StandardDistance.FIVE_K,
    )

    assert effort is not None
    assert effort.start_elapsed_ms == 400_000
    assert effort.finish_elapsed_ms == 1_400_000
    assert effort.elapsed_time_seconds == 1_000


@pytest.mark.parametrize(
    ("elapsed_ms", "distance_m", "message"),
    (
        (-1, 0.0, "elapsed time"),
        (0, -1.0, "distance"),
        (0, float("inf"), "distance"),
    ),
)
def test_distance_sample_rejects_invalid_values(
    elapsed_ms: int,
    distance_m: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DistanceSample(elapsed_ms=elapsed_ms, distance_m=distance_m)


@pytest.mark.parametrize("distance_m", (0.0, -1.0, float("inf"), float("nan")))
def test_distance_audit_rejects_invalid_measured_distance(distance_m: float) -> None:
    with pytest.raises(ValueError, match="Measured distance"):
        match_standard_distance(distance_m)


@pytest.mark.parametrize("tolerance_pct", (0.0, -1.0, 10.1, float("inf"), float("nan")))
def test_distance_audit_rejects_invalid_tolerance(tolerance_pct: float) -> None:
    with pytest.raises(ValueError, match="tolerance"):
        match_standard_distance(5_000, tolerance_pct=tolerance_pct)


def test_same_distance_prediction_preserves_elapsed_time() -> None:
    source = _performance(
        activity_id=FIRST_ID,
        distance=StandardDistance.TEN_K,
        elapsed_time_seconds=2_490,
        achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    prediction = predict_riegel_time(source, StandardDistance.TEN_K)

    assert prediction.predicted_time_seconds == 2_490
    assert prediction.predicted_pace_seconds_per_km == 249


def test_personal_best_progression_is_chronological_and_distance_specific() -> None:
    performances = (
        _performance(
            activity_id=THIRD_ID,
            distance=StandardDistance.FIVE_K,
            elapsed_time_seconds=1_181,
            achieved_at=datetime(2026, 3, 1, tzinfo=UTC),
        ),
        _performance(
            activity_id=FIRST_ID,
            distance=StandardDistance.FIVE_K,
            elapsed_time_seconds=1_260,
            achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        _performance(
            activity_id=FOURTH_ID,
            distance=StandardDistance.FIVE_K,
            elapsed_time_seconds=1_200,
            achieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        _performance(
            activity_id=SECOND_ID,
            distance=StandardDistance.TEN_K,
            elapsed_time_seconds=2_490,
            achieved_at=datetime(2026, 2, 1, tzinfo=UTC),
        ),
    )

    progression = calculate_personal_best_progression(performances)

    assert [event.performance.activity_id for event in progression] == [
        FIRST_ID,
        SECOND_ID,
        THIRD_ID,
    ]
    assert [event.previous_best_seconds for event in progression] == [None, None, 1_260]


@pytest.mark.parametrize("elapsed_time_seconds", (0.0, -1.0, float("inf"), float("nan")))
def test_rejects_invalid_performance_times(elapsed_time_seconds: float) -> None:
    with pytest.raises(ValueError, match="Elapsed time"):
        _performance(
            activity_id=FIRST_ID,
            distance=StandardDistance.FIVE_K,
            elapsed_time_seconds=elapsed_time_seconds,
            achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_rejects_timezone_naive_achievement_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _performance(
            activity_id=FIRST_ID,
            distance=StandardDistance.FIVE_K,
            elapsed_time_seconds=1_200,
            achieved_at=datetime.fromisoformat("2026-01-01T00:00:00"),
        )


@pytest.mark.parametrize("exponent", (0.0, -1.0, float("inf"), float("nan")))
def test_rejects_invalid_riegel_exponents(exponent: float) -> None:
    source = _performance(
        activity_id=FIRST_ID,
        distance=StandardDistance.FIVE_K,
        elapsed_time_seconds=1_200,
        achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="exponent"):
        predict_riegel_time(
            source,
            StandardDistance.TEN_K,
            exponent=exponent,
        )
