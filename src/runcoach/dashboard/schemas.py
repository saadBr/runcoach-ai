"""Validated API response schemas used by the Streamlit dashboard."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)


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


class PerformanceOverview(DashboardSchema):
    """Verified personal-best and prediction-readiness response."""

    personal_bests: tuple[PersonalBest, ...] = Field(min_length=1)
    prediction_status: str = Field(min_length=1)
    prediction_method: str = Field(min_length=1)
    verified_labels: int = Field(ge=0)
    interpretation_role: str = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
