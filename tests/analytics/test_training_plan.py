"""Tests for deterministic goal-based training-plan previews."""

from dataclasses import replace
from datetime import date

import pytest

from runcoach.analytics.current_fitness import (
    CurrentFitnessAssessment,
    CurrentFitnessEstimate,
    FitnessMark,
    TrainingProfile,
)
from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
    TRAINING_PLAN_VERSION,
    GoalStatus,
    PlannedSessionKind,
    PlanPhase,
    TrainingGoal,
    build_training_plan_preview,
)


def _fitness() -> CurrentFitnessAssessment:
    marks = (
        (StandardDistance.FIVE_K, 1_082.88, 1_082.88, 216.576, 1.0, "high", 1_128.0),
        (StandardDistance.TEN_K, 2_249.98, 2_249.98, 224.998, 1.0, "medium", 2_464.0),
        (
            StandardDistance.HALF_MARATHON,
            5_123.019,
            5_123.019,
            242.826,
            1.0,
            "medium",
            5_606.0,
        ),
        (
            StandardDistance.MARATHON,
            11_388.665,
            11_461.396,
            271.629,
            0.92,
            "medium",
            13_266.0,
        ),
    )
    estimates = tuple(
        CurrentFitnessEstimate(
            distance=distance,
            fitness_potential_time_seconds=potential,
            race_readiness_time_seconds=readiness,
            optimistic_time_seconds=readiness * 0.96,
            conservative_time_seconds=readiness * 1.04,
            fitness_potential_pace_seconds_per_km=pace,
            race_readiness_pace_seconds_per_km=pace,
            preparation_score=preparation,
            confidence=confidence,  # type: ignore[arg-type]
            current_pb_seconds=personal_best,
            improvement_from_pb_seconds=personal_best - readiness,
            basis="Synthetic evidence.",
        )
        for distance, potential, readiness, pace, preparation, confidence, personal_best in marks
    )
    anchor = FitnessMark(StandardDistance.FIVE_K, 1_128.0, date(2026, 9, 1))
    return CurrentFitnessAssessment(
        algorithm_version="training_context_fitness_v2",
        status="experimental_not_validated",
        as_of_date=date(2026, 9, 4),
        anchor=anchor,
        prior_anchor=None,
        anchor_capacity_factor=0.96,
        anchor_improvement_factor=0.916918,
        training=TrainingProfile(
            as_of_date=date(2026, 9, 4),
            runs_28d=25,
            distance_28d_km=311.89,
            runs_84d=65,
            distance_84d_km=748.45,
            longest_run_84d_km=28.02,
            classified_sessions_84d=4,
            quality_sessions_84d=3,
            runs_168d=103,
            distance_168d_km=1_136.69,
            runs_365d=136,
            distance_365d_km=1_468.76,
        ),
        estimates=estimates,
        limitations=("Synthetic limitation.",),
    )


def test_marathon_preview_builds_progressive_outline_and_first_week() -> None:
    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2026, 11, 29),
            target_time_seconds=11_400.0,
            days_per_week=6,
        ),
        fitness=_fitness(),
    )

    assert preview.algorithm_version == TRAINING_PLAN_VERSION
    assert preview.status == "preview_not_persisted"
    assert preview.plan_start_date == date(2026, 8, 31)
    assert preview.weeks_to_race == 13
    assert preview.goal_status is GoalStatus.ACHIEVABLE
    assert preview.fitness_potential_seconds == pytest.approx(11_388.665)
    assert preview.current_readiness_seconds == pytest.approx(11_461.396)
    assert preview.current_preparation_score == pytest.approx(0.92)
    assert preview.recent_weekly_distance_km == pytest.approx(77.972)
    assert len(preview.weekly_outline) == 13
    assert preview.weekly_outline[0].phase is PlanPhase.BASE
    assert preview.weekly_outline[-1].phase is PlanPhase.RACE
    assert preview.weekly_outline[3].target_distance_km < (
        preview.weekly_outline[2].target_distance_km
    )
    assert len(preview.first_week) == 6
    assert {session.kind for session in preview.first_week} >= {
        PlannedSessionKind.QUALITY,
        PlannedSessionKind.LONG,
        PlannedSessionKind.RECOVERY,
    }
    assert sum(session.distance_km for session in preview.first_week) == pytest.approx(
        preview.weekly_outline[0].target_distance_km,
        abs=0.2,
    )


def test_midweek_plan_includes_the_current_monday_week() -> None:
    base_fitness = _fitness()
    fitness = replace(
        base_fitness,
        as_of_date=date(2026, 9, 8),
        training=replace(base_fitness.training, as_of_date=date(2026, 9, 8)),
    )

    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=6,
        ),
        fitness=fitness,
    )

    assert preview.plan_start_date == date(2026, 9, 7)
    assert preview.weekly_outline[0].start_date == date(2026, 9, 7)
    assert min(session.scheduled_date for session in preview.first_week) >= date(2026, 9, 7)
    assert max(session.scheduled_date for session in preview.first_week) <= date(2026, 9, 13)


def test_refresh_preserves_the_original_plan_calendar() -> None:
    base_fitness = _fitness()
    fitness = replace(
        base_fitness,
        as_of_date=date(2026, 9, 15),
        training=replace(base_fitness.training, as_of_date=date(2026, 9, 15)),
    )

    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=6,
        ),
        fitness=fitness,
        plan_start_date=date(2026, 9, 7),
    )

    assert preview.plan_start_date == date(2026, 9, 7)
    assert preview.weekly_outline[0].start_date == date(2026, 9, 7)


def test_january_2027_marathon_plan_builds_specific_endurance_safely() -> None:
    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=6,
        ),
        fitness=_fitness(),
    )

    assert preview.weeks_to_race == 22
    assert preview.goal.race_date == date(2027, 1, 31)
    assert {week.phase for week in preview.weekly_outline} == set(PlanPhase)
    assert 30 <= max(week.long_run_km for week in preview.weekly_outline) <= 35
    maximum_safe_volume = preview.recent_weekly_distance_km * 1.15
    assert max(week.target_distance_km for week in preview.weekly_outline) <= (
        maximum_safe_volume + 0.2
    )


def test_marathon_plan_builds_beyond_low_recent_volume_without_tiny_sessions() -> None:
    fitness = _fitness()
    fitness = replace(
        fitness,
        training=replace(
            fitness.training,
            runs_28d=24,
            distance_28d_km=160.0,
            runs_84d=60,
            distance_84d_km=480.0,
            longest_run_84d_km=24.0,
        ),
    )

    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=6,
        ),
        fitness=fitness,
    )

    assert preview.recent_weekly_distance_km == 40
    assert max(week.target_distance_km for week in preview.weekly_outline) == 60
    assert min(session.distance_km for session in preview.first_week) >= 5
    assert sum(session.distance_km for session in preview.first_week) == pytest.approx(
        preview.weekly_outline[0].target_distance_km,
        abs=0.2,
    )
    quality = next(
        session for session in preview.first_week if session.kind is PlannedSessionKind.QUALITY
    )
    assert "strides" in quality.title


def test_low_volume_base_week_uses_fewer_days_instead_of_filler_runs() -> None:
    fitness = _fitness()
    fitness = replace(
        fitness,
        training=replace(
            fitness.training,
            runs_28d=16,
            distance_28d_km=120.0,
            runs_84d=42,
            distance_84d_km=330.0,
            longest_run_84d_km=20.0,
        ),
    )

    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=6,
        ),
        fitness=fitness,
    )

    assert len(preview.first_week) < 6
    assert min(session.distance_km for session in preview.first_week) >= 5
    assert sum(session.distance_km for session in preview.first_week) == pytest.approx(
        preview.weekly_outline[0].target_distance_km,
        abs=0.2,
    )


@pytest.mark.parametrize(
    ("target_seconds", "race_date", "expected"),
    (
        (None, date(2026, 11, 29), GoalStatus.FITNESS_BASED),
        (11_400.0, date(2026, 11, 29), GoalStatus.ACHIEVABLE),
        (11_200.0, date(2026, 11, 29), GoalStatus.CHALLENGING),
        (10_800.0, date(2026, 11, 29), GoalStatus.AGGRESSIVE),
        (11_200.0, date(2026, 10, 18), GoalStatus.AGGRESSIVE),
    ),
)
def test_goal_status_distinguishes_ambition_and_time_available(
    target_seconds: float | None,
    race_date: date,
    expected: GoalStatus,
) -> None:
    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.MARATHON,
            race_date=race_date,
            target_time_seconds=target_seconds,
            days_per_week=5,
        ),
        fitness=_fitness(),
    )

    assert preview.goal_status is expected


def test_session_paces_and_distances_are_target_specific() -> None:
    preview = build_training_plan_preview(
        goal=TrainingGoal(
            distance=StandardDistance.FIVE_K,
            race_date=date(2026, 11, 1),
            target_time_seconds=1_080.0,
            days_per_week=4,
        ),
        fitness=_fitness(),
    )

    quality = next(
        session for session in preview.first_week if session.kind is PlannedSessionKind.QUALITY
    )
    long_run = next(
        session for session in preview.first_week if session.kind is PlannedSessionKind.LONG
    )
    assert quality.title.startswith("6 x 800 m")
    assert quality.pace is not None
    assert quality.pace.faster_seconds_per_km == pytest.approx(213.576)
    assert long_run.distance_km <= 18


@pytest.mark.parametrize(
    ("race_date", "message"),
    (
        (date(2026, 9, 12), "at least two"),
        (date(2027, 9, 30), "within 52 weeks"),
    ),
)
def test_invalid_race_horizon_is_rejected(race_date: date, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_training_plan_preview(
            goal=TrainingGoal(
                distance=StandardDistance.TEN_K,
                race_date=race_date,
                target_time_seconds=None,
                days_per_week=4,
            ),
            fitness=_fitness(),
        )


def test_invalid_goal_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="Target time"):
        TrainingGoal(
            StandardDistance.FIVE_K,
            date(2026, 12, 1),
            0,
            4,
        )
    with pytest.raises(ValueError, match="between three and seven"):
        TrainingGoal(
            StandardDistance.FIVE_K,
            date(2026, 12, 1),
            None,
            2,
        )
