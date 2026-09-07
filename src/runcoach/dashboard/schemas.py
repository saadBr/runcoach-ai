"""Validated API response schemas used by the Streamlit dashboard."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.analytics.performance_label_audit import LabelReviewStatus
from runcoach.analytics.session_classification import SessionKind
from runcoach.analytics.training_plan import (
    GoalStatus,
    PlannedSessionKind,
    PlanPhase,
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


class PerformanceLabelCandidate(DashboardSchema):
    """One minimized private candidate requiring a human decision."""

    review_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    achieved_at: datetime
    matched_distance: StandardDistance
    measured_distance_m: float = Field(gt=0)
    recorded_elapsed_time_seconds: float = Field(gt=0)
    distance_deviation_pct: float
    session_kind: SessionKind
    review_status: LabelReviewStatus
    review_label: PerformanceLabel | None
    verified_elapsed_time_seconds: float | None = Field(default=None, gt=0)
    review_notes: str | None = Field(default=None, max_length=500)


class PerformanceValidationMetric(DashboardSchema):
    """Aggregate chronological error metrics for one baseline."""

    baseline: str = Field(min_length=1)
    predictions: int = Field(ge=0)
    mean_absolute_error_seconds: float = Field(ge=0)
    median_absolute_error_seconds: float = Field(ge=0)
    mean_absolute_percentage_error: float = Field(ge=0)
    mean_signed_error_seconds: float


class PerformanceValidationSummary(DashboardSchema):
    """Current eligibility and aggregate chronological validation state."""

    status: str = Field(min_length=1)
    verified_labels: int = Field(ge=0)
    chronological_targets: int = Field(ge=0)
    candidate_model_eligible: bool
    eligibility_reasons: tuple[str, ...]
    aggregate_metrics: tuple[PerformanceValidationMetric, ...]


class PerformanceLabelAudit(DashboardSchema):
    """Paginated private performance review queue."""

    dataset_version: str = Field(min_length=1)
    total_rows: int = Field(ge=0)
    verified_rows: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    unreviewed_rows: int = Field(ge=0)
    offset: int = Field(ge=0)
    returned_rows: int = Field(ge=0)
    candidates: tuple[PerformanceLabelCandidate, ...]
    validation: PerformanceValidationSummary


class TrainingGoal(DashboardSchema):
    """Goal parameters used to create a plan preview."""

    distance: StandardDistance
    race_date: date
    target_time_seconds: float | None = Field(gt=0)
    days_per_week: int = Field(ge=3, le=7)


class PaceRange(DashboardSchema):
    """Inclusive pace guidance in seconds per kilometre."""

    faster_seconds_per_km: float = Field(gt=0)
    slower_seconds_per_km: float = Field(gt=0)


class PlannedSession(DashboardSchema):
    """One scheduled session in the first plan week."""

    scheduled_date: date
    kind: PlannedSessionKind
    title: str = Field(min_length=1)
    distance_km: float = Field(ge=0)
    pace: PaceRange | None
    purpose: str = Field(min_length=1)


class PlannedWeek(DashboardSchema):
    """One week in the progressive plan outline."""

    week_number: int = Field(ge=1)
    start_date: date
    end_date: date
    phase: PlanPhase
    target_distance_km: float = Field(ge=0)
    long_run_km: float = Field(ge=0)
    quality_focus: str = Field(min_length=1)


class TrainingPlanPreview(DashboardSchema):
    """Goal assessment and progressive plan preview."""

    algorithm_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    as_of_date: date
    plan_start_date: date
    goal: TrainingGoal
    goal_status: GoalStatus
    weeks_to_race: int = Field(ge=2, le=52)
    fitness_potential_seconds: float = Field(gt=0)
    current_readiness_seconds: float = Field(gt=0)
    recommended_target_seconds: float = Field(gt=0)
    target_gap_seconds: float | None
    current_preparation_score: float = Field(ge=0, le=1)
    recent_weekly_distance_km: float = Field(gt=0)
    first_week: tuple[PlannedSession, ...] = Field(min_length=3, max_length=7)
    weekly_outline: tuple[PlannedWeek, ...] = Field(min_length=2, max_length=52)
    rationale: tuple[str, ...] = Field(min_length=1)
    guardrails: tuple[str, ...] = Field(min_length=1)


class PersistedTrainingPlan(DashboardSchema):
    """The active durable plan version returned by the coaching API."""

    goal_id: UUID
    plan_id: UUID
    version: int = Field(ge=1)
    created: bool
    preview: TrainingPlanPreview


class PlanWeekProgress(DashboardSchema):
    """Actual running completed against one planned calendar week."""

    week_number: int = Field(ge=1)
    start_date: date
    end_date: date
    phase: str = Field(min_length=1)
    status: Literal["upcoming", "in_progress", "completed"]
    target_distance_km: float = Field(ge=0)
    target_long_run_km: float = Field(ge=0)
    actual_runs: int = Field(ge=0)
    actual_distance_km: float = Field(ge=0)
    actual_long_run_km: float = Field(ge=0)
    distance_completion_pct: float = Field(ge=0)
    long_run_completion_pct: float = Field(ge=0)


class PlanSessionProgress(DashboardSchema):
    """One prescribed session matched to imported activity evidence."""

    scheduled_date: date
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    target_distance_km: float = Field(ge=0)
    status: Literal["upcoming", "due", "completed", "partial", "substituted", "missed"]
    matched_activity_date: date | None
    matched_activity_name: str | None
    actual_distance_km: float | None = Field(default=None, ge=0)
    actual_pace_seconds_per_km: float | None = Field(default=None, gt=0)
    classified_as: str | None
    distance_completion_pct: float | None = Field(default=None, ge=0)
    pace_status: Literal[
        "within_range",
        "faster_than_planned",
        "easier_than_planned",
        "not_applicable",
        "unavailable",
    ]


class PlanVersionSummary(DashboardSchema):
    """A compact, immutable training-plan revision summary."""

    plan_id: UUID
    version: int = Field(ge=1)
    status: Literal["active", "superseded"]
    evidence_as_of_date: date
    created_at: datetime
    superseded_at: datetime | None
    recent_weekly_distance_km: float = Field(ge=0)
    first_week_target_km: float = Field(ge=0)
    peak_week_target_km: float = Field(ge=0)
    peak_long_run_km: float = Field(ge=0)


class ActivePlanTracking(DashboardSchema):
    """Plan adherence and version history returned by the coaching API."""

    goal_id: UUID
    plan_id: UUID
    active_version: int = Field(ge=1)
    as_of_date: date
    plan_start_date: date
    race_date: date
    status: Literal["not_started", "in_progress", "completed"]
    completed_weeks: int = Field(ge=0)
    total_weeks: int = Field(ge=1)
    current_week_number: int | None = Field(default=None, ge=1)
    planned_distance_to_date_km: float = Field(ge=0)
    actual_distance_to_date_km: float = Field(ge=0)
    adherence_pct: float | None = Field(default=None, ge=0)
    weeks: tuple[PlanWeekProgress, ...] = Field(min_length=1)
    sessions: tuple[PlanSessionProgress, ...] = Field(min_length=1)
    recommendation_code: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    versions: tuple[PlanVersionSummary, ...] = Field(min_length=1)


class UploadedRunActivity(DashboardSchema):
    """Sanitized activity facts returned after a private FIT upload."""

    title: str = Field(min_length=1)
    local_date: date
    distance_km: float | None = Field(default=None, ge=0)
    elapsed_time_seconds: float | None = Field(default=None, ge=0)
    laps: int = Field(ge=0)
    trackpoints: int = Field(ge=0)


class UploadedRunImportSummary(DashboardSchema):
    """Persistence counters for one accepted upload."""

    import_batch_id: UUID
    total_files: int = Field(ge=0)
    accepted_files: int = Field(ge=0)
    duplicate_files: int = Field(ge=0)
    matched_files: int = Field(ge=0)
    unmatched_files: int = Field(ge=0)
    ambiguous_files: int = Field(ge=0)
    source_links_created: int = Field(ge=0)
    activities_enriched: int = Field(ge=0)
    activities_unchanged: int = Field(ge=0)
    laps_written: int = Field(ge=0)
    trackpoints_written: int = Field(ge=0)
    quality_issues_created: int = Field(ge=0)
    activities_created: int = Field(ge=0)


class UploadedRunAnalytics(DashboardSchema):
    """Deterministic analytics refresh counters returned by the upload."""

    as_of_date: date
    activities_processed: int = Field(ge=0)
    activities_with_profile: int = Field(ge=0)
    activities_with_heart_rate_load: int = Field(ge=0)
    activity_metrics_created: int = Field(ge=0)
    activity_metrics_reused: int = Field(ge=0)
    daily_loads_created: int = Field(ge=0)
    daily_loads_updated: int = Field(ge=0)
    daily_loads_reused: int = Field(ge=0)


class UploadedRunPlanRefresh(DashboardSchema):
    """Plan refresh decision made after importing a run."""

    status: Literal["deferred_active_week", "refreshed"]
    new_version_created: bool


class UploadedRunResult(DashboardSchema):
    """Validated end-to-end dashboard response for one uploaded run."""

    status: Literal["updated", "duplicate"]
    activity: UploadedRunActivity
    parser_findings: int = Field(ge=0)
    import_summary: UploadedRunImportSummary | None
    analytics: UploadedRunAnalytics
    plan_refresh: UploadedRunPlanRefresh
    tracking: ActivePlanTracking


class CoachingReply(DashboardSchema):
    """Reviewed conversational coaching answer and its evidence references."""

    answer: str = Field(min_length=1, max_length=4_000)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    limitations: tuple[str, ...] = Field(max_length=5)
    mode: Literal["openai", "deterministic"]
    model: str | None
    context_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
