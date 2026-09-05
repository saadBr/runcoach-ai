"""Tests for strict dashboard API response schemas."""

import pytest
from pydantic import ValidationError

from runcoach.dashboard.schemas import (
    AnalyticsOverview,
    AnalyticsTrends,
    PerformanceOverview,
)


def overview_payload() -> dict[str, object]:
    """Return a representative overview response."""

    window = {
        "days": 7,
        "start_date": "2026-08-21",
        "end_date": "2026-08-27",
        "runs": 3,
        "distance_km": 44.024,
        "moving_hours": 4.458,
    }
    workload = {
        "local_date": "2026-08-27",
        "load_method": "duration_minutes_v1",
        "algorithm_version": "daily_load_v1",
        "daily_load": 0.0,
        "acute_load": 38.5717,
        "chronic_load": 44.8069,
        "fitness_index": 44.8069,
        "fatigue_index": 38.5717,
        "form_index": 6.2352,
        "coverage_pct": 100.0,
    }

    return {
        "as_of_date": "2026-08-27",
        "data_start_date": "2024-05-21",
        "data_end_date": "2026-08-23",
        "total_runs": 130,
        "total_distance_km": 1376.081,
        "total_moving_hours": 123.432,
        "last_7_days": window,
        "last_28_days": {**window, "days": 28},
        "sensor_coverage": {
            "activities_with_metrics": 130,
            "activities_with_heart_rate_load": 85,
            "average_heart_rate_coverage_pct": 65.081,
            "average_gps_coverage_pct": 96.86,
            "average_cadence_coverage_pct": 65.081,
        },
        "workload": workload,
    }


def trends_payload() -> dict[str, object]:
    """Return a representative trends response."""

    workload = {
        "local_date": "2026-08-27",
        "load_method": "duration_minutes_v1",
        "algorithm_version": "daily_load_v1",
        "daily_load": 0.0,
        "acute_load": 38.5717,
        "chronic_load": 44.8069,
        "fitness_index": 44.8069,
        "fatigue_index": 38.5717,
        "form_index": 6.2352,
        "coverage_pct": 100.0,
    }

    return {
        "start_date": "2026-08-03",
        "end_date": "2026-08-27",
        "requested_weeks": 4,
        "weekly_training": [
            {
                "week_start": "2026-08-03",
                "week_end": "2026-08-09",
                "runs": 6,
                "distance_km": 78.844,
                "moving_hours": 7.484,
                "duration_load_minutes": 449.027,
                "weighted_pace_seconds_per_km": 341.709,
                "elevation_gain_m": 459.87,
                "heart_rate_load_activities": 6,
                "edwards_trimp": 1376.967,
            }
        ],
        "daily_workload": [workload],
    }


def performance_payload() -> dict[str, object]:
    """Return representative verified-performance evidence."""

    personal_best_id = "018f0000-0000-7000-8000-000000000020"
    return {
        "personal_bests": [
            {
                "personal_best_id": personal_best_id,
                "activity_id": "018f0000-0000-7000-8000-000000000010",
                "distance": "10k",
                "distance_m": 10000.0,
                "elapsed_time_seconds": 2464.0,
                "pace_seconds_per_km": 246.4,
                "achieved_at": "2026-03-29T09:00:00Z",
                "verification_status": "verified_race",
                "effort_type": "provider_best_effort",
                "verification_source": "strava_best_effort",
                "algorithm_version": "strava_best_effort_import_v1",
            }
        ],
        "prediction_status": "label_audit_required",
        "prediction_method": "training_feature_model",
        "verified_labels": 1,
        "interpretation_role": "openai_explains_validated_outputs_only",
        "limitations": ["No prediction is published before evaluation."],
    }


def test_overview_schema_parses_dates_and_nested_models() -> None:
    overview = AnalyticsOverview.model_validate(overview_payload())

    assert overview.total_runs == 130
    assert overview.data_start_date.isoformat() == "2024-05-21"
    assert overview.sensor_coverage.activities_with_heart_rate_load == 85
    assert overview.workload.form_index == pytest.approx(6.2352)


def test_trends_schema_parses_weekly_and_daily_series() -> None:
    trends = AnalyticsTrends.model_validate(trends_payload())

    assert trends.requested_weeks == 4
    assert trends.weekly_training[0].elevation_gain_m == pytest.approx(459.87)
    assert trends.daily_workload[0].acute_load == pytest.approx(38.5717)


def test_performance_schema_parses_evidence_and_model_readiness() -> None:
    performance = PerformanceOverview.model_validate(performance_payload())

    assert performance.personal_bests[0].distance.value == "10k"
    assert performance.personal_bests[0].achieved_at.year == 2026
    assert performance.personal_bests[0].verification_status.value == "verified_race"
    assert performance.prediction_status == "label_audit_required"
    assert performance.prediction_method == "training_feature_model"
    assert performance.verified_labels == 1


def test_schema_rejects_unknown_fields() -> None:
    payload = overview_payload()
    payload["athlete_id"] = "private-identifier"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalyticsOverview.model_validate(payload)


def test_schema_rejects_invalid_coverage() -> None:
    payload = overview_payload()
    sensor_coverage = payload["sensor_coverage"]
    assert isinstance(sensor_coverage, dict)
    sensor_coverage["average_gps_coverage_pct"] = 101.0

    with pytest.raises(ValidationError, match="less than or equal to 100"):
        AnalyticsOverview.model_validate(payload)
