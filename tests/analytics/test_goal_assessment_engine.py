"""Tests for the experimental same-distance goal assessment engine."""

from datetime import date

import pytest

from runcoach.analytics.goal_assessment import (
    TrainingBlock,
    assess_goal,
    format_duration,
)
from runcoach.analytics.performance import StandardDistance


def _block(
    *,
    runs: int,
    distance_km: float,
    longest_run_km: float | None,
    form_index: float | None = 5,
    last_run_date: date | None = date(2026, 8, 23),
) -> TrainingBlock:
    return TrainingBlock(
        end_date=date(2026, 8, 27),
        runs=runs,
        distance_km=distance_km,
        moving_hours=distance_km / 10,
        longest_run_km=longest_run_km,
        form_index=form_index,
        last_run_date=last_run_date,
    )


def test_strong_training_supports_a_bounded_sub_pb_range() -> None:
    assessment = assess_goal(
        distance=StandardDistance.FIVE_K,
        reference_pb_seconds=1_181,
        reference_pb_date=date(2026, 5, 15),
        current_block=_block(runs=22, distance_km=220, longest_run_km=20),
        reference_block=_block(runs=20, distance_km=200, longest_run_km=15),
    )

    assert assessment.status == "experimental_not_validated"
    assert assessment.confidence == "medium"
    assert assessment.training_support.support_score == pytest.approx(1.085)
    assert assessment.achievable_range.optimistic_time == "19:29"
    assert assessment.achievable_range.conservative_time == "20:16"
    assert assessment.recommended_focus.startswith("Maintain volume")


def test_long_runs_are_capped_at_distance_relevant_support() -> None:
    assessment = assess_goal(
        distance=StandardDistance.FIVE_K,
        reference_pb_seconds=1_200,
        reference_pb_date=date(2026, 1, 1),
        current_block=_block(runs=10, distance_km=100, longest_run_km=20),
        reference_block=_block(runs=10, distance_km=100, longest_run_km=40),
    )

    assert assessment.training_support.longest_run_ratio == 1
    assert assessment.training_support.support_score == 1


def test_low_volume_recommends_aerobic_rebuild() -> None:
    assessment = assess_goal(
        distance=StandardDistance.HALF_MARATHON,
        reference_pb_seconds=5_600,
        reference_pb_date=date(2026, 1, 1),
        current_block=_block(runs=10, distance_km=60, longest_run_km=25),
        reference_block=_block(runs=10, distance_km=120, longest_run_km=25),
    )

    assert assessment.recommended_focus.startswith("Rebuild sustainable aerobic volume")
    assert assessment.achievable_range.optimistic_seconds >= 5_600


def test_stale_training_lowers_confidence_and_shifts_range() -> None:
    assessment = assess_goal(
        distance=StandardDistance.TEN_K,
        reference_pb_seconds=2_400,
        reference_pb_date=date(2026, 1, 1),
        current_block=_block(
            runs=10,
            distance_km=100,
            longest_run_km=20,
            last_run_date=date(2026, 8, 1),
        ),
        reference_block=_block(runs=10, distance_km=100, longest_run_km=20),
    )

    assert assessment.confidence == "low"
    assert assessment.achievable_range.optimistic_seconds == pytest.approx(2_424)
    assert assessment.achievable_range.conservative_seconds == pytest.approx(2_520)


def test_heavy_fatigue_adds_a_conservative_penalty() -> None:
    assessment = assess_goal(
        distance=StandardDistance.MARATHON,
        reference_pb_seconds=13_200,
        reference_pb_date=date(2026, 1, 1),
        current_block=_block(
            runs=10,
            distance_km=100,
            longest_run_km=30,
            form_index=-16,
        ),
        reference_block=_block(runs=10, distance_km=100, longest_run_km=30),
    )

    assert assessment.achievable_range.optimistic_seconds == pytest.approx(13_200)
    assert assessment.achievable_range.conservative_seconds == pytest.approx(13_728)


@pytest.mark.parametrize(
    ("seconds", "formatted"),
    ((1_181, "19:41"), (5_606, "1:33:26"), (13_266, "3:41:06")),
)
def test_format_duration(seconds: float, formatted: str) -> None:
    assert format_duration(seconds) == formatted


@pytest.mark.parametrize("seconds", (0, -1, float("nan")))
def test_invalid_reference_time_is_rejected(seconds: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        assess_goal(
            distance=StandardDistance.FIVE_K,
            reference_pb_seconds=seconds,
            reference_pb_date=date(2026, 1, 1),
            current_block=_block(runs=10, distance_km=100, longest_run_km=15),
            reference_block=_block(runs=10, distance_km=100, longest_run_km=15),
        )
