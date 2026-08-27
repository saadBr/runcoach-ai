"""Golden tests for deterministic per-activity metrics."""

import pytest

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
    HEART_RATE_ZONE_METHOD,
    ActivityMetricInput,
    HeartRateZone,
    SensorSample,
    calculate_activity_metrics,
)


def test_calculates_pace_coverage_zones_and_training_load() -> None:
    metric_input = ActivityMetricInput(
        distance_m=200,
        moving_time_ms=50_000,
        elapsed_time_ms=60_000,
        observed_max_hr_bpm=200,
        samples=(
            SensorSample(
                elapsed_ms=0,
                heart_rate_bpm=100,
                has_position=True,
                cadence_spm=170,
            ),
            SensorSample(
                elapsed_ms=10_000,
                heart_rate_bpm=130,
                has_position=True,
                cadence_spm=172,
            ),
            SensorSample(
                elapsed_ms=20_000,
                heart_rate_bpm=150,
                has_position=False,
                cadence_spm=174,
            ),
            SensorSample(
                elapsed_ms=30_000,
                heart_rate_bpm=170,
                has_position=False,
                cadence_spm=None,
            ),
            SensorSample(
                elapsed_ms=40_000,
                heart_rate_bpm=190,
                has_position=True,
                cadence_spm=None,
            ),
            SensorSample(
                elapsed_ms=50_000,
                heart_rate_bpm=190,
                has_position=True,
                cadence_spm=None,
            ),
        ),
    )

    result = calculate_activity_metrics(metric_input)

    assert result.algorithm_version == ACTIVITY_METRICS_VERSION
    assert result.average_moving_pace_seconds_per_km == 250
    assert result.average_elapsed_pace_seconds_per_km == 300
    assert result.heart_rate_coverage_pct == 100
    assert result.gps_coverage_pct == 60
    assert result.cadence_coverage_pct == 60
    assert result.load_method == DURATION_LOAD_METHOD
    assert result.training_load == pytest.approx(0.833333)
    assert result.heart_rate_zone_method == HEART_RATE_ZONE_METHOD
    assert result.edwards_trimp == pytest.approx(2.5)
    assert result.sample_gap_cap_seconds == 10

    zones = {zone_metric.zone: zone_metric for zone_metric in result.zone_distribution}
    assert set(zones) == set(HeartRateZone)

    for zone in HeartRateZone:
        assert zones[zone].seconds == 10
        assert zones[zone].percent_of_observed_hr_time == 20


def test_heart_rate_coverage_does_not_require_a_profile() -> None:
    result = calculate_activity_metrics(
        ActivityMetricInput(
            distance_m=1_000,
            moving_time_ms=10_000,
            elapsed_time_ms=10_000,
            observed_max_hr_bpm=None,
            samples=(
                SensorSample(
                    elapsed_ms=0,
                    heart_rate_bpm=150,
                ),
                SensorSample(
                    elapsed_ms=10_000,
                    heart_rate_bpm=151,
                ),
            ),
        )
    )

    assert result.heart_rate_coverage_pct == 100
    assert result.heart_rate_zone_method is None
    assert result.zone_distribution == ()
    assert result.edwards_trimp is None


def test_large_sensor_gap_is_capped_instead_of_claiming_full_coverage() -> None:
    result = calculate_activity_metrics(
        ActivityMetricInput(
            distance_m=1_000,
            moving_time_ms=60_000,
            elapsed_time_ms=60_000,
            observed_max_hr_bpm=195,
            samples=(
                SensorSample(
                    elapsed_ms=0,
                    heart_rate_bpm=150,
                    has_position=True,
                    cadence_spm=170,
                ),
                SensorSample(
                    elapsed_ms=60_000,
                    heart_rate_bpm=151,
                    has_position=True,
                    cadence_spm=171,
                ),
            ),
        )
    )

    assert result.heart_rate_coverage_pct == pytest.approx(16.6667)
    assert result.gps_coverage_pct == pytest.approx(16.6667)
    assert result.cadence_coverage_pct == pytest.approx(16.6667)


def test_paused_interval_is_excluded_from_sensor_coverage() -> None:
    result = calculate_activity_metrics(
        ActivityMetricInput(
            distance_m=100,
            moving_time_ms=20_000,
            elapsed_time_ms=30_000,
            observed_max_hr_bpm=195,
            samples=(
                SensorSample(
                    elapsed_ms=0,
                    heart_rate_bpm=140,
                    has_position=True,
                    cadence_spm=170,
                    is_paused=True,
                ),
                SensorSample(
                    elapsed_ms=10_000,
                    heart_rate_bpm=150,
                    has_position=True,
                    cadence_spm=175,
                ),
                SensorSample(
                    elapsed_ms=20_000,
                    heart_rate_bpm=151,
                    has_position=True,
                    cadence_spm=176,
                ),
            ),
        )
    )

    assert result.heart_rate_coverage_pct == 50
    assert result.gps_coverage_pct == 50
    assert result.cadence_coverage_pct == 50


def test_elapsed_duration_is_load_fallback_when_moving_time_is_zero() -> None:
    result = calculate_activity_metrics(
        ActivityMetricInput(
            distance_m=0,
            moving_time_ms=0,
            elapsed_time_ms=60_000,
            observed_max_hr_bpm=None,
            samples=(),
        )
    )

    assert result.average_moving_pace_seconds_per_km is None
    assert result.average_elapsed_pace_seconds_per_km is None
    assert result.training_load == 1
    assert result.heart_rate_coverage_pct == 0


@pytest.mark.parametrize(
    ("metric_input", "message"),
    (
        (
            ActivityMetricInput(
                distance_m=1_000,
                moving_time_ms=10_000,
                elapsed_time_ms=10_000,
                observed_max_hr_bpm=195,
                samples=(),
            ),
            "",
        ),
    ),
)
def test_valid_input_control(
    metric_input: ActivityMetricInput,
    message: str,
) -> None:
    del message
    assert calculate_activity_metrics(metric_input).training_load > 0


def test_rejects_invalid_activity_and_sample_values() -> None:
    with pytest.raises(ValueError, match="Moving time"):
        ActivityMetricInput(
            distance_m=1_000,
            moving_time_ms=20_000,
            elapsed_time_ms=10_000,
            observed_max_hr_bpm=195,
            samples=(),
        )

    with pytest.raises(ValueError, match="ordered"):
        ActivityMetricInput(
            distance_m=1_000,
            moving_time_ms=10_000,
            elapsed_time_ms=10_000,
            observed_max_hr_bpm=195,
            samples=(
                SensorSample(elapsed_ms=5_000),
                SensorSample(elapsed_ms=1_000),
            ),
        )

    with pytest.raises(ValueError, match="heart rate"):
        SensorSample(
            elapsed_ms=0,
            heart_rate_bpm=300,
        )

    with pytest.raises(ValueError, match="cadence"):
        SensorSample(
            elapsed_ms=0,
            cadence_spm=400,
        )
