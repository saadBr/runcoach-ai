"""Read-only deterministic analytics API endpoints."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
)
from runcoach.analytics.session_classification import SessionKind
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


def _configured_athlete_id(
    settings: Settings,
) -> UUID:
    if settings.athlete_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Athlete configuration is unavailable.",
        )

    return settings.athlete_id


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
