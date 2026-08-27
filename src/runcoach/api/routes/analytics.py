"""Read-only deterministic analytics API endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from runcoach.config import Settings, get_settings
from runcoach.db.analytics_queries import (
    AnalyticsQueryError,
    AnalyticsQueryService,
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
    """Latest deterministic workload state."""

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

    if settings.athlete_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Athlete configuration is unavailable.",
        )

    try:
        overview = AnalyticsQueryService(database_session).overview(
            athlete_id=settings.athlete_id,
            as_of_date=as_of_date,
        )
    except AnalyticsQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return AnalyticsOverviewResponse.model_validate(overview)
