"""Tests for leakage-safe chronological performance validation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from runcoach.analytics.performance import (
    PerformanceLabel,
    StandardDistance,
    VerifiedPerformance,
)
from runcoach.analytics.performance_validation import (
    MINIMUM_VERIFIED_LABELS,
    PerformanceObservation,
    evaluate_performance_baselines,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _observation(
    number: int,
    day: int,
    distance: StandardDistance,
    seconds: float,
) -> PerformanceObservation:
    activity_id = UUID(int=number)
    return PerformanceObservation(
        observation_id=activity_id,
        performance=VerifiedPerformance(
            activity_id=activity_id,
            distance=distance,
            elapsed_time_seconds=seconds,
            achieved_at=START + timedelta(days=day),
            label=PerformanceLabel.VERIFIED_RACE,
        ),
    )


def _history() -> tuple[PerformanceObservation, ...]:
    return (
        _observation(1, 0, StandardDistance.TEN_K, 2_400.0),
        _observation(2, 31, StandardDistance.FIVE_K, 1_140.0),
        _observation(3, 60, StandardDistance.TEN_K, 2_310.0),
        _observation(4, 90, StandardDistance.HALF_MARATHON, 5_160.0),
        _observation(5, 120, StandardDistance.FIVE_K, 1_110.0),
    )


def test_walk_forward_predictions_use_only_strictly_earlier_sources() -> None:
    observations = _history()

    report = evaluate_performance_baselines(observations)

    achieved_at = {item.observation_id: item.performance.achieved_at for item in observations}
    assert report.verified_labels == 5
    assert report.chronological_targets == 4
    assert report.status == "descriptive_only"
    assert not report.candidate_model_eligible
    assert any("30" in reason for reason in report.eligibility_reasons)
    for prediction in report.predictions:
        assert prediction.source_observation_ids
        assert all(
            achieved_at[source_id] < prediction.target_achieved_at
            for source_id in prediction.source_observation_ids
        )


def test_riegel_baseline_uses_fastest_projection_from_prior_evidence() -> None:
    report = evaluate_performance_baselines(_history())

    prediction = next(
        item
        for item in report.predictions
        if item.baseline == "riegel_best_prior" and item.target_observation_id == UUID(int=3)
    )

    assert prediction.source_observation_ids == (UUID(int=2),)
    assert prediction.predicted_time_seconds < 2_400.0
    assert prediction.signed_error_seconds == pytest.approx(
        prediction.predicted_time_seconds - prediction.actual_time_seconds,
        abs=0.001,
    )


def test_same_distance_baselines_report_aggregate_and_distance_metrics() -> None:
    report = evaluate_performance_baselines(_history())

    recent = tuple(item for item in report.metrics if item.baseline == "recent_same_distance")

    assert recent[0].target_distance is None
    assert recent[0].predictions == 2
    assert {item.target_distance for item in recent[1:]} == {
        StandardDistance.FIVE_K,
        StandardDistance.TEN_K,
    }


def test_equal_timestamp_observations_cannot_predict_each_other() -> None:
    first = _observation(1, 0, StandardDistance.FIVE_K, 1_200.0)
    second = _observation(2, 0, StandardDistance.TEN_K, 2_500.0)

    report = evaluate_performance_baselines((first, second))

    assert report.chronological_targets == 0
    assert report.predictions == ()
    assert report.metrics == ()


def test_duplicate_observation_id_is_rejected() -> None:
    observation = _observation(1, 0, StandardDistance.FIVE_K, 1_200.0)

    with pytest.raises(ValueError, match="identifiers must be unique"):
        evaluate_performance_baselines((observation, observation))


def test_observation_id_must_match_performance_activity() -> None:
    performance = _observation(1, 0, StandardDistance.FIVE_K, 1_200.0).performance

    with pytest.raises(ValueError, match="identifiers must match"):
        PerformanceObservation(observation_id=UUID(int=2), performance=performance)


def test_eligibility_gate_passes_only_with_enough_walk_forward_labels() -> None:
    observations = tuple(
        _observation(
            number=index + 1,
            day=index,
            distance=(StandardDistance.FIVE_K if index % 2 == 0 else StandardDistance.TEN_K),
            seconds=1_200.0 + index,
        )
        for index in range(MINIMUM_VERIFIED_LABELS)
    )

    report = evaluate_performance_baselines(observations)

    assert report.candidate_model_eligible
    assert report.status == "eligible_for_candidate_model"
    assert report.eligibility_reasons == ()
    assert report.chronological_targets == MINIMUM_VERIFIED_LABELS - 1
