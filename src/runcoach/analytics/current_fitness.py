"""Transparent current-fitness estimates from performance and training evidence."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Final, Literal

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
    standard_distance_meters,
)
from runcoach.analytics.session_classification import SessionKind

CURRENT_FITNESS_ALGORITHM_VERSION: Final = "training_context_fitness_v2"

type EstimateConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class FitnessMark:
    """One verified performance used by the current-fitness estimator."""

    distance: StandardDistance
    elapsed_time_seconds: float
    achieved_on: date
    verification_status: PerformanceLabel = PerformanceLabel.VERIFIED_RACE
    effort_type: PerformanceEffortType = PerformanceEffortType.WHOLE_ACTIVITY
    activity_distance_km: float | None = None
    session_kind: SessionKind = SessionKind.UNCLASSIFIED

    def __post_init__(self) -> None:
        if not isfinite(self.elapsed_time_seconds) or self.elapsed_time_seconds <= 0:
            raise ValueError("Fitness-mark time must be finite and positive.")
        if self.activity_distance_km is not None and (
            not isfinite(self.activity_distance_km) or self.activity_distance_km <= 0
        ):
            raise ValueError("Fitness-mark activity distance must be finite and positive.")


@dataclass(frozen=True, slots=True)
class TrainingProfile:
    """Multi-horizon training completed through an evidence cutoff."""

    as_of_date: date
    runs_28d: int
    distance_28d_km: float
    runs_84d: int
    distance_84d_km: float
    longest_run_84d_km: float | None
    classified_sessions_84d: int
    quality_sessions_84d: int
    runs_168d: int
    distance_168d_km: float
    runs_365d: int
    distance_365d_km: float

    def __post_init__(self) -> None:
        if min(self.runs_28d, self.runs_84d, self.runs_168d, self.runs_365d) < 0:
            raise ValueError("Training-profile run counts must be non-negative.")
        if self.classified_sessions_84d < 0 or self.quality_sessions_84d < 0:
            raise ValueError("Training-profile session counts must be non-negative.")
        for value in (
            self.distance_28d_km,
            self.distance_84d_km,
            self.distance_168d_km,
            self.distance_365d_km,
        ):
            if not isfinite(value) or value < 0:
                raise ValueError("Training-profile distances must be finite and non-negative.")
        if self.longest_run_84d_km is not None and (
            not isfinite(self.longest_run_84d_km) or self.longest_run_84d_km < 0
        ):
            raise ValueError("Training-profile longest run must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class CurrentFitnessEstimate:
    """One distance estimate with capability and preparation separated."""

    distance: StandardDistance
    fitness_potential_time_seconds: float
    race_readiness_time_seconds: float
    optimistic_time_seconds: float
    conservative_time_seconds: float
    fitness_potential_pace_seconds_per_km: float
    race_readiness_pace_seconds_per_km: float
    preparation_score: float
    confidence: EstimateConfidence
    current_pb_seconds: float
    improvement_from_pb_seconds: float
    basis: str


@dataclass(frozen=True, slots=True)
class CurrentFitnessAssessment:
    """Versioned experimental assessment for all supported distances."""

    algorithm_version: str
    status: str
    as_of_date: date
    anchor: FitnessMark
    prior_anchor: FitnessMark | None
    anchor_capacity_factor: float
    anchor_improvement_factor: float
    training: TrainingProfile
    estimates: tuple[CurrentFitnessEstimate, ...]
    limitations: tuple[str, ...]


_RANGE_WIDTH: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 0.01,
    StandardDistance.TEN_K: 0.015,
    StandardDistance.HALF_MARATHON: 0.025,
    StandardDistance.MARATHON: 0.04,
}

_VOLUME_SENSITIVITY: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 0.0,
    StandardDistance.TEN_K: 0.003,
    StandardDistance.HALF_MARATHON: 0.008,
    StandardDistance.MARATHON: 0.045,
}

_LONG_RUN_SENSITIVITY: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 0.0,
    StandardDistance.TEN_K: 0.0,
    StandardDistance.HALF_MARATHON: 0.005,
    StandardDistance.MARATHON: 0.02,
}

_PREPARATION_TARGETS: Final[dict[StandardDistance, tuple[int, float, float]]] = {
    StandardDistance.FIVE_K: (18, 120.0, 10.0),
    StandardDistance.TEN_K: (24, 240.0, 15.0),
    StandardDistance.HALF_MARATHON: (36, 420.0, 24.0),
    StandardDistance.MARATHON: (48, 650.0, 35.0),
}

_MAX_READINESS_PENALTY: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 0.01,
    StandardDistance.TEN_K: 0.015,
    StandardDistance.HALF_MARATHON: 0.03,
    StandardDistance.MARATHON: 0.08,
}

_EMBEDDED_QUALITY_RESERVE: Final = 0.96
_STANDALONE_MAX_EFFORT_RESERVE: Final = 0.985


def _anchor_capacity_factor(anchor: FitnessMark) -> float:
    target_km = standard_distance_meters(anchor.distance) / 1_000
    embedded_effort = (
        anchor.activity_distance_km is not None
        and anchor.activity_distance_km >= target_km * 1.5
        and anchor.effort_type is not PerformanceEffortType.WHOLE_ACTIVITY
    )
    quality_session = anchor.session_kind in {
        SessionKind.HILLS,
        SessionKind.INTERVALS,
        SessionKind.TEMPO,
        SessionKind.PROGRESSIVE,
    }
    if embedded_effort and quality_session:
        return _EMBEDDED_QUALITY_RESERVE
    if anchor.verification_status is PerformanceLabel.VERIFIED_MAX_EFFORT:
        return _STANDALONE_MAX_EFFORT_RESERVE
    return 1.0


def _bounded_ratio(current: float, reference: float) -> float | None:
    if reference <= 0:
        return None
    return min(max(current / reference, 0.75), 4.0)


def _endurance_adjustment(
    *,
    distance: StandardDistance,
    current: TrainingProfile,
    reference: TrainingProfile | None,
) -> float:
    if reference is None or distance is StandardDistance.FIVE_K:
        return 1.0

    volume_ratio = _bounded_ratio(current.distance_84d_km, reference.distance_84d_km)
    long_run_ratio = _bounded_ratio(
        current.longest_run_84d_km or 0.0,
        reference.longest_run_84d_km or 0.0,
    )
    adjustment = 1.0
    if volume_ratio is not None:
        adjustment *= volume_ratio ** -_VOLUME_SENSITIVITY[distance]
    if long_run_ratio is not None:
        adjustment *= long_run_ratio ** -_LONG_RUN_SENSITIVITY[distance]
    return min(max(adjustment, 0.90), 1.03)


def _preparation_score(distance: StandardDistance, training: TrainingProfile) -> float:
    required_runs, required_distance_km, required_long_run_km = _PREPARATION_TARGETS[distance]
    run_score = min(training.runs_84d / required_runs, 1.0)
    volume_score = min(training.distance_84d_km / required_distance_km, 1.0)
    long_run_score = min((training.longest_run_84d_km or 0.0) / required_long_run_km, 1.0)
    return round(0.15 * run_score + 0.45 * volume_score + 0.40 * long_run_score, 6)


def _confidence(
    *,
    mark: FitnessMark,
    anchor: FitnessMark,
    as_of_date: date,
    training: TrainingProfile,
    preparation_score: float,
    has_prior_anchor: bool,
) -> EstimateConfidence:
    age_days = (as_of_date - mark.achieved_on).days
    if (
        mark.distance is anchor.distance
        and anchor.session_kind is not SessionKind.UNCLASSIFIED
        and training.runs_84d >= 20
    ):
        return "high"
    if (
        has_prior_anchor
        and age_days <= 180
        and preparation_score >= 0.85
        and training.runs_84d >= 20
    ):
        return "medium"
    return "low"


def estimate_current_fitness(
    *,
    current_marks: tuple[FitnessMark, ...],
    anchor: FitnessMark,
    prior_anchor: FitnessMark | None,
    training: TrainingProfile,
    reference_training_by_distance: Mapping[StandardDistance, TrainingProfile] | None,
) -> CurrentFitnessAssessment:
    """Estimate flat-course potential and distance-specific race readiness.

    The newest verified mark anchors current short-distance capacity. A bounded reserve is
    applied when that mark came from a best-effort segment embedded inside a longer quality
    session. Improvement is transferred through the athlete's own PB curve, then each target
    is adjusted using training completed now versus immediately before that PB. Finally, a
    preparation score distinguishes general fitness from distance-specific readiness.
    """

    if not current_marks:
        raise ValueError("At least one current fitness mark is required.")
    marks_by_distance = {mark.distance: mark for mark in current_marks}
    if len(marks_by_distance) != len(current_marks):
        raise ValueError("Current fitness marks must contain unique distances.")
    if marks_by_distance.get(anchor.distance) != anchor:
        raise ValueError("The current anchor must be included in current fitness marks.")
    if prior_anchor is not None and (
        prior_anchor.distance is not anchor.distance
        or prior_anchor.achieved_on >= anchor.achieved_on
    ):
        raise ValueError("The prior anchor must be an older mark at the anchor distance.")

    capacity_factor = _anchor_capacity_factor(anchor)
    anchor_capacity_seconds = anchor.elapsed_time_seconds * capacity_factor
    anchor_improvement = (
        min(anchor_capacity_seconds / prior_anchor.elapsed_time_seconds, 1.0)
        if prior_anchor is not None
        else capacity_factor
    )
    references = reference_training_by_distance or {}
    estimates: list[CurrentFitnessEstimate] = []

    for distance in StandardDistance:
        mark = marks_by_distance.get(distance)
        if mark is None:
            continue

        potential = (
            anchor_capacity_seconds
            if distance is anchor.distance
            else mark.elapsed_time_seconds * anchor_improvement
        )
        endurance_adjustment = _endurance_adjustment(
            distance=distance,
            current=training,
            reference=references.get(distance),
        )
        potential *= endurance_adjustment
        potential = min(potential, mark.elapsed_time_seconds)

        preparation_score = _preparation_score(distance, training)
        readiness_factor = 1 + _MAX_READINESS_PENALTY[distance] * (1 - preparation_score)
        readiness = potential * readiness_factor
        readiness = min(readiness, mark.elapsed_time_seconds)

        width = _RANGE_WIDTH[distance] * (1 + 0.5 * (1 - preparation_score))
        optimistic = readiness * (1 - width)
        conservative = readiness * (1 + width)
        distance_km = standard_distance_meters(distance) / 1_000
        reference = references.get(distance)
        basis = (
            "Current capability is anchored to the newest verified effort and the athlete's "
            "personal PB curve."
        )
        if capacity_factor < 1:
            basis += " The anchor includes a bounded reserve for an embedded quality effort."
        if reference is not None and endurance_adjustment != 1:
            basis += " Training change since this PB adjusts distance-specific potential."
        basis += " Recent volume, frequency, and longest run determine race readiness."

        estimates.append(
            CurrentFitnessEstimate(
                distance=distance,
                fitness_potential_time_seconds=round(potential, 3),
                race_readiness_time_seconds=round(readiness, 3),
                optimistic_time_seconds=round(optimistic, 3),
                conservative_time_seconds=round(conservative, 3),
                fitness_potential_pace_seconds_per_km=round(potential / distance_km, 6),
                race_readiness_pace_seconds_per_km=round(readiness / distance_km, 6),
                preparation_score=preparation_score,
                confidence=_confidence(
                    mark=mark,
                    anchor=anchor,
                    as_of_date=training.as_of_date,
                    training=training,
                    preparation_score=preparation_score,
                    has_prior_anchor=prior_anchor is not None,
                ),
                current_pb_seconds=mark.elapsed_time_seconds,
                improvement_from_pb_seconds=round(mark.elapsed_time_seconds - readiness, 3),
                basis=basis,
            )
        )

    return CurrentFitnessAssessment(
        algorithm_version=CURRENT_FITNESS_ALGORITHM_VERSION,
        status="experimental_not_validated",
        as_of_date=training.as_of_date,
        anchor=anchor,
        prior_anchor=prior_anchor,
        anchor_capacity_factor=round(capacity_factor, 6),
        anchor_improvement_factor=round(anchor_improvement, 6),
        training=training,
        estimates=tuple(estimates),
        limitations=(
            "Fitness potential assumes a flat course, favorable conditions, and a full effort.",
            "Race readiness is a deterministic training-evidence adjustment, not a guarantee.",
            "The model is personalized to one athlete but is not yet chronologically validated.",
            "Weather, taper, illness, sleep, terrain, and race execution are not modeled yet.",
        ),
    )
