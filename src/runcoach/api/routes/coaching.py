"""Goal-based coaching API endpoints backed by deterministic evidence."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
    GoalStatus,
    PlannedSessionKind,
    PlanPhase,
)
from runcoach.config import Settings, get_settings
from runcoach.db.session import get_db_session
from runcoach.db.training_plans import (
    PersistedTrainingPlan,
    TrainingPlanPersistenceError,
    TrainingPlanPersistenceService,
    TrainingPlanQueryError,
    TrainingPlanQueryService,
)

router = APIRouter(prefix="/api/v1/coaching", tags=["coaching"])

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[Session, Depends(get_db_session)]


class TrainingGoalResponse(BaseModel):
    """Goal parameters used for one plan preview."""

    model_config = ConfigDict(from_attributes=True)

    distance: StandardDistance
    race_date: date
    target_time_seconds: float | None
    days_per_week: int


class PaceRangeResponse(BaseModel):
    """Inclusive pace guidance in seconds per kilometre."""

    model_config = ConfigDict(from_attributes=True)

    faster_seconds_per_km: float
    slower_seconds_per_km: float


class PlannedSessionResponse(BaseModel):
    """One scheduled session in the first plan week."""

    model_config = ConfigDict(from_attributes=True)

    scheduled_date: date
    kind: PlannedSessionKind
    title: str
    distance_km: float
    pace: PaceRangeResponse | None
    purpose: str


class PlannedWeekResponse(BaseModel):
    """One weekly volume and focus target."""

    model_config = ConfigDict(from_attributes=True)

    week_number: int
    start_date: date
    end_date: date
    phase: PlanPhase
    target_distance_km: float
    long_run_km: float
    quality_focus: str


class TrainingPlanPreviewResponse(BaseModel):
    """Dashboard-ready goal and training-plan preview."""

    model_config = ConfigDict(from_attributes=True)

    algorithm_version: str
    status: str
    as_of_date: date
    plan_start_date: date
    goal: TrainingGoalResponse
    goal_status: GoalStatus
    weeks_to_race: int
    fitness_potential_seconds: float
    current_readiness_seconds: float
    recommended_target_seconds: float
    target_gap_seconds: float | None
    current_preparation_score: float
    recent_weekly_distance_km: float
    first_week: tuple[PlannedSessionResponse, ...]
    weekly_outline: tuple[PlannedWeekResponse, ...]
    rationale: tuple[str, ...]
    guardrails: tuple[str, ...]


class PersistedTrainingPlanResponse(BaseModel):
    """Identity, version, and snapshot for the active persisted plan."""

    goal_id: UUID
    plan_id: UUID
    version: int
    created: bool
    preview: TrainingPlanPreviewResponse


def _configured_athlete_id(settings: Settings) -> UUID:
    if settings.athlete_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Athlete configuration is unavailable.",
        )
    return settings.athlete_id


def _persisted_response(result: PersistedTrainingPlan) -> PersistedTrainingPlanResponse:
    return PersistedTrainingPlanResponse(
        goal_id=result.goal_id,
        plan_id=result.plan_id,
        version=result.version,
        created=result.created,
        preview=TrainingPlanPreviewResponse.model_validate(result.preview),
    )


@router.get("/plan-preview", response_model=TrainingPlanPreviewResponse)
def training_plan_preview(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    distance: Annotated[StandardDistance, Query(description="Target race distance.")],
    race_date: Annotated[date, Query(description="Target race date in YYYY-MM-DD format.")],
    days_per_week: Annotated[int, Query(ge=3, le=7)] = 6,
    target_time_seconds: Annotated[float | None, Query(gt=0)] = None,
) -> TrainingPlanPreviewResponse:
    """Generate a personalized plan preview without persisting it."""

    try:
        preview = TrainingPlanQueryService(database_session).preview(
            athlete_id=_configured_athlete_id(settings),
            distance=distance,
            race_date=race_date,
            target_time_seconds=target_time_seconds,
            days_per_week=days_per_week,
        )
    except TrainingPlanQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    return TrainingPlanPreviewResponse.model_validate(preview)


@router.post("/plans/active", response_model=PersistedTrainingPlanResponse)
def activate_training_plan(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    distance: Annotated[StandardDistance, Query(description="Target race distance.")],
    race_date: Annotated[date, Query(description="Target race date in YYYY-MM-DD format.")],
    days_per_week: Annotated[int, Query(ge=3, le=7)] = 6,
    target_time_seconds: Annotated[float | None, Query(gt=0)] = None,
) -> PersistedTrainingPlanResponse:
    """Create or idempotently refresh the active plan for a selected goal."""

    try:
        result = TrainingPlanPersistenceService(database_session).create_or_refresh(
            athlete_id=_configured_athlete_id(settings),
            distance=distance,
            race_date=race_date,
            target_time_seconds=target_time_seconds,
            days_per_week=days_per_week,
        )
    except (TrainingPlanQueryError, TrainingPlanPersistenceError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return _persisted_response(result)


@router.get("/plans/active", response_model=PersistedTrainingPlanResponse)
def active_training_plan(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
) -> PersistedTrainingPlanResponse:
    """Return the athlete's currently active persisted plan."""

    try:
        result = TrainingPlanPersistenceService(database_session).load_active(
            athlete_id=_configured_athlete_id(settings)
        )
    except TrainingPlanQueryError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return _persisted_response(result)


@router.post("/plans/active/refresh", response_model=PersistedTrainingPlanResponse)
def refresh_active_training_plan(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
) -> PersistedTrainingPlanResponse:
    """Regenerate the active plan from the latest imported training evidence."""

    try:
        result = TrainingPlanPersistenceService(database_session).refresh_active(
            athlete_id=_configured_athlete_id(settings)
        )
    except (TrainingPlanQueryError, TrainingPlanPersistenceError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return _persisted_response(result)
