"""Deterministic goal assessment and progressive training-plan previews."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from math import ceil, isfinite
from typing import Final

from runcoach.analytics.current_fitness import (
    CurrentFitnessAssessment,
    CurrentFitnessEstimate,
)
from runcoach.analytics.performance import StandardDistance, standard_distance_meters

TRAINING_PLAN_VERSION: Final = "goal_plan_preview_v1"
MINIMUM_PLAN_DAYS: Final = 14
MAXIMUM_PLAN_DAYS: Final = 364


class GoalStatus(StrEnum):
    """Relationship between a requested target and current evidence."""

    FITNESS_BASED = "fitness_based"
    ACHIEVABLE = "achievable"
    CHALLENGING = "challenging"
    AGGRESSIVE = "aggressive"


class PlanPhase(StrEnum):
    """High-level purpose of one planned week."""

    BASE = "base"
    BUILD = "build"
    SPECIFIC = "specific"
    TAPER = "taper"
    RACE = "race"


class PlannedSessionKind(StrEnum):
    """Supported session roles in a generated week."""

    EASY = "easy"
    RECOVERY = "recovery"
    QUALITY = "quality"
    LONG = "long"
    RACE = "race"


@dataclass(frozen=True, slots=True)
class TrainingGoal:
    """User-selected race target used to generate a preview."""

    distance: StandardDistance
    race_date: date
    target_time_seconds: float | None
    days_per_week: int

    def __post_init__(self) -> None:
        if self.target_time_seconds is not None and (
            not isfinite(self.target_time_seconds) or self.target_time_seconds <= 0
        ):
            raise ValueError("Target time must be finite and positive when provided.")
        if not 3 <= self.days_per_week <= 7:
            raise ValueError("Training days per week must be between three and seven.")


@dataclass(frozen=True, slots=True)
class PaceRange:
    """Inclusive pace guidance in seconds per kilometre."""

    faster_seconds_per_km: float
    slower_seconds_per_km: float


@dataclass(frozen=True, slots=True)
class PlannedSession:
    """One concrete session in the first generated week."""

    scheduled_date: date
    kind: PlannedSessionKind
    title: str
    distance_km: float
    pace: PaceRange | None
    purpose: str


@dataclass(frozen=True, slots=True)
class PlannedWeek:
    """One progressive weekly outline between now and race day."""

    week_number: int
    start_date: date
    end_date: date
    phase: PlanPhase
    target_distance_km: float
    long_run_km: float
    quality_focus: str


@dataclass(frozen=True, slots=True)
class TrainingPlanPreview:
    """Auditable training plan derived from current fitness and recent training."""

    algorithm_version: str
    status: str
    as_of_date: date
    plan_start_date: date
    goal: TrainingGoal
    goal_status: GoalStatus
    weeks_to_race: int
    fitness_potential_seconds: float
    current_readiness_seconds: float
    recommended_target_seconds: float
    target_gap_seconds: float | None
    current_preparation_score: float
    recent_weekly_distance_km: float
    first_week: tuple[PlannedSession, ...]
    weekly_outline: tuple[PlannedWeek, ...]
    rationale: tuple[str, ...]
    guardrails: tuple[str, ...]


_LONG_RUN_SHARE: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 0.22,
    StandardDistance.TEN_K: 0.24,
    StandardDistance.HALF_MARATHON: 0.28,
    StandardDistance.MARATHON: 0.32,
}

_LONG_RUN_CAP_KM: Final[dict[StandardDistance, float]] = {
    StandardDistance.FIVE_K: 18.0,
    StandardDistance.TEN_K: 22.0,
    StandardDistance.HALF_MARATHON: 30.0,
    StandardDistance.MARATHON: 35.0,
}

_QUALITY_FOCUS: Final[dict[StandardDistance, str]] = {
    StandardDistance.FIVE_K: "5K speed endurance",
    StandardDistance.TEN_K: "10K pace and threshold durability",
    StandardDistance.HALF_MARATHON: "threshold and half-marathon pace",
    StandardDistance.MARATHON: "marathon pace and fueling durability",
}


def _next_monday(as_of_date: date) -> date:
    days_ahead = (7 - as_of_date.weekday()) % 7
    return as_of_date + timedelta(days=days_ahead or 7)


def _estimate_for(
    fitness: CurrentFitnessAssessment,
    distance: StandardDistance,
) -> CurrentFitnessEstimate:
    estimate = next(
        (candidate for candidate in fitness.estimates if candidate.distance is distance),
        None,
    )
    if estimate is None:
        raise ValueError(f"Current fitness does not include {distance.value}.")
    return estimate


def _goal_status(
    *,
    target_seconds: float | None,
    estimate: CurrentFitnessEstimate,
    weeks_to_race: int,
) -> GoalStatus:
    if target_seconds is None:
        return GoalStatus.FITNESS_BASED
    if target_seconds >= estimate.race_readiness_time_seconds * 0.99:
        return GoalStatus.ACHIEVABLE
    if target_seconds >= estimate.fitness_potential_time_seconds * 0.98 and weeks_to_race >= 8:
        return GoalStatus.CHALLENGING
    return GoalStatus.AGGRESSIVE


def _phase(week_number: int, total_weeks: int) -> PlanPhase:
    weeks_remaining = total_weeks - week_number
    if week_number == total_weeks:
        return PlanPhase.RACE
    if weeks_remaining <= 2:
        return PlanPhase.TAPER
    if weeks_remaining <= max(5, total_weeks // 3):
        return PlanPhase.SPECIFIC
    if week_number <= max(2, total_weeks // 4):
        return PlanPhase.BASE
    return PlanPhase.BUILD


def _weekly_distance(
    *,
    week_number: int,
    total_weeks: int,
    recent_weekly_km: float,
    phase: PlanPhase,
    race_distance: StandardDistance,
) -> float:
    if phase is PlanPhase.RACE:
        race_distance_km = standard_distance_meters(race_distance) / 1_000
        return round(max(recent_weekly_km * 0.45, race_distance_km + 6), 1)
    if phase is PlanPhase.TAPER:
        weeks_remaining = total_weeks - week_number
        return round(recent_weekly_km * (0.62 if weeks_remaining == 1 else 0.78), 1)

    build_step = (week_number - 1) - ((week_number - 1) // 4)
    distance_km = recent_weekly_km * 0.92 * (1.035**build_step)
    if week_number % 4 == 0:
        distance_km *= 0.82
    return round(min(distance_km, recent_weekly_km * 1.15), 1)


def _long_run_distance(
    *,
    target_distance_km: float,
    race_distance: StandardDistance,
    phase: PlanPhase,
) -> float:
    share = _LONG_RUN_SHARE[race_distance]
    if race_distance is StandardDistance.MARATHON:
        share = {
            PlanPhase.BASE: 0.32,
            PlanPhase.BUILD: 0.35,
            PlanPhase.SPECIFIC: 0.38,
            PlanPhase.TAPER: 0.32,
            PlanPhase.RACE: 0.0,
        }[phase]
    distance_km = min(target_distance_km * share, _LONG_RUN_CAP_KM[race_distance])
    if phase is PlanPhase.TAPER:
        distance_km *= 0.75
    return round(distance_km, 1)


def _weekly_outline(
    *,
    goal: TrainingGoal,
    plan_start_date: date,
    total_weeks: int,
    recent_weekly_km: float,
) -> tuple[PlannedWeek, ...]:
    weeks: list[PlannedWeek] = []
    for week_number in range(1, total_weeks + 1):
        start_date = plan_start_date + timedelta(days=(week_number - 1) * 7)
        end_date = min(start_date + timedelta(days=6), goal.race_date)
        phase = _phase(week_number, total_weeks)
        target_distance_km = _weekly_distance(
            week_number=week_number,
            total_weeks=total_weeks,
            recent_weekly_km=recent_weekly_km,
            phase=phase,
            race_distance=goal.distance,
        )
        if phase is PlanPhase.RACE:
            long_run_km = 0.0
            quality_focus = "Race execution and recovery"
        else:
            long_run_km = _long_run_distance(
                target_distance_km=target_distance_km,
                race_distance=goal.distance,
                phase=phase,
            )
            quality_focus = _QUALITY_FOCUS[goal.distance]
            if phase is PlanPhase.TAPER:
                quality_focus = "Reduced-volume race-pace sharpening"
        weeks.append(
            PlannedWeek(
                week_number=week_number,
                start_date=start_date,
                end_date=end_date,
                phase=phase,
                target_distance_km=target_distance_km,
                long_run_km=long_run_km,
                quality_focus=quality_focus,
            )
        )
    return tuple(weeks)


def _pace_range(faster: float, slower: float) -> PaceRange:
    return PaceRange(
        faster_seconds_per_km=round(faster, 3),
        slower_seconds_per_km=round(slower, 3),
    )


def _session_paces(
    fitness: CurrentFitnessAssessment,
    target_estimate: CurrentFitnessEstimate,
    target_distance: StandardDistance,
) -> dict[PlannedSessionKind, PaceRange]:
    five_k = _estimate_for(fitness, StandardDistance.FIVE_K)
    five_k_pace = five_k.fitness_potential_pace_seconds_per_km
    target_pace = target_estimate.race_readiness_pace_seconds_per_km
    quality_pace = {
        StandardDistance.FIVE_K: _pace_range(five_k_pace - 3, five_k_pace + 5),
        StandardDistance.TEN_K: _pace_range(target_pace - 5, target_pace + 5),
        StandardDistance.HALF_MARATHON: _pace_range(target_pace - 8, target_pace + 4),
        StandardDistance.MARATHON: _pace_range(target_pace - 5, target_pace + 5),
    }[target_distance]
    return {
        PlannedSessionKind.EASY: _pace_range(five_k_pace + 90, five_k_pace + 130),
        PlannedSessionKind.RECOVERY: _pace_range(five_k_pace + 115, five_k_pace + 150),
        PlannedSessionKind.LONG: _pace_range(five_k_pace + 75, five_k_pace + 115),
        PlannedSessionKind.QUALITY: quality_pace,
        PlannedSessionKind.RACE: _pace_range(target_pace, target_pace),
    }


def _quality_title(distance: StandardDistance) -> str:
    return {
        StandardDistance.FIVE_K: "6 x 800 m at controlled 5K effort",
        StandardDistance.TEN_K: "4 x 2 km at controlled 10K effort",
        StandardDistance.HALF_MARATHON: "3 x 3 km at threshold to half-marathon effort",
        StandardDistance.MARATHON: "3 x 4 km at controlled marathon effort",
    }[distance]


def _first_week(
    *,
    goal: TrainingGoal,
    week: PlannedWeek,
    fitness: CurrentFitnessAssessment,
    target_estimate: CurrentFitnessEstimate,
) -> tuple[PlannedSession, ...]:
    day_slots = {
        3: (1, 3, 6),
        4: (1, 3, 5, 6),
        5: (0, 1, 3, 5, 6),
        6: (0, 1, 2, 3, 5, 6),
        7: (0, 1, 2, 3, 4, 5, 6),
    }[goal.days_per_week]
    long_day = day_slots[-1]
    quality_day = day_slots[1] if len(day_slots) >= 4 else day_slots[0]
    recovery_day = day_slots[-2] if len(day_slots) >= 4 else None
    long_distance = week.long_run_km
    minimum_quality_distance = {
        StandardDistance.FIVE_K: 9.0,
        StandardDistance.TEN_K: 12.0,
        StandardDistance.HALF_MARATHON: 15.0,
        StandardDistance.MARATHON: 18.0,
    }[goal.distance]
    quality_distance = round(
        max(minimum_quality_distance, week.target_distance_km * 0.16),
        1,
    )
    remaining_distance = max(week.target_distance_km - long_distance - quality_distance, 0.0)
    easy_count = goal.days_per_week - 2
    easy_distance = round(remaining_distance / easy_count, 1) if easy_count else 0.0
    paces = _session_paces(fitness, target_estimate, goal.distance)

    sessions: list[PlannedSession] = []
    for day_offset in day_slots:
        scheduled_date = week.start_date + timedelta(days=day_offset)
        if day_offset == long_day:
            sessions.append(
                PlannedSession(
                    scheduled_date=scheduled_date,
                    kind=PlannedSessionKind.LONG,
                    title="Long aerobic run",
                    distance_km=long_distance,
                    pace=paces[PlannedSessionKind.LONG],
                    purpose="Build distance-specific aerobic durability without racing training.",
                )
            )
        elif day_offset == quality_day:
            sessions.append(
                PlannedSession(
                    scheduled_date=scheduled_date,
                    kind=PlannedSessionKind.QUALITY,
                    title=_quality_title(goal.distance),
                    distance_km=quality_distance,
                    pace=paces[PlannedSessionKind.QUALITY],
                    purpose=(
                        f"Develop {_QUALITY_FOCUS[goal.distance]}; distance includes warm-up "
                        "and cool-down."
                    ),
                )
            )
        elif recovery_day is not None and day_offset == recovery_day:
            sessions.append(
                PlannedSession(
                    scheduled_date=scheduled_date,
                    kind=PlannedSessionKind.RECOVERY,
                    title="Recovery run",
                    distance_km=easy_distance,
                    pace=paces[PlannedSessionKind.RECOVERY],
                    purpose="Add low-cost aerobic volume before the long run.",
                )
            )
        else:
            sessions.append(
                PlannedSession(
                    scheduled_date=scheduled_date,
                    kind=PlannedSessionKind.EASY,
                    title="Easy aerobic run",
                    distance_km=easy_distance,
                    pace=paces[PlannedSessionKind.EASY],
                    purpose="Maintain aerobic frequency while absorbing harder sessions.",
                )
            )
    return tuple(sessions)


def build_training_plan_preview(
    *,
    goal: TrainingGoal,
    fitness: CurrentFitnessAssessment,
) -> TrainingPlanPreview:
    """Build a progressive plan preview from current fitness and training evidence."""

    plan_start_date = _next_monday(fitness.as_of_date)
    plan_days = (goal.race_date - plan_start_date).days + 1
    if plan_days < MINIMUM_PLAN_DAYS:
        raise ValueError("Race date must allow at least two training weeks.")
    if plan_days > MAXIMUM_PLAN_DAYS:
        raise ValueError("Race date must be within 52 weeks of the plan start.")

    weeks_to_race = ceil(plan_days / 7)
    estimate = _estimate_for(fitness, goal.distance)
    recent_weekly_km = round(fitness.training.distance_28d_km / 4, 3)
    if recent_weekly_km <= 0:
        raise ValueError("Recent training volume is required to generate a plan.")

    recent_weekly_runs = max(fitness.training.runs_28d / 4, 1.0)
    planning_weekly_km = recent_weekly_km * min(
        goal.days_per_week / recent_weekly_runs,
        1.0,
    )
    outline = _weekly_outline(
        goal=goal,
        plan_start_date=plan_start_date,
        total_weeks=weeks_to_race,
        recent_weekly_km=planning_weekly_km,
    )
    first_week = _first_week(
        goal=goal,
        week=outline[0],
        fitness=fitness,
        target_estimate=estimate,
    )
    goal_status = _goal_status(
        target_seconds=goal.target_time_seconds,
        estimate=estimate,
        weeks_to_race=weeks_to_race,
    )
    recommended_target = estimate.race_readiness_time_seconds
    target_gap = (
        round(goal.target_time_seconds - recommended_target, 3)
        if goal.target_time_seconds is not None
        else None
    )

    return TrainingPlanPreview(
        algorithm_version=TRAINING_PLAN_VERSION,
        status="preview_not_persisted",
        as_of_date=fitness.as_of_date,
        plan_start_date=plan_start_date,
        goal=goal,
        goal_status=goal_status,
        weeks_to_race=weeks_to_race,
        fitness_potential_seconds=estimate.fitness_potential_time_seconds,
        current_readiness_seconds=estimate.race_readiness_time_seconds,
        recommended_target_seconds=recommended_target,
        target_gap_seconds=target_gap,
        current_preparation_score=estimate.preparation_score,
        recent_weekly_distance_km=recent_weekly_km,
        first_week=first_week,
        weekly_outline=outline,
        rationale=(
            "The target is assessed against the current training-context fitness estimate.",
            "Initial volume starts below the trailing 28-day weekly average.",
            "Build weeks increase gradually, every fourth week reduces load, and race week tapers.",
            "Session paces are derived from current 5K capacity and target-distance readiness.",
        ),
        guardrails=(
            "Keep easy and recovery days conversational; do not turn them into time trials.",
            "Stop or modify a session for pain, illness, or unusual fatigue.",
            "Do not add missed hard sessions later in the week.",
            "This preview is training guidance, not medical advice or a guaranteed result.",
        ),
    )
