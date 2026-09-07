"""Tests for strict dashboard API response schemas."""

import pytest
from pydantic import ValidationError

from runcoach.dashboard.schemas import (
    ActivePlanTracking,
    AnalyticsOverview,
    AnalyticsTrends,
    CoachingReply,
    CurrentAccount,
    LoginSession,
    PerformanceLabelAudit,
    PerformanceOverview,
    PersistedTrainingPlan,
    TrainingPlanPreview,
    UploadedRunResult,
)


def test_authentication_schemas_validate_athlete_context_and_token() -> None:
    login = LoginSession.model_validate(
        {
            "access_token": "opaque-session-token-with-sufficient-length",
            "token_type": "bearer",
            "expires_at": "2026-10-07T12:00:00Z",
            "athlete": {
                "display_name": "Synthetic Athlete",
                "timezone": "Africa/Casablanca",
                "onboarding_status": "ready",
            },
        }
    )
    current = CurrentAccount.model_validate(
        {
            "athlete": login.athlete.model_dump(mode="json"),
            "session_expires_at": login.expires_at.isoformat(),
        }
    )

    assert current.athlete.display_name == "Synthetic Athlete"
    assert current.athlete.onboarding_status == "ready"

    with pytest.raises(ValidationError):
        LoginSession.model_validate(
            {
                "access_token": "short",
                "token_type": "bearer",
                "expires_at": "2026-10-07T12:00:00Z",
                "athlete": current.athlete.model_dump(mode="json"),
            }
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
    limitations = ["Experimental estimate; chronological validation is pending."]
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
        "current_fitness": {
            "algorithm_version": "training_context_fitness_v2",
            "status": "experimental_not_validated",
            "as_of_date": "2026-04-01",
            "anchor": {
                "distance": "10k",
                "elapsed_time_seconds": 2464.0,
                "achieved_on": "2026-03-29",
                "verification_status": "verified_race",
                "effort_type": "whole_activity",
                "activity_distance_km": 10.0,
                "session_kind": "race",
            },
            "prior_anchor": None,
            "anchor_capacity_factor": 1.0,
            "anchor_improvement_factor": 1.0,
            "training": {
                "as_of_date": "2026-04-01",
                "runs_28d": 20,
                "distance_28d_km": 200.0,
                "runs_84d": 55,
                "distance_84d_km": 550.0,
                "longest_run_84d_km": 25.0,
                "classified_sessions_84d": 12,
                "quality_sessions_84d": 6,
                "runs_168d": 80,
                "distance_168d_km": 800.0,
                "runs_365d": 100,
                "distance_365d_km": 1100.0,
            },
            "estimates": [
                {
                    "distance": "10k",
                    "fitness_potential_time_seconds": 2464.0,
                    "race_readiness_time_seconds": 2464.0,
                    "optimistic_time_seconds": 2427.04,
                    "conservative_time_seconds": 2500.96,
                    "fitness_potential_pace_seconds_per_km": 246.4,
                    "race_readiness_pace_seconds_per_km": 246.4,
                    "preparation_score": 1.0,
                    "confidence": "high",
                    "current_pb_seconds": 2464.0,
                    "improvement_from_pb_seconds": 0.0,
                    "basis": "Newest verified performance at this distance.",
                }
            ],
            "limitations": limitations,
        },
        "prediction_status": "experimental_not_validated",
        "prediction_method": "training_context_fitness_v2",
        "verified_labels": 1,
        "interpretation_role": "openai_explains_validated_outputs_only",
        "limitations": limitations,
    }


def training_plan_payload() -> dict[str, object]:
    """Return a representative goal-based plan preview."""

    session = {
        "scheduled_date": "2026-09-08",
        "kind": "easy",
        "title": "Easy aerobic run",
        "distance_km": 9.0,
        "pace": {
            "faster_seconds_per_km": 306.0,
            "slower_seconds_per_km": 346.0,
        },
        "purpose": "Maintain aerobic frequency.",
    }
    week = {
        "week_number": 1,
        "start_date": "2026-09-07",
        "end_date": "2026-09-13",
        "phase": "base",
        "target_distance_km": 71.7,
        "long_run_km": 22.9,
        "quality_focus": "marathon pace and fueling durability",
    }
    return {
        "algorithm_version": "goal_plan_preview_v1",
        "status": "preview_not_persisted",
        "as_of_date": "2026-09-04",
        "plan_start_date": "2026-09-07",
        "goal": {
            "distance": "marathon",
            "race_date": "2026-11-29",
            "target_time_seconds": 11400.0,
            "days_per_week": 6,
        },
        "goal_status": "achievable",
        "weeks_to_race": 12,
        "fitness_potential_seconds": 11388.665,
        "current_readiness_seconds": 11461.396,
        "recommended_target_seconds": 11461.396,
        "target_gap_seconds": -61.396,
        "current_preparation_score": 0.92,
        "recent_weekly_distance_km": 77.972,
        "first_week": [session, session, session],
        "weekly_outline": [week, {**week, "week_number": 2}],
        "rationale": ["The plan uses current fitness and training evidence."],
        "guardrails": ["Keep easy days conversational."],
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


def test_performance_schema_parses_evidence_and_fitness_estimate() -> None:
    performance = PerformanceOverview.model_validate(performance_payload())

    assert performance.personal_bests[0].distance.value == "10k"
    assert performance.personal_bests[0].achieved_at.year == 2026
    assert performance.personal_bests[0].verification_status.value == "verified_race"
    assert performance.prediction_status == "experimental_not_validated"
    assert performance.prediction_method == "training_context_fitness_v2"
    assert performance.verified_labels == 1
    assert performance.current_fitness.training.runs_365d == 100
    assert performance.current_fitness.estimates[0].fitness_potential_time_seconds == 2464.0


def test_performance_label_audit_schema_parses_review_and_validation() -> None:
    audit = PerformanceLabelAudit.model_validate(
        {
            "dataset_version": "performance_training_features_v3",
            "total_rows": 70,
            "verified_rows": 5,
            "excluded_rows": 10,
            "unreviewed_rows": 55,
            "offset": 0,
            "returned_rows": 1,
            "candidates": [
                {
                    "review_token": "a" * 64,
                    "achieved_at": "2026-07-01T08:00:00Z",
                    "matched_distance": "5k",
                    "measured_distance_m": 5005.0,
                    "recorded_elapsed_time_seconds": 1260.0,
                    "distance_deviation_pct": 0.1,
                    "session_kind": "unclassified",
                    "review_status": "unreviewed",
                    "review_label": None,
                    "verified_elapsed_time_seconds": None,
                    "review_notes": None,
                }
            ],
            "validation": {
                "status": "descriptive_only",
                "verified_labels": 5,
                "chronological_targets": 4,
                "candidate_model_eligible": False,
                "eligibility_reasons": ["More labels are required."],
                "aggregate_metrics": [
                    {
                        "baseline": "riegel_best_prior",
                        "predictions": 4,
                        "mean_absolute_error_seconds": 539.5,
                        "median_absolute_error_seconds": 113.1,
                        "mean_absolute_percentage_error": 5.6,
                        "mean_signed_error_seconds": -512.6,
                    }
                ],
            },
        }
    )

    assert audit.total_rows == 70
    assert audit.candidates[0].matched_distance.value == "5k"
    assert audit.candidates[0].review_status.value == "unreviewed"
    assert audit.validation.aggregate_metrics[0].predictions == 4


def test_training_plan_schema_parses_goal_sessions_and_weeks() -> None:
    plan = TrainingPlanPreview.model_validate(training_plan_payload())

    assert plan.goal.distance.value == "marathon"
    assert plan.goal_status.value == "achievable"
    assert plan.first_week[0].pace is not None
    assert plan.first_week[0].pace.faster_seconds_per_km == 306.0
    assert plan.weekly_outline[0].phase.value == "base"


def test_persisted_training_plan_schema_wraps_versioned_preview() -> None:
    plan = PersistedTrainingPlan.model_validate(
        {
            "goal_id": "018f0000-0000-7000-8000-000000000030",
            "plan_id": "018f0000-0000-7000-8000-000000000031",
            "version": 2,
            "created": True,
            "preview": training_plan_payload(),
        }
    )

    assert plan.version == 2
    assert plan.preview.goal.race_date.isoformat() == "2026-11-29"


def test_active_plan_tracking_schema_parses_progress_and_history() -> None:
    tracking = ActivePlanTracking.model_validate(
        {
            "goal_id": "018f0000-0000-7000-8000-000000000030",
            "plan_id": "018f0000-0000-7000-8000-000000000031",
            "active_version": 2,
            "as_of_date": "2026-09-13",
            "plan_start_date": "2026-09-07",
            "race_date": "2027-01-31",
            "status": "in_progress",
            "completed_weeks": 0,
            "total_weeks": 21,
            "current_week_number": 1,
            "planned_distance_to_date_km": 70.0,
            "actual_distance_to_date_km": 72.0,
            "adherence_pct": 102.9,
            "weeks": [
                {
                    "week_number": 1,
                    "start_date": "2026-09-07",
                    "end_date": "2026-09-13",
                    "phase": "base",
                    "status": "in_progress",
                    "target_distance_km": 70.0,
                    "target_long_run_km": 24.0,
                    "actual_runs": 6,
                    "actual_distance_km": 72.0,
                    "actual_long_run_km": 25.0,
                    "distance_completion_pct": 102.9,
                    "long_run_completion_pct": 104.2,
                }
            ],
            "sessions": [
                {
                    "scheduled_date": "2026-09-13",
                    "kind": "long",
                    "title": "Long aerobic run",
                    "target_distance_km": 24.0,
                    "status": "completed",
                    "matched_activity_date": "2026-09-13",
                    "matched_activity_name": "Progressive long run",
                    "actual_distance_km": 25.0,
                    "actual_pace_seconds_per_km": 330.0,
                    "classified_as": "progressive",
                    "distance_completion_pct": 104.2,
                    "pace_status": "within_range",
                }
            ],
            "recommendation_code": "continue_as_planned",
            "recommendation": "Continue with the next scheduled session.",
            "versions": [
                {
                    "plan_id": "018f0000-0000-7000-8000-000000000031",
                    "version": 2,
                    "status": "active",
                    "evidence_as_of_date": "2026-09-06",
                    "created_at": "2026-09-06T10:00:00Z",
                    "superseded_at": None,
                    "recent_weekly_distance_km": 80.0,
                    "first_week_target_km": 70.0,
                    "peak_week_target_km": 85.0,
                    "peak_long_run_km": 32.0,
                }
            ],
        }
    )

    assert tracking.active_version == 2
    assert tracking.weeks[0].actual_runs == 6
    assert tracking.sessions[0].matched_activity_name == "Progressive long run"
    assert tracking.versions[0].evidence_as_of_date.isoformat() == "2026-09-06"


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


def test_uploaded_run_schema_parses_refresh_and_recommendation() -> None:
    result = UploadedRunResult.model_validate(
        {
            "status": "updated",
            "activity": {
                "title": "Tempo Run",
                "local_date": "2026-09-06",
                "distance_km": 10.0,
                "elapsed_time_seconds": 2400.0,
                "laps": 4,
                "trackpoints": 800,
            },
            "parser_findings": 0,
            "import_summary": {
                "import_batch_id": "018f0000-0000-7000-8000-000000000040",
                "total_files": 1,
                "accepted_files": 1,
                "duplicate_files": 0,
                "matched_files": 1,
                "unmatched_files": 0,
                "ambiguous_files": 0,
                "source_links_created": 1,
                "activities_enriched": 1,
                "activities_unchanged": 0,
                "laps_written": 4,
                "trackpoints_written": 800,
                "quality_issues_created": 0,
                "activities_created": 1,
            },
            "analytics": {
                "as_of_date": "2026-09-06",
                "activities_processed": 143,
                "activities_with_profile": 103,
                "activities_with_heart_rate_load": 98,
                "activity_metrics_created": 1,
                "activity_metrics_reused": 142,
                "daily_loads_created": 1,
                "daily_loads_updated": 0,
                "daily_loads_reused": 839,
            },
            "plan_refresh": {
                "status": "deferred_active_week",
                "new_version_created": False,
            },
            "tracking": {
                "goal_id": "018f0000-0000-7000-8000-000000000030",
                "plan_id": "018f0000-0000-7000-8000-000000000031",
                "active_version": 2,
                "as_of_date": "2026-09-06",
                "plan_start_date": "2026-09-07",
                "race_date": "2027-01-31",
                "status": "not_started",
                "completed_weeks": 0,
                "total_weeks": 21,
                "current_week_number": None,
                "planned_distance_to_date_km": 0.0,
                "actual_distance_to_date_km": 0.0,
                "adherence_pct": None,
                "weeks": [
                    {
                        "week_number": 1,
                        "start_date": "2026-09-07",
                        "end_date": "2026-09-13",
                        "phase": "base",
                        "status": "upcoming",
                        "target_distance_km": 70.0,
                        "target_long_run_km": 24.0,
                        "actual_runs": 0,
                        "actual_distance_km": 0.0,
                        "actual_long_run_km": 0.0,
                        "distance_completion_pct": 0.0,
                        "long_run_completion_pct": 0.0,
                    }
                ],
                "sessions": [
                    {
                        "scheduled_date": "2026-09-07",
                        "kind": "easy",
                        "title": "Easy aerobic run",
                        "target_distance_km": 8.5,
                        "status": "upcoming",
                        "matched_activity_date": None,
                        "matched_activity_name": None,
                        "actual_distance_km": None,
                        "actual_pace_seconds_per_km": None,
                        "classified_as": None,
                        "distance_completion_pct": None,
                        "pace_status": "unavailable",
                    }
                ],
                "recommendation_code": "plan_not_started",
                "recommendation": "Begin with the scheduled easy aerobic run.",
                "versions": [
                    {
                        "plan_id": "018f0000-0000-7000-8000-000000000031",
                        "version": 2,
                        "status": "active",
                        "evidence_as_of_date": "2026-09-06",
                        "created_at": "2026-09-06T10:00:00Z",
                        "superseded_at": None,
                        "recent_weekly_distance_km": 77.0,
                        "first_week_target_km": 70.0,
                        "peak_week_target_km": 85.0,
                        "peak_long_run_km": 32.0,
                    }
                ],
            },
        }
    )

    assert result.status == "updated"
    assert result.activity.local_date.isoformat() == "2026-09-06"
    assert result.import_summary is not None
    assert result.import_summary.trackpoints_written == 800
    assert result.tracking.recommendation_code == "plan_not_started"


def test_coaching_reply_schema_preserves_provenance() -> None:
    reply = CoachingReply.model_validate(
        {
            "answer": "The next session is an easy 8.5 km run.",
            "evidence_ids": ["plan:next-session:1"],
            "limitations": ["Sleep and soreness are not represented."],
            "mode": "openai",
            "model": "gpt-test",
            "context_version": "coaching_context_v1",
            "prompt_version": "evidence_coach_v1",
        }
    )

    assert reply.mode == "openai"
    assert reply.evidence_ids == ("plan:next-session:1",)

    with pytest.raises(ValidationError):
        CoachingReply.model_validate(
            {
                **reply.model_dump(),
                "evidence_ids": [],
            }
        )
