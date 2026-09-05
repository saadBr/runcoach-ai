"""Deterministic personal-best progression and race-time baselines."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from typing import Final
from uuid import UUID

RIEGEL_ALGORITHM_VERSION: Final = "riegel_v1"
DEFAULT_RIEGEL_EXPONENT: Final = 1.06
STANDARD_DISTANCE_AUDIT_VERSION: Final = "standard_distance_audit_v1"
DEFAULT_DISTANCE_TOLERANCE_PCT: Final = 3.0
DISTANCE_INTERPOLATION_VERSION: Final = "cumulative_distance_interpolation_v1"
ROLLING_DISTANCE_INTERPOLATION_VERSION: Final = "rolling_distance_interpolation_v1"
STRAVA_BEST_EFFORT_IMPORT_VERSION: Final = "strava_best_effort_import_v1"


class StandardDistance(StrEnum):
    """Supported standard road-race distances."""

    FIVE_K = "5k"
    TEN_K = "10k"
    HALF_MARATHON = "half_marathon"
    MARATHON = "marathon"


STANDARD_DISTANCE_METERS: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 5_000.0,
    StandardDistance.TEN_K: 10_000.0,
    StandardDistance.HALF_MARATHON: 21_097.5,
    StandardDistance.MARATHON: 42_195.0,
}


class PerformanceLabel(StrEnum):
    """Human-verified labels eligible for deterministic performance analysis."""

    VERIFIED_RACE = "verified_race"
    VERIFIED_TIME_TRIAL = "verified_time_trial"
    VERIFIED_MAX_EFFORT = "verified_max_effort"


class PerformanceEffortType(StrEnum):
    """How the standard-distance performance time was obtained."""

    WHOLE_ACTIVITY = "whole_activity"
    DISTANCE_INTERPOLATION = "distance_interpolation"
    ROLLING_SEGMENT = "rolling_segment"
    PROVIDER_BEST_EFFORT = "provider_best_effort"


@dataclass(frozen=True, slots=True)
class VerifiedPerformance:
    """One verified standard-distance result backed by a canonical activity."""

    activity_id: UUID
    distance: StandardDistance
    elapsed_time_seconds: float
    achieved_at: datetime
    label: PerformanceLabel

    def __post_init__(self) -> None:
        if not isfinite(self.elapsed_time_seconds) or self.elapsed_time_seconds <= 0:
            raise ValueError("Elapsed time must be finite and positive.")

        if self.achieved_at.tzinfo is None or self.achieved_at.utcoffset() is None:
            raise ValueError("Achievement time must include timezone information.")


@dataclass(frozen=True, slots=True)
class PersonalBestEvent:
    """A verified performance that improved the standing record for its distance."""

    performance: VerifiedPerformance
    previous_best_seconds: float | None


@dataclass(frozen=True, slots=True)
class RiegelPrediction:
    """A versioned race-time projection from one verified performance."""

    algorithm_version: str
    source_performance: VerifiedPerformance
    target_distance: StandardDistance
    exponent: float
    predicted_time_seconds: float
    predicted_pace_seconds_per_km: float


@dataclass(frozen=True, slots=True)
class StandardDistanceMatch:
    """Nearest standard distance accepted by the audit tolerance."""

    distance: StandardDistance
    official_distance_m: float
    measured_distance_m: float
    deviation_m: float
    deviation_pct: float


@dataclass(frozen=True, slots=True)
class DistanceSample:
    """One cumulative-distance observation timed from activity start."""

    elapsed_ms: int
    distance_m: float

    def __post_init__(self) -> None:
        if self.elapsed_ms < 0:
            raise ValueError("Distance-sample elapsed time must be non-negative.")
        if not isfinite(self.distance_m) or self.distance_m < 0:
            raise ValueError("Distance-sample distance must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class StandardDistanceEffort:
    """Interpolated elapsed time at an exact standard-distance crossing."""

    algorithm_version: str
    target_distance: StandardDistance
    target_distance_m: float
    finish_elapsed_ms: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float


@dataclass(frozen=True, slots=True)
class RollingDistanceEffort:
    """Fastest exact-distance segment supported by cumulative trackpoints."""

    algorithm_version: str
    target_distance: StandardDistance
    target_distance_m: float
    start_elapsed_ms: float
    finish_elapsed_ms: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float


def standard_distance_meters(distance: StandardDistance) -> float:
    """Return the exact distance represented by a supported race label."""

    return STANDARD_DISTANCE_METERS[distance]


def match_standard_distance(
    measured_distance_m: float,
    *,
    tolerance_pct: float = DEFAULT_DISTANCE_TOLERANCE_PCT,
) -> StandardDistanceMatch | None:
    """Match a whole-activity distance without asserting that it was a race."""

    if not isfinite(measured_distance_m) or measured_distance_m <= 0:
        raise ValueError("Measured distance must be finite and positive.")

    if not isfinite(tolerance_pct) or not 0 < tolerance_pct <= 10:
        raise ValueError("Distance tolerance must be greater than zero and at most 10 percent.")

    distance, official_distance_m = min(
        STANDARD_DISTANCE_METERS.items(),
        key=lambda item: abs(measured_distance_m - item[1]),
    )
    deviation_m = abs(measured_distance_m - official_distance_m)
    deviation_pct = (deviation_m / official_distance_m) * 100

    if deviation_pct > tolerance_pct:
        return None

    return StandardDistanceMatch(
        distance=distance,
        official_distance_m=official_distance_m,
        measured_distance_m=measured_distance_m,
        deviation_m=round(deviation_m, 6),
        deviation_pct=round(deviation_pct, 6),
    )


def calculate_standard_distance_effort(
    samples: tuple[DistanceSample, ...],
    target_distance: StandardDistance,
) -> StandardDistanceEffort | None:
    """Interpolate elapsed time where cumulative distance first reaches the target."""

    if not samples:
        return None

    _validate_distance_samples(samples)

    target_distance_m = standard_distance_meters(target_distance)
    finish_elapsed_ms: float | None = None

    if samples[0].distance_m == target_distance_m:
        finish_elapsed_ms = float(samples[0].elapsed_ms)

    for previous, current in pairwise(samples):
        if finish_elapsed_ms is not None:
            break
        if not previous.distance_m <= target_distance_m <= current.distance_m:
            continue

        distance_delta_m = current.distance_m - previous.distance_m
        if distance_delta_m == 0:
            continue

        interpolation_fraction = (target_distance_m - previous.distance_m) / distance_delta_m
        finish_elapsed_ms = previous.elapsed_ms + interpolation_fraction * (
            current.elapsed_ms - previous.elapsed_ms
        )

    if finish_elapsed_ms is None:
        return None

    elapsed_time_seconds = finish_elapsed_ms / 1_000
    return StandardDistanceEffort(
        algorithm_version=DISTANCE_INTERPOLATION_VERSION,
        target_distance=target_distance,
        target_distance_m=target_distance_m,
        finish_elapsed_ms=round(finish_elapsed_ms, 3),
        elapsed_time_seconds=round(elapsed_time_seconds, 6),
        pace_seconds_per_km=round(
            elapsed_time_seconds / (target_distance_m / 1_000),
            6,
        ),
    )


def _validate_distance_samples(samples: tuple[DistanceSample, ...]) -> None:
    elapsed_values = tuple(sample.elapsed_ms for sample in samples)
    if elapsed_values != tuple(sorted(elapsed_values)):
        raise ValueError("Distance samples must be ordered by elapsed time.")

    distance_values = tuple(sample.distance_m for sample in samples)
    if distance_values != tuple(sorted(distance_values)):
        raise ValueError("Cumulative distance must be non-decreasing.")


def _elapsed_at_distance(
    samples: tuple[DistanceSample, ...],
    distance_values: tuple[float, ...],
    target_distance_m: float,
    *,
    start_boundary: bool,
) -> float | None:
    """Interpolate elapsed time, resolving distance plateaus conservatively."""

    right_index = bisect_left(distance_values, target_distance_m)
    if right_index == len(samples):
        return None

    if distance_values[right_index] == target_distance_m:
        index = (
            bisect_right(distance_values, target_distance_m) - 1 if start_boundary else right_index
        )
        return float(samples[index].elapsed_ms)

    if right_index == 0:
        return None

    previous = samples[right_index - 1]
    current = samples[right_index]
    distance_delta_m = current.distance_m - previous.distance_m
    if distance_delta_m <= 0:
        return None

    interpolation_fraction = (target_distance_m - previous.distance_m) / distance_delta_m
    return previous.elapsed_ms + interpolation_fraction * (current.elapsed_ms - previous.elapsed_ms)


def calculate_fastest_rolling_distance_effort(
    samples: tuple[DistanceSample, ...],
    target_distance: StandardDistance,
) -> RollingDistanceEffort | None:
    """Return the fastest rolling exact-distance effort in one activity.

    Candidate boundaries include every piecewise-linear breakpoint at either
    the segment start or finish. This finds the exact minimum without treating
    individual trackpoints as exact standard-distance boundaries.
    """

    if not samples:
        return None

    _validate_distance_samples(samples)
    target_distance_m = standard_distance_meters(target_distance)
    distance_values = tuple(sample.distance_m for sample in samples)
    minimum_distance_m = distance_values[0]
    maximum_distance_m = distance_values[-1]
    if maximum_distance_m - minimum_distance_m < target_distance_m:
        return None

    maximum_start_m = maximum_distance_m - target_distance_m
    candidate_starts_m = {
        distance_m
        for distance_m in distance_values
        if minimum_distance_m <= distance_m <= maximum_start_m
    }
    candidate_starts_m.update(
        distance_m - target_distance_m
        for distance_m in distance_values
        if minimum_distance_m <= distance_m - target_distance_m <= maximum_start_m
    )

    best: tuple[float, float, float] | None = None
    for start_distance_m in candidate_starts_m:
        finish_distance_m = start_distance_m + target_distance_m
        start_elapsed_ms = _elapsed_at_distance(
            samples,
            distance_values,
            start_distance_m,
            start_boundary=True,
        )
        finish_elapsed_ms = _elapsed_at_distance(
            samples,
            distance_values,
            finish_distance_m,
            start_boundary=False,
        )
        if start_elapsed_ms is None or finish_elapsed_ms is None:
            continue

        elapsed_ms = finish_elapsed_ms - start_elapsed_ms
        if elapsed_ms <= 0:
            continue

        candidate = (elapsed_ms, start_elapsed_ms, finish_elapsed_ms)
        if best is None or candidate < best:
            best = candidate

    if best is None:
        return None

    elapsed_ms, start_elapsed_ms, finish_elapsed_ms = best
    elapsed_time_seconds = elapsed_ms / 1_000
    return RollingDistanceEffort(
        algorithm_version=ROLLING_DISTANCE_INTERPOLATION_VERSION,
        target_distance=target_distance,
        target_distance_m=target_distance_m,
        start_elapsed_ms=round(start_elapsed_ms, 3),
        finish_elapsed_ms=round(finish_elapsed_ms, 3),
        elapsed_time_seconds=round(elapsed_time_seconds, 6),
        pace_seconds_per_km=round(
            elapsed_time_seconds / (target_distance_m / 1_000),
            6,
        ),
    )


def calculate_personal_best_progression(
    performances: tuple[VerifiedPerformance, ...],
) -> tuple[PersonalBestEvent, ...]:
    """Return every chronological improvement, keeping distances independent."""

    ordered = sorted(
        performances,
        key=lambda item: (
            item.achieved_at,
            item.elapsed_time_seconds,
            str(item.activity_id),
        ),
    )
    best_by_distance: dict[StandardDistance, VerifiedPerformance] = {}
    progression: list[PersonalBestEvent] = []

    for performance in ordered:
        previous = best_by_distance.get(performance.distance)
        if (
            previous is not None
            and performance.elapsed_time_seconds >= previous.elapsed_time_seconds
        ):
            continue

        progression.append(
            PersonalBestEvent(
                performance=performance,
                previous_best_seconds=(
                    previous.elapsed_time_seconds if previous is not None else None
                ),
            )
        )
        best_by_distance[performance.distance] = performance

    return tuple(progression)


def predict_riegel_time(
    source_performance: VerifiedPerformance,
    target_distance: StandardDistance,
    *,
    exponent: float = DEFAULT_RIEGEL_EXPONENT,
) -> RiegelPrediction:
    """Project a target time with T2 = T1 * (D2 / D1) ** exponent."""

    if not isfinite(exponent) or exponent <= 0:
        raise ValueError("Riegel exponent must be finite and positive.")

    source_distance_m = standard_distance_meters(source_performance.distance)
    target_distance_m = standard_distance_meters(target_distance)
    predicted_time_seconds = (
        source_performance.elapsed_time_seconds
        * (target_distance_m / source_distance_m) ** exponent
    )

    return RiegelPrediction(
        algorithm_version=RIEGEL_ALGORITHM_VERSION,
        source_performance=source_performance,
        target_distance=target_distance,
        exponent=exponent,
        predicted_time_seconds=round(predicted_time_seconds, 6),
        predicted_pace_seconds_per_km=round(
            predicted_time_seconds / (target_distance_m / 1_000),
            6,
        ),
    )
