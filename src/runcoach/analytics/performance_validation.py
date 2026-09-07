"""Leakage-safe chronological validation for race-time baselines."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean, median
from typing import Final, Literal
from uuid import UUID

from runcoach.analytics.performance import (
    StandardDistance,
    VerifiedPerformance,
    predict_riegel_time,
)

PERFORMANCE_VALIDATION_VERSION: Final = "performance_validation_v1"
MINIMUM_VERIFIED_LABELS: Final = 30
MINIMUM_CHRONOLOGICAL_PREDICTIONS: Final = 8

type BaselineName = Literal[
    "riegel_best_prior",
    "recent_same_distance",
    "historical_median_same_distance",
]


@dataclass(frozen=True, slots=True)
class PerformanceObservation:
    """One manually verified outcome eligible for chronological evaluation."""

    observation_id: UUID
    performance: VerifiedPerformance

    def __post_init__(self) -> None:
        if self.observation_id != self.performance.activity_id:
            raise ValueError("Observation and performance identifiers must match.")


@dataclass(frozen=True, slots=True)
class ChronologicalPrediction:
    """One prediction made exclusively from verified earlier observations."""

    baseline: BaselineName
    target_observation_id: UUID
    target_distance: StandardDistance
    target_achieved_at: datetime
    actual_time_seconds: float
    predicted_time_seconds: float
    signed_error_seconds: float
    absolute_error_seconds: float
    absolute_percentage_error: float
    source_observation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class BaselineMetrics:
    """Aggregate chronological error for one baseline and optional distance."""

    baseline: BaselineName
    target_distance: StandardDistance | None
    predictions: int
    mean_absolute_error_seconds: float
    median_absolute_error_seconds: float
    mean_absolute_percentage_error: float
    mean_signed_error_seconds: float


@dataclass(frozen=True, slots=True)
class PerformanceValidationReport:
    """Reproducible validation result and learned-model eligibility decision."""

    validation_version: str
    status: str
    verified_labels: int
    represented_distances: tuple[StandardDistance, ...]
    chronological_targets: int
    candidate_model_eligible: bool
    eligibility_reasons: tuple[str, ...]
    predictions: tuple[ChronologicalPrediction, ...]
    metrics: tuple[BaselineMetrics, ...]
    leakage_rule: str


def _prediction(
    *,
    baseline: BaselineName,
    target: PerformanceObservation,
    predicted_time_seconds: float,
    source_ids: tuple[UUID, ...],
) -> ChronologicalPrediction:
    actual = target.performance.elapsed_time_seconds
    signed_error = predicted_time_seconds - actual
    return ChronologicalPrediction(
        baseline=baseline,
        target_observation_id=target.observation_id,
        target_distance=target.performance.distance,
        target_achieved_at=target.performance.achieved_at,
        actual_time_seconds=round(actual, 3),
        predicted_time_seconds=round(predicted_time_seconds, 3),
        signed_error_seconds=round(signed_error, 3),
        absolute_error_seconds=round(abs(signed_error), 3),
        absolute_percentage_error=round(abs(signed_error) / actual * 100, 6),
        source_observation_ids=source_ids,
    )


def _riegel_prediction(
    target: PerformanceObservation,
    prior: tuple[PerformanceObservation, ...],
) -> ChronologicalPrediction | None:
    if not prior:
        return None
    candidates = tuple(
        (
            source,
            predict_riegel_time(
                source.performance,
                target.performance.distance,
            ).predicted_time_seconds,
        )
        for source in prior
    )
    source, predicted = min(candidates, key=lambda item: item[1])
    return _prediction(
        baseline="riegel_best_prior",
        target=target,
        predicted_time_seconds=predicted,
        source_ids=(source.observation_id,),
    )


def _same_distance_predictions(
    target: PerformanceObservation,
    prior: tuple[PerformanceObservation, ...],
) -> tuple[ChronologicalPrediction, ...]:
    matching = tuple(
        item for item in prior if item.performance.distance is target.performance.distance
    )
    if not matching:
        return ()
    recent = max(matching, key=lambda item: item.performance.achieved_at)
    historical_time = median(item.performance.elapsed_time_seconds for item in matching)
    return (
        _prediction(
            baseline="recent_same_distance",
            target=target,
            predicted_time_seconds=recent.performance.elapsed_time_seconds,
            source_ids=(recent.observation_id,),
        ),
        _prediction(
            baseline="historical_median_same_distance",
            target=target,
            predicted_time_seconds=historical_time,
            source_ids=tuple(item.observation_id for item in matching),
        ),
    )


def _metrics(
    baseline: BaselineName,
    predictions: tuple[ChronologicalPrediction, ...],
    target_distance: StandardDistance | None,
) -> BaselineMetrics:
    if not predictions:
        raise ValueError("At least one prediction is required to calculate metrics.")
    return BaselineMetrics(
        baseline=baseline,
        target_distance=target_distance,
        predictions=len(predictions),
        mean_absolute_error_seconds=round(
            fmean(item.absolute_error_seconds for item in predictions),
            3,
        ),
        median_absolute_error_seconds=round(
            median(item.absolute_error_seconds for item in predictions),
            3,
        ),
        mean_absolute_percentage_error=round(
            fmean(item.absolute_percentage_error for item in predictions),
            6,
        ),
        mean_signed_error_seconds=round(
            fmean(item.signed_error_seconds for item in predictions),
            3,
        ),
    )


def _aggregate_metrics(
    predictions: tuple[ChronologicalPrediction, ...],
) -> tuple[BaselineMetrics, ...]:
    grouped: dict[BaselineName, list[ChronologicalPrediction]] = defaultdict(list)
    grouped_by_distance: dict[
        tuple[BaselineName, StandardDistance], list[ChronologicalPrediction]
    ] = defaultdict(list)
    for item in predictions:
        grouped[item.baseline].append(item)
        grouped_by_distance[(item.baseline, item.target_distance)].append(item)

    results: list[BaselineMetrics] = []
    for baseline in sorted(grouped):
        values = tuple(grouped[baseline])
        results.append(_metrics(baseline, values, None))
        distances = sorted(
            (key[1] for key in grouped_by_distance if key[0] == baseline),
            key=lambda item: item.value,
        )
        for distance in distances:
            results.append(
                _metrics(
                    baseline,
                    tuple(grouped_by_distance[(baseline, distance)]),
                    distance,
                )
            )
    return tuple(results)


def evaluate_performance_baselines(
    observations: tuple[PerformanceObservation, ...],
) -> PerformanceValidationReport:
    """Evaluate baselines in event order while excluding current and future evidence."""

    if len({item.observation_id for item in observations}) != len(observations):
        raise ValueError("Performance observation identifiers must be unique.")
    for item in observations:
        seconds = item.performance.elapsed_time_seconds
        if not isfinite(seconds) or seconds <= 0:
            raise ValueError("Verified performance times must be finite and positive.")

    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (item.performance.achieved_at, str(item.observation_id)),
        )
    )
    predictions: list[ChronologicalPrediction] = []
    chronological_target_ids: set[UUID] = set()
    for target in ordered:
        prior = tuple(
            item
            for item in ordered
            if item.performance.achieved_at < target.performance.achieved_at
        )
        riegel = _riegel_prediction(target, prior)
        if riegel is not None:
            predictions.append(riegel)
            chronological_target_ids.add(target.observation_id)
        predictions.extend(_same_distance_predictions(target, prior))

    represented_distances = tuple(
        sorted({item.performance.distance for item in ordered}, key=lambda item: item.value)
    )
    reasons: list[str] = []
    if len(ordered) < MINIMUM_VERIFIED_LABELS:
        reasons.append(
            f"{len(ordered)} verified labels are available; at least "
            f"{MINIMUM_VERIFIED_LABELS} are required."
        )
    if len(chronological_target_ids) < MINIMUM_CHRONOLOGICAL_PREDICTIONS:
        reasons.append(
            f"{len(chronological_target_ids)} later events can be predicted; at least "
            f"{MINIMUM_CHRONOLOGICAL_PREDICTIONS} are required."
        )
    if len(represented_distances) < 2:
        reasons.append("Verified labels must represent more than one target distance.")

    eligible = not reasons
    return PerformanceValidationReport(
        validation_version=PERFORMANCE_VALIDATION_VERSION,
        status="eligible_for_candidate_model" if eligible else "descriptive_only",
        verified_labels=len(ordered),
        represented_distances=represented_distances,
        chronological_targets=len(chronological_target_ids),
        candidate_model_eligible=eligible,
        eligibility_reasons=tuple(reasons),
        predictions=tuple(predictions),
        metrics=_aggregate_metrics(tuple(predictions)),
        leakage_rule=(
            "For each target, only manually verified observations with an earlier achievement "
            "timestamp are eligible as prediction sources."
        ),
    )
