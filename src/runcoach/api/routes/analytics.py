"""Read-only deterministic analytics API endpoints."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParameter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.analytics.performance_label_audit import (
    LabelAuditError,
    LabelReviewDecision,
    LabelReviewStatus,
    PerformanceLabelAudit,
    PerformanceLabelCandidate,
    candidate_for_review_token,
    evaluate_label_audit,
    label_audit_path,
    load_label_audit,
    review_token,
    update_and_validate,
)
from runcoach.analytics.performance_validation import PerformanceValidationReport
from runcoach.analytics.session_classification import SessionKind, classify_session
from runcoach.config import Settings, get_settings
from runcoach.db.analytics_queries import (
    AnalyticsQueryError,
    AnalyticsQueryService,
)
from runcoach.db.analytics_trends import (
    AnalyticsTrendsQueryError,
    AnalyticsTrendsQueryService,
)
from runcoach.db.performance_queries import (
    PerformanceQueryError,
    PerformanceQueryService,
)
from runcoach.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[
    Session,
    Depends(get_db_session),
]


class TrainingWindowResponse(BaseModel):
    """Aggregated training inside one inclusive date window."""

    model_config = ConfigDict(from_attributes=True)

    days: int
    start_date: date
    end_date: date
    runs: int
    distance_km: float
    moving_hours: float


class SensorCoverageResponse(BaseModel):
    """Aggregate sensor availability for calculated activities."""

    model_config = ConfigDict(from_attributes=True)

    activities_with_metrics: int
    activities_with_heart_rate_load: int
    average_heart_rate_coverage_pct: float
    average_gps_coverage_pct: float
    average_cadence_coverage_pct: float


class WorkloadSnapshotResponse(BaseModel):
    """One deterministic daily workload state."""

    model_config = ConfigDict(from_attributes=True)

    local_date: date
    load_method: str
    algorithm_version: str
    daily_load: float
    acute_load: float | None
    chronic_load: float | None
    fitness_index: float | None
    fatigue_index: float | None
    form_index: float | None
    coverage_pct: float


class AnalyticsOverviewResponse(BaseModel):
    """Dashboard-ready analytics overview."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    data_start_date: date
    data_end_date: date
    total_runs: int
    total_distance_km: float
    total_moving_hours: float
    last_7_days: TrainingWindowResponse
    last_28_days: TrainingWindowResponse
    sensor_coverage: SensorCoverageResponse
    workload: WorkloadSnapshotResponse


class WeeklyTrainingResponse(BaseModel):
    """One calendar-week training aggregate."""

    model_config = ConfigDict(from_attributes=True)

    week_start: date
    week_end: date
    runs: int
    distance_km: float
    moving_hours: float
    duration_load_minutes: float
    weighted_pace_seconds_per_km: float | None
    elevation_gain_m: float | None
    heart_rate_load_activities: int
    edwards_trimp: float | None


class AnalyticsTrendsResponse(BaseModel):
    """Dashboard-ready weekly and daily trend series."""

    model_config = ConfigDict(from_attributes=True)

    start_date: date
    end_date: date
    requested_weeks: int
    weekly_training: tuple[WeeklyTrainingResponse, ...]
    daily_workload: tuple[WorkloadSnapshotResponse, ...]


class PersonalBestResponse(BaseModel):
    """One active verified standard-distance personal best."""

    model_config = ConfigDict(from_attributes=True)

    personal_best_id: UUID
    activity_id: UUID
    distance: StandardDistance
    distance_m: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float
    achieved_at: datetime
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    verification_source: str
    algorithm_version: str


class FitnessMarkResponse(BaseModel):
    """One verified mark anchoring the current-fitness estimate."""

    model_config = ConfigDict(from_attributes=True)

    distance: StandardDistance
    elapsed_time_seconds: float
    achieved_on: date
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    activity_distance_km: float | None
    session_kind: SessionKind


class FitnessTrainingResponse(BaseModel):
    """Multi-horizon training evidence used by the estimator."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    runs_28d: int
    distance_28d_km: float
    runs_84d: int
    distance_84d_km: float
    longest_run_84d_km: float | None
    classified_sessions_84d: int
    quality_sessions_84d: int
    runs_168d: int
    distance_168d_km: float
    runs_365d: int
    distance_365d_km: float


class FitnessEstimateResponse(BaseModel):
    """One experimental distance estimate and uncertainty interval."""

    model_config = ConfigDict(from_attributes=True)

    distance: StandardDistance
    fitness_potential_time_seconds: float
    race_readiness_time_seconds: float
    optimistic_time_seconds: float
    conservative_time_seconds: float
    fitness_potential_pace_seconds_per_km: float
    race_readiness_pace_seconds_per_km: float
    preparation_score: float
    confidence: str
    current_pb_seconds: float
    improvement_from_pb_seconds: float
    basis: str


class CurrentFitnessResponse(BaseModel):
    """Versioned current-fitness assessment and its evidence."""

    model_config = ConfigDict(from_attributes=True)

    algorithm_version: str
    status: str
    as_of_date: date
    anchor: FitnessMarkResponse
    prior_anchor: FitnessMarkResponse | None
    anchor_capacity_factor: float
    anchor_improvement_factor: float
    training: FitnessTrainingResponse
    estimates: tuple[FitnessEstimateResponse, ...]
    limitations: tuple[str, ...]


class PerformanceOverviewResponse(BaseModel):
    """Verified personal bests and an experimental current-fitness estimate."""

    model_config = ConfigDict(from_attributes=True)

    personal_bests: tuple[PersonalBestResponse, ...]
    current_fitness: CurrentFitnessResponse
    prediction_status: str
    prediction_method: str
    verified_labels: int
    interpretation_role: str
    limitations: tuple[str, ...]


class PerformanceLabelCandidateResponse(BaseModel):
    """Minimal private candidate data required for human performance review."""

    model_config = ConfigDict(from_attributes=True)

    review_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    achieved_at: datetime
    matched_distance: StandardDistance
    measured_distance_m: float
    recorded_elapsed_time_seconds: float
    distance_deviation_pct: float
    session_kind: SessionKind
    review_status: LabelReviewStatus
    review_label: PerformanceLabel | None
    verified_elapsed_time_seconds: float | None
    review_notes: str | None


class PerformanceValidationMetricResponse(BaseModel):
    """Aggregate error metrics for one chronological baseline."""

    model_config = ConfigDict(from_attributes=True)

    baseline: str
    predictions: int
    mean_absolute_error_seconds: float
    median_absolute_error_seconds: float
    mean_absolute_percentage_error: float
    mean_signed_error_seconds: float


class PerformanceValidationSummaryResponse(BaseModel):
    """Non-identifying validation state derived from reviewed labels."""

    status: str
    verified_labels: int
    chronological_targets: int
    candidate_model_eligible: bool
    eligibility_reasons: tuple[str, ...]
    aggregate_metrics: tuple[PerformanceValidationMetricResponse, ...]


class PerformanceLabelAuditResponse(BaseModel):
    """Paginated local review queue and its validation progress."""

    dataset_version: str
    total_rows: int
    verified_rows: int
    excluded_rows: int
    unreviewed_rows: int
    offset: int
    returned_rows: int
    candidates: tuple[PerformanceLabelCandidateResponse, ...]
    validation: PerformanceValidationSummaryResponse


class PerformanceLabelReviewRequest(BaseModel):
    """One explicit human decision for a private candidate performance."""

    model_config = ConfigDict(extra="forbid")

    review_status: LabelReviewStatus
    review_label: PerformanceLabel | None = None
    verified_elapsed_time_seconds: float | None = Field(default=None, gt=0)
    review_notes: str | None = Field(default=None, max_length=500)


def _configured_athlete_id(
    settings: Settings,
) -> UUID:
    if settings.athlete_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Athlete configuration is unavailable.",
        )

    return settings.athlete_id


def _require_local_label_audit(settings: Settings) -> None:
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance label audit is unavailable.",
        )


def _validation_summary(
    report: PerformanceValidationReport,
) -> PerformanceValidationSummaryResponse:
    aggregate_metrics = tuple(
        PerformanceValidationMetricResponse.model_validate(metric)
        for metric in report.metrics
        if metric.target_distance is None
    )
    return PerformanceValidationSummaryResponse(
        status=report.status,
        verified_labels=report.verified_labels,
        chronological_targets=report.chronological_targets,
        candidate_model_eligible=report.candidate_model_eligible,
        eligibility_reasons=report.eligibility_reasons,
        aggregate_metrics=aggregate_metrics,
    )


def _label_audit_response(
    audit: PerformanceLabelAudit,
    report: PerformanceValidationReport,
    *,
    candidates: tuple[PerformanceLabelCandidate, ...],
    offset: int,
) -> PerformanceLabelAuditResponse:
    return PerformanceLabelAuditResponse(
        dataset_version=audit.dataset_version,
        total_rows=audit.total_rows,
        verified_rows=audit.verified_rows,
        excluded_rows=audit.excluded_rows,
        unreviewed_rows=audit.unreviewed_rows,
        offset=offset,
        returned_rows=len(candidates),
        candidates=tuple(
            PerformanceLabelCandidateResponse(
                review_token=review_token(
                    dataset_version=audit.dataset_version,
                    activity_id=candidate.activity_id,
                ),
                achieved_at=candidate.achieved_at,
                matched_distance=candidate.matched_distance,
                measured_distance_m=candidate.measured_distance_m,
                recorded_elapsed_time_seconds=candidate.recorded_elapsed_time_seconds,
                distance_deviation_pct=candidate.distance_deviation_pct,
                session_kind=classify_session(candidate.activity_name).primary_kind,
                review_status=candidate.review_status,
                review_label=candidate.review_label,
                verified_elapsed_time_seconds=candidate.verified_elapsed_time_seconds,
                review_notes=candidate.review_notes,
            )
            for candidate in candidates
        ),
        validation=_validation_summary(report),
    )


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
)
def analytics_overview(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    as_of_date: Annotated[
        date | None,
        Query(
            description=(
                "Exact calculated local date. Omit to use the latest available workload snapshot."
            )
        ),
    ] = None,
) -> AnalyticsOverviewResponse:
    """Return deterministic activity and workload aggregates."""

    athlete_id = _configured_athlete_id(settings)

    try:
        overview = AnalyticsQueryService(database_session).overview(
            athlete_id=athlete_id,
            as_of_date=as_of_date,
        )
    except AnalyticsQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return AnalyticsOverviewResponse.model_validate(overview)


@router.get(
    "/trends",
    response_model=AnalyticsTrendsResponse,
)
def analytics_trends(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    weeks: Annotated[
        int,
        Query(
            ge=1,
            le=52,
            description="Number of calendar weeks to return.",
        ),
    ] = 12,
    end_date: Annotated[
        date | None,
        Query(
            description=("Exact calculated local end date. Omit to use the latest workload date.")
        ),
    ] = None,
) -> AnalyticsTrendsResponse:
    """Return weekly training and daily workload trend series."""

    athlete_id = _configured_athlete_id(settings)

    try:
        trends = AnalyticsTrendsQueryService(database_session).trends(
            athlete_id=athlete_id,
            weeks=weeks,
            end_date=end_date,
        )
    except AnalyticsTrendsQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return AnalyticsTrendsResponse.model_validate(trends)


@router.get(
    "/performance",
    response_model=PerformanceOverviewResponse,
)
def analytics_performance(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
) -> PerformanceOverviewResponse:
    """Return verified PBs and an auditable experimental fitness estimate."""

    athlete_id = _configured_athlete_id(settings)

    try:
        performance = PerformanceQueryService(database_session).overview(
            athlete_id=athlete_id,
        )
    except PerformanceQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return PerformanceOverviewResponse.model_validate(performance)


@router.get(
    "/performance/label-audit",
    response_model=PerformanceLabelAuditResponse,
)
def performance_label_audit(
    settings: SettingsDependency,
    review_status: Annotated[
        LabelReviewStatus | None,
        Query(description="Optional human-review state used to filter candidates."),
    ] = LabelReviewStatus.UNREVIEWED,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PerformanceLabelAuditResponse:
    """Return a private, minimized candidate queue and current validation state."""

    _configured_athlete_id(settings)
    _require_local_label_audit(settings)
    try:
        audit = load_label_audit(label_audit_path(settings.private_data_dir))
        report = evaluate_label_audit(audit)
    except LabelAuditError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Performance label audit is unavailable. Export the private performance "
                "dataset first."
            ),
        ) from None
    candidates = tuple(
        candidate
        for candidate in audit.candidates
        if review_status is None or candidate.review_status is review_status
    )[offset : offset + limit]
    return _label_audit_response(
        audit,
        report,
        candidates=candidates,
        offset=offset,
    )


@router.put(
    "/performance/label-audit/{review_token_value}",
    response_model=PerformanceLabelAuditResponse,
)
def review_performance_candidate(
    review_token_value: Annotated[
        str,
        PathParameter(pattern=r"^[0-9a-f]{64}$"),
    ],
    request: PerformanceLabelReviewRequest,
    settings: SettingsDependency,
) -> PerformanceLabelAuditResponse:
    """Persist one private label decision and immediately rerun validation."""

    _configured_athlete_id(settings)
    _require_local_label_audit(settings)
    try:
        decision = LabelReviewDecision(
            review_status=request.review_status,
            review_label=request.review_label,
            verified_elapsed_time_seconds=request.verified_elapsed_time_seconds,
            review_notes=request.review_notes,
        )
        current_audit = load_label_audit(label_audit_path(settings.private_data_dir))
        selected_candidate = candidate_for_review_token(
            current_audit,
            review_token_value,
        )
        audit, report = update_and_validate(
            private_data_dir=settings.private_data_dir,
            activity_id=selected_candidate.activity_id,
            decision=decision,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except LabelAuditError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance label audit or candidate is unavailable.",
        ) from None
    candidate = next(
        item for item in audit.candidates if item.activity_id == selected_candidate.activity_id
    )
    return _label_audit_response(
        audit,
        report,
        candidates=(candidate,),
        offset=0,
    )
