"""Validated API response schemas used by the Streamlit dashboard."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.analytics.session_classification import SessionKind


class DashboardSchema(BaseModel):
    """Strict immutable base for dashboard API contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TrainingWindow(DashboardSchema):
    """Aggregate activity totals for a fixed date window."""

    days: int = Field(ge=1)
    start_date: date
    end_date: date
    runs: int = Field(ge=0)
    distance_km: float = Field(ge=0)
    moving_hours: float = Field(ge=0)


class SensorCoverage(DashboardSchema):
    """Activity-level sensor and metric coverage."""

    activities_with_metrics: int = Field(ge=0)
    activities_with_heart_rate_load: int = Field(ge=0)
    average_heart_rate_coverage_pct: float = Field(ge=0, le=100)
    average_gps_coverage_pct: float = Field(ge=0, le=100)
    average_cadence_coverage_pct: float = Field(ge=0, le=100)


class WorkloadSnapshot(DashboardSchema):
    """One persisted daily deterministic workload state."""

    local_date: date
    load_method: str
    algorithm_version: str
    daily_load: float = Field(ge=0)
    acute_load: float | None
    chronic_load: float | None
    fitness_index: float | None
    fatigue_index: float | None
    form_index: float | None
    coverage_pct: float = Field(ge=0, le=100)


class AnalyticsOverview(DashboardSchema):
    """Dashboard overview response."""

    as_of_date: date
    data_start_date: date
    data_end_date: date
    total_runs: int = Field(ge=0)
    total_distance_km: float = Field(ge=0)
    total_moving_hours: float = Field(ge=0)
    last_7_days: TrainingWindow
    last_28_days: TrainingWindow
    sensor_coverage: SensorCoverage
    workload: WorkloadSnapshot


class WeeklyTraining(DashboardSchema):
    """One calendar-week training aggregate."""

    week_start: date
    week_end: date
    runs: int = Field(ge=0)
    distance_km: float = Field(ge=0)
    moving_hours: float = Field(ge=0)
    duration_load_minutes: float = Field(ge=0)
    weighted_pace_seconds_per_km: float | None
    elevation_gain_m: float | None
    heart_rate_load_activities: int = Field(ge=0)
    edwards_trimp: float | None


class AnalyticsTrends(DashboardSchema):
    """Weekly training and daily workload trend response."""

    start_date: date
    end_date: date
    requested_weeks: int = Field(ge=1, le=52)
    weekly_training: tuple[WeeklyTraining, ...]
    daily_workload: tuple[WorkloadSnapshot, ...]


class PersonalBest(DashboardSchema):
    """One active verified standard-distance personal best."""

    personal_best_id: UUID
    activity_id: UUID
    distance: StandardDistance
    distance_m: float = Field(gt=0)
    elapsed_time_seconds: float = Field(gt=0)
    pace_seconds_per_km: float = Field(gt=0)
    achieved_at: datetime
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    verification_source: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)


class FitnessMark(DashboardSchema):
    """One verified performance anchoring the estimate."""

    distance: StandardDistance
    elapsed_time_seconds: float = Field(gt=0)
    achieved_on: date
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    activity_distance_km: float | None = Field(gt=0)
    session_kind: SessionKind


class FitnessTraining(DashboardSchema):
    """Multi-horizon training evidence used by the estimate."""

    as_of_date: date
    runs_28d: int = Field(ge=0)
    distance_28d_km: float = Field(ge=0)
    runs_84d: int = Field(ge=0)
    distance_84d_km: float = Field(ge=0)
    longest_run_84d_km: float | None = Field(ge=0)
    classified_sessions_84d: int = Field(ge=0)
    quality_sessions_84d: int = Field(ge=0)
    runs_168d: int = Field(ge=0)
    distance_168d_km: float = Field(ge=0)
    runs_365d: int = Field(ge=0)
    distance_365d_km: float = Field(ge=0)


class FitnessEstimate(DashboardSchema):
    """One experimental distance estimate and uncertainty range."""

    distance: StandardDistance
    fitness_potential_time_seconds: float = Field(gt=0)
    race_readiness_time_seconds: float = Field(gt=0)
    optimistic_time_seconds: float = Field(gt=0)
    conservative_time_seconds: float = Field(gt=0)
    fitness_potential_pace_seconds_per_km: float = Field(gt=0)
    race_readiness_pace_seconds_per_km: float = Field(gt=0)
    preparation_score: float = Field(ge=0, le=1)
    confidence: str = Field(min_length=1)
    current_pb_seconds: float = Field(gt=0)
    improvement_from_pb_seconds: float = Field(ge=0)
    basis: str = Field(min_length=1)


class CurrentFitness(DashboardSchema):
    """Versioned current-fitness estimate and its inputs."""

    algorithm_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    as_of_date: date
    anchor: FitnessMark
    prior_anchor: FitnessMark | None
    anchor_capacity_factor: float = Field(gt=0, le=1)
    anchor_improvement_factor: float = Field(gt=0, le=1)
    training: FitnessTraining
    estimates: tuple[FitnessEstimate, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)


class PerformanceOverview(DashboardSchema):
    """Verified personal-best and current-fitness response."""

    personal_bests: tuple[PersonalBest, ...] = Field(min_length=1)
    current_fitness: CurrentFitness
    prediction_status: str = Field(min_length=1)
    prediction_method: str = Field(min_length=1)
    verified_labels: int = Field(ge=0)
    interpretation_role: str = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
