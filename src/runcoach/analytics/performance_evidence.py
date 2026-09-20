"""Deterministic selection of representative athlete performance evidence."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite
from typing import Final
from uuid import UUID

from runcoach.analytics.performance import (
    DEFAULT_DISTANCE_TOLERANCE_PCT,
    StandardDistance,
    match_standard_distance,
)
from runcoach.analytics.session_classification import SessionKind

PERFORMANCE_EVIDENCE_VERSION: Final = "representative_performance_evidence_v3"
MAX_STRONG_TRAINING_PACE_SECONDS_PER_KM: Final = 270.0
MINIMUM_STRONG_TRAINING_DISTANCE_KM: Final = 3.0
MINIMUM_STRONG_TRAINING_DURATION_SECONDS: Final = 12 * 60.0
MAXIMUM_STOPPAGE_RATIO: Final = 1.10


class PerformanceEvidenceKind(StrEnum):
    """Why an activity is meaningful to the performance model."""

    VERIFIED_PERSONAL_BEST = "verified_personal_best"
    VERIFIED_HISTORY = "verified_history"
    OBSERVED_TRAINING_BEST = "observed_training_best"
    RACE_PERFORMANCE = "race_performance"
    STANDARD_DISTANCE_PERFORMANCE = "standard_distance_performance"
    STRONG_TRAINING = "strong_training"


@dataclass(frozen=True, slots=True)
class ActivityPerformanceCandidate:
    """Minimal canonical activity fields needed for evidence selection."""

    activity_id: UUID
    name: str | None
    achieved_on: date
    distance_km: float
    moving_time_seconds: float
    elapsed_time_seconds: float
    activity_type: str
    session_kind: SessionKind

    def __post_init__(self) -> None:
        values = (self.distance_km, self.moving_time_seconds, self.elapsed_time_seconds)
        if not all(isfinite(value) and value > 0 for value in values):
            raise ValueError("Performance candidate values must be finite and positive.")


@dataclass(frozen=True, slots=True)
class SelectedPerformanceEvidence:
    """One selected activity and the transparent reason it was retained."""

    activity_id: UUID
    activity_name: str | None
    achieved_on: date
    evidence_kind: PerformanceEvidenceKind
    target_distance: StandardDistance | None
    activity_distance_km: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float
    session_kind: SessionKind
    reason: str


def _standard_distance_evidence(
    candidate: ActivityPerformanceCandidate,
) -> tuple[StandardDistance, float] | None:
    match = match_standard_distance(
        candidate.distance_km * 1_000,
        tolerance_pct=DEFAULT_DISTANCE_TOLERANCE_PCT,
    )
    if match is None:
        return None
    normalized_seconds = candidate.elapsed_time_seconds * (
        match.official_distance_m / (candidate.distance_km * 1_000)
    )
    return match.distance, normalized_seconds


def _has_reliable_timing(candidate: ActivityPerformanceCandidate) -> bool:
    return (
        candidate.elapsed_time_seconds >= candidate.moving_time_seconds
        and candidate.elapsed_time_seconds <= candidate.moving_time_seconds * MAXIMUM_STOPPAGE_RATIO
    )


def _strong_training_candidate(candidate: ActivityPerformanceCandidate) -> bool:
    moving_pace = candidate.moving_time_seconds / candidate.distance_km
    return (
        _has_reliable_timing(candidate)
        and candidate.distance_km >= MINIMUM_STRONG_TRAINING_DISTANCE_KM
        and candidate.moving_time_seconds >= MINIMUM_STRONG_TRAINING_DURATION_SECONDS
        and moving_pace < MAX_STRONG_TRAINING_PACE_SECONDS_PER_KM
    )


def _distance_band(distance_km: float) -> StandardDistance:
    """Group supporting runs by the next standard distance they inform."""

    if distance_km < 5:
        return StandardDistance.FIVE_K
    if distance_km < 10:
        return StandardDistance.TEN_K
    if distance_km < 21.0975:
        return StandardDistance.HALF_MARATHON
    return StandardDistance.MARATHON


def select_activity_performance_evidence(
    candidates: tuple[ActivityPerformanceCandidate, ...],
    *,
    already_verified_activity_ids: frozenset[UUID] = frozenset(),
) -> tuple[SelectedPerformanceEvidence, ...]:
    """Select meaningful non-duplicate race and training evidence.

    All explicitly identified races and the two requested standard-distance
    benchmarks are retained. Other fast training is compacted to the fastest
    and most recent activity in each distance band, so short speed and longer
    endurance evidence remain distinct without taking an arbitrary recent-N sample.
    """

    selected: dict[UUID, SelectedPerformanceEvidence] = {}
    strong_by_band: dict[StandardDistance, list[ActivityPerformanceCandidate]] = {}

    for candidate in candidates:
        if candidate.activity_id in already_verified_activity_ids:
            continue
        standard = _standard_distance_evidence(candidate)
        is_race = candidate.activity_type == "race" or candidate.session_kind is SessionKind.RACE

        if is_race and _has_reliable_timing(candidate):
            target_distance = standard[0] if standard is not None else None
            selected[candidate.activity_id] = SelectedPerformanceEvidence(
                activity_id=candidate.activity_id,
                activity_name=candidate.name,
                achieved_on=candidate.achieved_on,
                evidence_kind=PerformanceEvidenceKind.RACE_PERFORMANCE,
                target_distance=target_distance,
                activity_distance_km=round(candidate.distance_km, 6),
                elapsed_time_seconds=round(candidate.elapsed_time_seconds, 3),
                pace_seconds_per_km=round(
                    candidate.elapsed_time_seconds / candidate.distance_km,
                    6,
                ),
                session_kind=candidate.session_kind,
                reason="Explicit race metadata or title identifies this as a race effort.",
            )
            continue

        if standard is not None and _has_reliable_timing(candidate):
            distance, normalized_seconds = standard
            qualifies = (distance is StandardDistance.TEN_K and normalized_seconds < 42 * 60) or (
                distance is StandardDistance.HALF_MARATHON and normalized_seconds < 105 * 60
            )
            if qualifies:
                threshold = "42:00" if distance is StandardDistance.TEN_K else "1:45:00"
                selected[candidate.activity_id] = SelectedPerformanceEvidence(
                    activity_id=candidate.activity_id,
                    activity_name=candidate.name,
                    achieved_on=candidate.achieved_on,
                    evidence_kind=PerformanceEvidenceKind.STANDARD_DISTANCE_PERFORMANCE,
                    target_distance=distance,
                    activity_distance_km=round(candidate.distance_km, 6),
                    elapsed_time_seconds=round(candidate.elapsed_time_seconds, 3),
                    pace_seconds_per_km=round(
                        candidate.elapsed_time_seconds / candidate.distance_km,
                        6,
                    ),
                    session_kind=candidate.session_kind,
                    reason=(
                        f"Whole activity is within 3% of {distance.value} and its "
                        f"distance-normalized elapsed time is faster than {threshold}."
                    ),
                )
                continue

        if _strong_training_candidate(candidate):
            strong_by_band.setdefault(_distance_band(candidate.distance_km), []).append(candidate)

    for distance, band_candidates in strong_by_band.items():
        fastest = min(
            band_candidates,
            key=lambda item: (
                item.moving_time_seconds / item.distance_km,
                -item.achieved_on.toordinal(),
                str(item.activity_id),
            ),
        )
        most_recent = max(
            band_candidates,
            key=lambda item: (
                item.achieved_on,
                -(item.moving_time_seconds / item.distance_km),
                str(item.activity_id),
            ),
        )
        for candidate, descriptor in ((fastest, "fastest"), (most_recent, "most recent")):
            if candidate.activity_id in selected:
                continue
            selected[candidate.activity_id] = SelectedPerformanceEvidence(
                activity_id=candidate.activity_id,
                activity_name=candidate.name,
                achieved_on=candidate.achieved_on,
                evidence_kind=PerformanceEvidenceKind.STRONG_TRAINING,
                target_distance=None,
                activity_distance_km=round(candidate.distance_km, 6),
                elapsed_time_seconds=round(candidate.elapsed_time_seconds, 3),
                pace_seconds_per_km=round(
                    candidate.moving_time_seconds / candidate.distance_km,
                    6,
                ),
                session_kind=candidate.session_kind,
                reason=(
                    f"Representative {descriptor} sub-4:30/km training activity in the "
                    f"{distance.value} evidence band, with at least 3 km, 12 minutes, "
                    "and no material stopped-time distortion."
                ),
            )

    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.achieved_on,
                item.evidence_kind,
                str(item.activity_id),
            ),
            reverse=True,
        )
    )
