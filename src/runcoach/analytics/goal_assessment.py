"""Experimental same-distance goal assessment from an athlete's own history."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Final, Literal

from runcoach.analytics.performance import StandardDistance

GOAL_ASSESSMENT_VERSION: Final = "same_distance_training_support_v1"
TRAINING_WINDOW_DAYS: Final = 42

type Confidence = Literal["low", "medium"]


@dataclass(frozen=True, slots=True)
class TrainingBlock:
    """A bounded summary of training completed before an assessment date."""

    end_date: date
    runs: int
    distance_km: float
    moving_hours: float
    longest_run_km: float | None
    form_index: float | None = None
    last_run_date: date | None = None

    def __post_init__(self) -> None:
        if self.runs < 0:
            raise ValueError("Training-block run count must be non-negative.")
        for value, label in (
            (self.distance_km, "distance"),
            (self.moving_hours, "moving time"),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"Training-block {label} must be finite and non-negative.")
        if self.longest_run_km is not None and (
            not isfinite(self.longest_run_km) or self.longest_run_km < 0
        ):
            raise ValueError("Training-block longest run must be finite and non-negative.")
        if self.form_index is not None and not isfinite(self.form_index):
            raise ValueError("Training-block form index must be finite when present.")


@dataclass(frozen=True, slots=True)
class TrainingSupport:
    """Current-to-reference training ratios used by the experimental rule."""

    run_frequency_ratio: float | None
    distance_ratio: float | None
    longest_run_ratio: float | None
    support_score: float | None


@dataclass(frozen=True, slots=True)
class AchievableTimeRange:
    """An intentionally bounded range rather than a single point forecast."""

    optimistic_seconds: float
    conservative_seconds: float
    optimistic_time: str
    conservative_time: str


@dataclass(frozen=True, slots=True)
class GoalAssessment:
    """Evidence-backed, explicitly experimental assessment for one distance."""

    distance: StandardDistance
    status: str
    confidence: Confidence
    reference_pb_seconds: float
    reference_pb_time: str
    reference_pb_date: date
    achievable_range: AchievableTimeRange
    current_42_day_block: TrainingBlock
    reference_42_day_block: TrainingBlock
    training_support: TrainingSupport
    recommended_focus: str
    algorithm_version: str
    limitations: tuple[str, ...]


_LONG_RUN_CAP_KM: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 15.0,
    StandardDistance.TEN_K: 24.0,
    StandardDistance.HALF_MARATHON: 32.0,
    StandardDistance.MARATHON: 42.195,
}

_SUPPORT_WEIGHTS: Final[dict[StandardDistance, tuple[float, float, float]]] = {
    StandardDistance.FIVE_K: (0.35, 0.50, 0.15),
    StandardDistance.TEN_K: (0.25, 0.45, 0.30),
    StandardDistance.HALF_MARATHON: (0.20, 0.35, 0.45),
    StandardDistance.MARATHON: (0.15, 0.30, 0.55),
}

_DISTANCE_FOCUS: Final[dict[StandardDistance, str]] = {
    StandardDistance.FIVE_K: "Maintain volume and add controlled 5K speed-endurance work.",
    StandardDistance.TEN_K: "Maintain volume and develop threshold durability.",
    StandardDistance.HALF_MARATHON: "Maintain volume and develop sustained threshold endurance.",
    StandardDistance.MARATHON: "Maintain volume and build marathon-specific long-run durability.",
}


def format_duration(total_seconds: float) -> str:
    """Format rounded seconds as M:SS or H:MM:SS for presentation."""

    if not isfinite(total_seconds) or total_seconds <= 0:
        raise ValueError("Duration must be finite and positive.")
    rounded = round(total_seconds)
    hours, remainder = divmod(rounded, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _ratio(current: float, reference: float) -> float | None:
    if reference <= 0:
        return None
    return round(current / reference, 6)


def _support_score(
    *,
    distance: StandardDistance,
    run_ratio: float | None,
    distance_ratio: float | None,
    longest_ratio: float | None,
) -> float | None:
    weights = _SUPPORT_WEIGHTS[distance]
    weighted_values = tuple(
        (min(max(ratio, 0.5), 1.5), weight)
        for ratio, weight in zip((run_ratio, distance_ratio, longest_ratio), weights, strict=True)
        if ratio is not None
    )
    if not weighted_values:
        return None
    weight_total = sum(weight for _, weight in weighted_values)
    return round(sum(value * weight for value, weight in weighted_values) / weight_total, 6)


def _range_factors(support_score: float | None) -> tuple[float, float]:
    if support_score is None:
        return (1.02, 1.08)
    if support_score >= 1.10:
        return (0.98, 1.02)
    if support_score >= 0.90:
        return (0.99, 1.03)
    if support_score >= 0.75:
        return (1.00, 1.05)
    return (1.02, 1.08)


def _recommended_focus(
    *,
    distance: StandardDistance,
    run_ratio: float | None,
    distance_ratio: float | None,
    longest_ratio: float | None,
) -> str:
    available: dict[str, float] = {}
    for name, value in (
        ("frequency", run_ratio),
        ("volume", distance_ratio),
        ("long_run", longest_ratio),
    ):
        if value is not None:
            available[name] = value
    if not available:
        return "Build a consistent aerobic training history before selecting a race target."

    weakest, weakest_ratio = min(available.items(), key=lambda item: item[1])
    if weakest_ratio >= 1.0:
        return _DISTANCE_FOCUS[distance]
    if weakest == "frequency":
        return "Rebuild consistent weekly running frequency before adding more intensity."
    if weakest == "volume":
        return "Rebuild sustainable aerobic volume before adding more race-specific intensity."
    return "Progress the long run gradually to restore distance-specific durability."


def assess_goal(
    *,
    distance: StandardDistance,
    reference_pb_seconds: float,
    reference_pb_date: date,
    current_block: TrainingBlock,
    reference_block: TrainingBlock,
) -> GoalAssessment:
    """Compare current training with the build-up before the athlete's same-distance PB."""

    if not isfinite(reference_pb_seconds) or reference_pb_seconds <= 0:
        raise ValueError("Reference PB time must be finite and positive.")

    run_ratio = _ratio(float(current_block.runs), float(reference_block.runs))
    distance_ratio = _ratio(current_block.distance_km, reference_block.distance_km)
    long_run_cap = _LONG_RUN_CAP_KM[distance]
    current_longest = min(current_block.longest_run_km or 0.0, long_run_cap)
    reference_longest = min(reference_block.longest_run_km or 0.0, long_run_cap)
    longest_ratio = _ratio(current_longest, reference_longest)
    support_score = _support_score(
        distance=distance,
        run_ratio=run_ratio,
        distance_ratio=distance_ratio,
        longest_ratio=longest_ratio,
    )

    optimistic_factor, conservative_factor = _range_factors(support_score)
    freshness_penalty = 0.0
    if current_block.last_run_date is None:
        freshness_penalty = 0.02
    else:
        days_since_last_run = (current_block.end_date - current_block.last_run_date).days
        if days_since_last_run > 14:
            freshness_penalty = 0.02

    fatigue_penalty = 0.01 if (current_block.form_index or 0.0) < -15 else 0.0
    optimistic_seconds = round(
        reference_pb_seconds * (optimistic_factor + freshness_penalty + fatigue_penalty),
        3,
    )
    conservative_seconds = round(
        reference_pb_seconds * (conservative_factor + freshness_penalty + fatigue_penalty),
        3,
    )

    confidence: Confidence = "medium"
    if (
        current_block.runs < 6
        or reference_block.runs < 6
        or support_score is None
        or freshness_penalty > 0
    ):
        confidence = "low"

    return GoalAssessment(
        distance=distance,
        status="experimental_not_validated",
        confidence=confidence,
        reference_pb_seconds=reference_pb_seconds,
        reference_pb_time=format_duration(reference_pb_seconds),
        reference_pb_date=reference_pb_date,
        achievable_range=AchievableTimeRange(
            optimistic_seconds=optimistic_seconds,
            conservative_seconds=conservative_seconds,
            optimistic_time=format_duration(optimistic_seconds),
            conservative_time=format_duration(conservative_seconds),
        ),
        current_42_day_block=current_block,
        reference_42_day_block=reference_block,
        training_support=TrainingSupport(
            run_frequency_ratio=run_ratio,
            distance_ratio=distance_ratio,
            longest_run_ratio=longest_ratio,
            support_score=support_score,
        ),
        recommended_focus=_recommended_focus(
            distance=distance,
            run_ratio=run_ratio,
            distance_ratio=distance_ratio,
            longest_ratio=longest_ratio,
        ),
        algorithm_version=GOAL_ASSESSMENT_VERSION,
        limitations=(
            "This range is an experimental decision-support heuristic, not a validated model.",
            "It compares 42-day training support with the build-up before the athlete's own PB.",
            "It does not yet account for course, weather, illness, sleep, taper, "
            "or race execution.",
        ),
    )
