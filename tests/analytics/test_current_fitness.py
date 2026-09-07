"""Tests for training-context current-fitness estimates."""

from datetime import date

import pytest

from runcoach.analytics.current_fitness import (
    CURRENT_FITNESS_ALGORITHM_VERSION,
    FitnessMark,
    TrainingProfile,
    estimate_current_fitness,
)
from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.analytics.session_classification import SessionKind


def _training(
    *,
    distance_84d_km: float = 650.0,
    longest_run_84d_km: float = 28.0,
) -> TrainingProfile:
    return TrainingProfile(
        as_of_date=date(2026, 9, 4),
        runs_28d=24,
        distance_28d_km=280.0,
        runs_84d=68,
        distance_84d_km=distance_84d_km,
        longest_run_84d_km=longest_run_84d_km,
        classified_sessions_84d=8,
        quality_sessions_84d=5,
        runs_168d=105,
        distance_168d_km=1_050.0,
        runs_365d=132,
        distance_365d_km=1_422.0,
    )


def _marks() -> tuple[FitnessMark, ...]:
    return (
        FitnessMark(
            StandardDistance.FIVE_K,
            1_128.0,
            date(2026, 9, 1),
            verification_status=PerformanceLabel.VERIFIED_MAX_EFFORT,
            effort_type=PerformanceEffortType.PROVIDER_BEST_EFFORT,
            activity_distance_km=11.0,
            session_kind=SessionKind.TEMPO,
        ),
        FitnessMark(StandardDistance.TEN_K, 2_464.0, date(2026, 3, 29)),
        FitnessMark(StandardDistance.HALF_MARATHON, 5_606.0, date(2026, 6, 28)),
        FitnessMark(StandardDistance.MARATHON, 13_266.0, date(2026, 4, 12)),
    )


def _references() -> dict[StandardDistance, TrainingProfile]:
    return {
        StandardDistance.FIVE_K: _training(),
        StandardDistance.TEN_K: _training(distance_84d_km=190.0),
        StandardDistance.HALF_MARATHON: _training(
            distance_84d_km=411.0,
            longest_run_84d_km=42.9,
        ),
        StandardDistance.MARATHON: _training(
            distance_84d_km=196.0,
            longest_run_84d_km=21.2,
        ),
    }


def test_embedded_quality_effort_exposes_potential_and_readiness() -> None:
    marks = _marks()
    assessment = estimate_current_fitness(
        current_marks=marks,
        anchor=marks[0],
        prior_anchor=FitnessMark(
            StandardDistance.FIVE_K,
            1_181.0,
            date(2026, 5, 15),
        ),
        training=_training(),
        reference_training_by_distance=_references(),
    )

    estimates = {estimate.distance: estimate for estimate in assessment.estimates}
    assert assessment.algorithm_version == CURRENT_FITNESS_ALGORITHM_VERSION
    assert assessment.status == "experimental_not_validated"
    assert assessment.anchor_capacity_factor == 0.96
    assert assessment.anchor_improvement_factor == pytest.approx(1_128 * 0.96 / 1_181)
    assert estimates[StandardDistance.FIVE_K].fitness_potential_time_seconds == 1_082.88
    assert estimates[StandardDistance.FIVE_K].race_readiness_time_seconds == 1_082.88
    assert estimates[StandardDistance.FIVE_K].confidence == "high"
    assert estimates[StandardDistance.TEN_K].fitness_potential_time_seconds < 2_464.0
    assert estimates[StandardDistance.MARATHON].fitness_potential_time_seconds < 12_000.0
    assert all(
        estimate.fitness_potential_time_seconds
        <= estimate.race_readiness_time_seconds
        <= estimate.current_pb_seconds
        for estimate in assessment.estimates
        if estimate.current_pb_seconds is not None
    )
    assert all(
        estimate.optimistic_time_seconds
        < estimate.race_readiness_time_seconds
        < estimate.conservative_time_seconds
        for estimate in assessment.estimates
    )


def test_marathon_readiness_responds_to_volume_and_long_run_support() -> None:
    marks = _marks()
    prior_anchor = FitnessMark(StandardDistance.FIVE_K, 1_181.0, date(2026, 5, 15))
    strong = estimate_current_fitness(
        current_marks=marks,
        anchor=marks[0],
        prior_anchor=prior_anchor,
        training=_training(distance_84d_km=750.0, longest_run_84d_km=32.0),
        reference_training_by_distance=_references(),
    )
    weak = estimate_current_fitness(
        current_marks=marks,
        anchor=marks[0],
        prior_anchor=prior_anchor,
        training=_training(distance_84d_km=300.0, longest_run_84d_km=18.0),
        reference_training_by_distance=_references(),
    )

    strong_marathon = strong.estimates[-1]
    weak_marathon = weak.estimates[-1]
    assert strong_marathon.fitness_potential_time_seconds < (
        weak_marathon.fitness_potential_time_seconds
    )
    assert strong_marathon.preparation_score > weak_marathon.preparation_score
    assert strong_marathon.race_readiness_time_seconds < (weak_marathon.race_readiness_time_seconds)


def test_race_anchor_does_not_receive_workout_reserve() -> None:
    anchor = FitnessMark(
        StandardDistance.TEN_K,
        2_464.0,
        date(2026, 9, 1),
        verification_status=PerformanceLabel.VERIFIED_RACE,
        effort_type=PerformanceEffortType.WHOLE_ACTIVITY,
        activity_distance_km=10.0,
        session_kind=SessionKind.RACE,
    )
    assessment = estimate_current_fitness(
        current_marks=(anchor,),
        anchor=anchor,
        prior_anchor=None,
        training=_training(),
        reference_training_by_distance=None,
    )

    assert assessment.anchor_capacity_factor == 1.0
    assert assessment.anchor_improvement_factor == 1.0
    estimates = {estimate.distance: estimate for estimate in assessment.estimates}
    assert estimates[StandardDistance.TEN_K].fitness_potential_time_seconds == 2_464.0
    missing_five_k = estimates[StandardDistance.FIVE_K]
    assert missing_five_k.current_pb_seconds is None
    assert missing_five_k.improvement_from_pb_seconds is None
    assert missing_five_k.confidence == "low"
    assert "Riegel cross-distance baseline" in missing_five_k.basis


@pytest.mark.parametrize(
    ("current_marks", "anchor", "prior_anchor", "message"),
    (
        (
            (),
            FitnessMark(StandardDistance.FIVE_K, 1_128.0, date(2026, 9, 1)),
            None,
            "At least one",
        ),
        (
            (
                FitnessMark(StandardDistance.FIVE_K, 1_128.0, date(2026, 9, 1)),
                FitnessMark(StandardDistance.FIVE_K, 1_129.0, date(2026, 8, 1)),
            ),
            FitnessMark(StandardDistance.FIVE_K, 1_128.0, date(2026, 9, 1)),
            None,
            "unique distances",
        ),
        (
            (FitnessMark(StandardDistance.TEN_K, 2_464.0, date(2026, 3, 29)),),
            FitnessMark(StandardDistance.FIVE_K, 1_128.0, date(2026, 9, 1)),
            None,
            "included",
        ),
    ),
)
def test_invalid_assessment_inputs_are_rejected(
    current_marks: tuple[FitnessMark, ...],
    anchor: FitnessMark,
    prior_anchor: FitnessMark | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        estimate_current_fitness(
            current_marks=current_marks,
            anchor=anchor,
            prior_anchor=prior_anchor,
            training=_training(),
            reference_training_by_distance=None,
        )


def test_invalid_mark_and_training_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        FitnessMark(StandardDistance.FIVE_K, 0.0, date(2026, 9, 1))
    with pytest.raises(ValueError, match="activity distance"):
        FitnessMark(
            StandardDistance.FIVE_K,
            1_128.0,
            date(2026, 9, 1),
            activity_distance_km=0,
        )
    with pytest.raises(ValueError, match="run counts"):
        TrainingProfile(
            as_of_date=date(2026, 9, 4),
            runs_28d=-1,
            distance_28d_km=0,
            runs_84d=0,
            distance_84d_km=0,
            longest_run_84d_km=None,
            classified_sessions_84d=0,
            quality_sessions_84d=0,
            runs_168d=0,
            distance_168d_km=0,
            runs_365d=0,
            distance_365d_km=0,
        )
