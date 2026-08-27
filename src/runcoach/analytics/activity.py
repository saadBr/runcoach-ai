"""Deterministic per-activity running metrics."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Final

ACTIVITY_METRICS_VERSION: Final = "activity_metrics_v1"
DURATION_LOAD_METHOD: Final = "duration_minutes_v1"
HEART_RATE_ZONE_METHOD: Final = "max_hr_5_zone_v1"
MAX_SAMPLE_GAP_MS: Final = 10_000


class HeartRateZone(StrEnum):
    """Five-zone model based on percentage of observed maximum heart rate."""

    ZONE_1 = "zone_1"
    ZONE_2 = "zone_2"
    ZONE_3 = "zone_3"
    ZONE_4 = "zone_4"
    ZONE_5 = "zone_5"


@dataclass(frozen=True, slots=True)
class SensorSample:
    """Privacy-preserving sensor sample used by deterministic analytics."""

    elapsed_ms: int
    heart_rate_bpm: int | None = None
    has_position: bool = False
    cadence_spm: float | None = None
    is_paused: bool = False

    def __post_init__(self) -> None:
        if self.elapsed_ms < 0:
            raise ValueError("Sample elapsed time must be non-negative.")

        if self.heart_rate_bpm is not None and not 20 <= self.heart_rate_bpm <= 250:
            raise ValueError("Sample heart rate is outside the plausible range.")

        if self.cadence_spm is not None and (
            not isfinite(self.cadence_spm) or not 0 <= self.cadence_spm <= 300
        ):
            raise ValueError("Sample cadence is outside the plausible range.")


@dataclass(frozen=True, slots=True)
class ActivityMetricInput:
    """Canonical activity values and ordered sensor samples."""

    distance_m: float
    moving_time_ms: int
    elapsed_time_ms: int
    observed_max_hr_bpm: int | None
    samples: tuple[SensorSample, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.distance_m) or self.distance_m < 0:
            raise ValueError("Activity distance must be finite and non-negative.")

        if self.moving_time_ms < 0 or self.elapsed_time_ms < 0:
            raise ValueError("Activity durations must be non-negative.")

        if self.moving_time_ms > self.elapsed_time_ms:
            raise ValueError("Moving time cannot exceed elapsed time.")

        if self.observed_max_hr_bpm is not None and (not 100 <= self.observed_max_hr_bpm <= 250):
            raise ValueError("Observed maximum heart rate is outside the plausible range.")

        elapsed_values = tuple(sample.elapsed_ms for sample in self.samples)
        if elapsed_values != tuple(sorted(elapsed_values)):
            raise ValueError("Sensor samples must be ordered by elapsed time.")


@dataclass(frozen=True, slots=True)
class HeartRateZoneMetric:
    """Time accumulated in one heart-rate zone."""

    zone: HeartRateZone
    seconds: float
    percent_of_observed_hr_time: float


@dataclass(frozen=True, slots=True)
class ActivityMetricResult:
    """Versioned deterministic activity metrics."""

    algorithm_version: str
    average_moving_pace_seconds_per_km: float | None
    average_elapsed_pace_seconds_per_km: float | None
    heart_rate_coverage_pct: float
    gps_coverage_pct: float
    cadence_coverage_pct: float
    load_method: str
    training_load: float
    heart_rate_zone_method: str | None
    zone_distribution: tuple[HeartRateZoneMetric, ...]
    edwards_trimp: float | None
    sample_gap_cap_seconds: float


def _pace_seconds_per_km(
    duration_ms: int,
    distance_m: float,
) -> float | None:
    if duration_ms <= 0 or distance_m <= 0:
        return None

    duration_seconds = duration_ms / 1_000
    distance_km = distance_m / 1_000
    return round(duration_seconds / distance_km, 6)


def _percentage(
    observed_ms: int,
    denominator_ms: int,
) -> float:
    if denominator_ms <= 0:
        return 0.0

    bounded_observed_ms = min(observed_ms, denominator_ms)
    return round((bounded_observed_ms / denominator_ms) * 100, 4)


def _heart_rate_zone(
    heart_rate_bpm: int,
    observed_max_hr_bpm: int,
) -> HeartRateZone:
    ratio = heart_rate_bpm / observed_max_hr_bpm

    if ratio < 0.60:
        return HeartRateZone.ZONE_1
    if ratio < 0.70:
        return HeartRateZone.ZONE_2
    if ratio < 0.80:
        return HeartRateZone.ZONE_3
    if ratio < 0.90:
        return HeartRateZone.ZONE_4
    return HeartRateZone.ZONE_5


def calculate_activity_metrics(
    metric_input: ActivityMetricInput,
) -> ActivityMetricResult:
    """Calculate deterministic metrics without database or LLM dependencies."""

    effective_duration_ms = (
        metric_input.moving_time_ms
        if metric_input.moving_time_ms > 0
        else metric_input.elapsed_time_ms
    )

    heart_rate_observed_ms = 0
    position_observed_ms = 0
    cadence_observed_ms = 0
    zone_duration_ms = {zone: 0 for zone in HeartRateZone}

    for current, following in zip(
        metric_input.samples,
        metric_input.samples[1:],
        strict=False,
    ):
        raw_interval_ms = following.elapsed_ms - current.elapsed_ms
        if raw_interval_ms <= 0 or current.is_paused:
            continue

        interval_ms = min(raw_interval_ms, MAX_SAMPLE_GAP_MS)

        if current.heart_rate_bpm is not None:
            heart_rate_observed_ms += interval_ms

            if metric_input.observed_max_hr_bpm is not None:
                zone = _heart_rate_zone(
                    current.heart_rate_bpm,
                    metric_input.observed_max_hr_bpm,
                )
                zone_duration_ms[zone] += interval_ms

        if current.has_position:
            position_observed_ms += interval_ms

        if current.cadence_spm is not None:
            cadence_observed_ms += interval_ms

    zone_distribution: tuple[HeartRateZoneMetric, ...] = ()
    edwards_trimp: float | None = None

    if metric_input.observed_max_hr_bpm is not None:
        zone_distribution = tuple(
            HeartRateZoneMetric(
                zone=zone,
                seconds=round(duration_ms / 1_000, 3),
                percent_of_observed_hr_time=_percentage(
                    duration_ms,
                    heart_rate_observed_ms,
                ),
            )
            for zone, duration_ms in zone_duration_ms.items()
        )

        if heart_rate_observed_ms > 0:
            edwards_trimp = round(
                sum(
                    (zone_duration_ms[zone] / 60_000) * weight
                    for weight, zone in enumerate(
                        HeartRateZone,
                        start=1,
                    )
                ),
                6,
            )

    return ActivityMetricResult(
        algorithm_version=ACTIVITY_METRICS_VERSION,
        average_moving_pace_seconds_per_km=_pace_seconds_per_km(
            metric_input.moving_time_ms,
            metric_input.distance_m,
        ),
        average_elapsed_pace_seconds_per_km=_pace_seconds_per_km(
            metric_input.elapsed_time_ms,
            metric_input.distance_m,
        ),
        heart_rate_coverage_pct=_percentage(
            heart_rate_observed_ms,
            effective_duration_ms,
        ),
        gps_coverage_pct=_percentage(
            position_observed_ms,
            effective_duration_ms,
        ),
        cadence_coverage_pct=_percentage(
            cadence_observed_ms,
            effective_duration_ms,
        ),
        load_method=DURATION_LOAD_METHOD,
        training_load=round(effective_duration_ms / 60_000, 6),
        heart_rate_zone_method=(
            HEART_RATE_ZONE_METHOD if metric_input.observed_max_hr_bpm is not None else None
        ),
        zone_distribution=zone_distribution,
        edwards_trimp=edwards_trimp,
        sample_gap_cap_seconds=MAX_SAMPLE_GAP_MS / 1_000,
    )
