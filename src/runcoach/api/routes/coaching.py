"""Goal-based coaching API endpoints backed by deterministic evidence."""

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
    GoalStatus,
    PlannedSessionKind,
    PlanPhase,
)
from runcoach.coaching.chat import (
    CoachingChatError,
    CoachingReply,
    ConversationTurn,
    build_conversational_coach,
)
from runcoach.coaching.update import known_strava_hashes, update_coaching_from_inputs
from runcoach.coaching.uploads import (
    PreparedRunUpload,
    RunUploadValidationError,
    prepare_strava_fit_upload,
)
from runcoach.config import Settings, get_settings
from runcoach.db.analytics import AnalyticsPersistenceError
from runcoach.db.models import Athlete
from runcoach.db.sensors import SensorPersistenceError
from runcoach.db.session import get_db_session
from runcoach.db.training_plan_tracking import (
    TrainingPlanTrackingError,
    TrainingPlanTrackingService,
)
from runcoach.db.training_plans import (
    PersistedTrainingPlan,
    TrainingPlanPersistenceError,
    TrainingPlanPersistenceService,
    TrainingPlanQueryError,
    TrainingPlanQueryService,
)

router = APIRouter(prefix="/api/v1/coaching", tags=["coaching"])

MAX_RUN_UPLOAD_BYTES = 25 * 1024 * 1024

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


class PlanWeekProgressResponse(BaseModel):
    """Actual running completed against one planned calendar week."""

    model_config = ConfigDict(from_attributes=True)

    week_number: int
    start_date: date
    end_date: date
    phase: str
    status: str
    target_distance_km: float
    target_long_run_km: float
    actual_runs: int
    actual_distance_km: float
    actual_long_run_km: float
    distance_completion_pct: float
    long_run_completion_pct: float


class PlanSessionProgressResponse(BaseModel):
    """One prescribed first-week session matched to imported activity evidence."""

    model_config = ConfigDict(from_attributes=True)

    scheduled_date: date
    kind: str
    title: str
    target_distance_km: float
    status: str
    matched_activity_date: date | None
    matched_activity_name: str | None
    actual_distance_km: float | None
    actual_pace_seconds_per_km: float | None
    classified_as: str | None
    distance_completion_pct: float | None
    pace_status: str


class PlanVersionSummaryResponse(BaseModel):
    """A compact summary of one immutable generated plan version."""

    model_config = ConfigDict(from_attributes=True)

    plan_id: UUID
    version: int
    status: str
    evidence_as_of_date: date
    created_at: datetime
    superseded_at: datetime | None
    recent_weekly_distance_km: float
    first_week_target_km: float
    peak_week_target_km: float
    peak_long_run_km: float


class ActivePlanTrackingResponse(BaseModel):
    """Weekly adherence and revision history for the active plan."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: UUID
    plan_id: UUID
    active_version: int
    as_of_date: date
    plan_start_date: date
    race_date: date
    status: str
    completed_weeks: int
    total_weeks: int
    current_week_number: int | None
    planned_distance_to_date_km: float
    actual_distance_to_date_km: float
    adherence_pct: float | None
    weeks: tuple[PlanWeekProgressResponse, ...]
    sessions: tuple[PlanSessionProgressResponse, ...]
    recommendation_code: str
    recommendation: str
    versions: tuple[PlanVersionSummaryResponse, ...]


class RunUploadActivityResponse(BaseModel):
    """Sanitized summary of the running activity contained in an upload."""

    title: str
    local_date: date
    distance_km: float | None
    elapsed_time_seconds: float | None
    laps: int
    trackpoints: int


class SensorImportSummaryResponse(BaseModel):
    """Non-sensitive persistence counters for one uploaded run."""

    model_config = ConfigDict(from_attributes=True)

    import_batch_id: UUID
    total_files: int
    accepted_files: int
    duplicate_files: int
    matched_files: int
    unmatched_files: int
    ambiguous_files: int
    source_links_created: int
    activities_enriched: int
    activities_unchanged: int
    laps_written: int
    trackpoints_written: int
    quality_issues_created: int
    activities_created: int


class AnalyticsRefreshResponse(BaseModel):
    """Counters from the deterministic analytics refresh."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    activities_processed: int
    activities_with_profile: int
    activities_with_heart_rate_load: int
    activity_metrics_created: int
    activity_metrics_reused: int
    daily_loads_created: int
    daily_loads_updated: int
    daily_loads_reused: int


class PlanRefreshResponse(BaseModel):
    """Whether the stable detailed week was retained or rolled forward."""

    status: str
    new_version_created: bool


class RunUploadResponse(BaseModel):
    """End-to-end result of uploading one Strava run."""

    status: str
    activity: RunUploadActivityResponse
    parser_findings: int
    import_summary: SensorImportSummaryResponse | None
    analytics: AnalyticsRefreshResponse
    plan_refresh: PlanRefreshResponse
    tracking: ActivePlanTrackingResponse


class CoachingChatRequest(BaseModel):
    """One question plus bounded dashboard-local conversation context."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2_000)
    conversation: tuple[ConversationTurn, ...] = Field(default=(), max_length=8)


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


def _validate_upload_metadata(filename: str, title: str) -> tuple[str, str, str]:
    safe_filename = filename.strip()
    normalized_title = title.strip()
    lowered_filename = safe_filename.casefold()

    if (
        not safe_filename
        or safe_filename in {".", ".."}
        or "/" in safe_filename
        or "\\" in safe_filename
    ):
        raise RunUploadValidationError("Filename must be one safe basename.")
    if len(safe_filename) > 255:
        raise RunUploadValidationError("Filename must contain at most 255 characters.")
    if lowered_filename.endswith(".fit.gz"):
        suffix = ".fit.gz"
    elif lowered_filename.endswith(".fit"):
        suffix = ".fit"
    else:
        raise RunUploadValidationError("Only .fit and .fit.gz activity files are accepted.")
    if not normalized_title:
        raise RunUploadValidationError("Activity title cannot be blank.")
    if len(normalized_title) > 160:
        raise RunUploadValidationError("Activity title must contain at most 160 characters.")
    if any(ord(character) < 32 for character in normalized_title):
        raise RunUploadValidationError("Activity title contains unsupported control characters.")
    return safe_filename, normalized_title, suffix


async def _write_upload(request: Request, destination: Path) -> int:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_RUN_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Run upload exceeds the 25 MiB limit.",
                )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must be a valid integer.",
            ) from error

    size_bytes = 0
    with destination.open("wb") as stream:
        async for chunk in request.stream():
            size_bytes += len(chunk)
            if size_bytes > MAX_RUN_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Run upload exceeds the 25 MiB limit.",
                )
            stream.write(chunk)
    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Run upload cannot be empty.",
        )
    return size_bytes


def _uploaded_activity_response(
    prepared: PreparedRunUpload,
    athlete_timezone: ZoneInfo,
) -> RunUploadActivityResponse:
    activity = prepared.activity
    return RunUploadActivityResponse(
        title=activity.name or "Untitled run",
        local_date=activity.start_time_utc.astimezone(athlete_timezone).date(),
        distance_km=(None if activity.distance_m is None else activity.distance_m / 1_000),
        elapsed_time_seconds=activity.elapsed_time_s,
        laps=len(activity.laps),
        trackpoints=len(activity.trackpoints),
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


@router.get("/plans/active/tracking", response_model=ActivePlanTrackingResponse)
def active_training_plan_tracking(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    as_of_date: Annotated[
        date | None,
        Query(description="Optional deterministic evaluation date in YYYY-MM-DD format."),
    ] = None,
) -> ActivePlanTrackingResponse:
    """Return actual weekly training against the active plan and its version history."""

    try:
        tracking = TrainingPlanTrackingService(database_session).overview(
            athlete_id=_configured_athlete_id(settings),
            as_of_date=as_of_date,
        )
    except TrainingPlanTrackingError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ActivePlanTrackingResponse.model_validate(tracking)


@router.post("/chat", response_model=CoachingReply)
def coaching_chat(
    body: CoachingChatRequest,
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
) -> CoachingReply:
    """Answer from minimized deterministic evidence, with optional OpenAI interpretation."""

    try:
        return build_conversational_coach(database_session, settings).answer(
            athlete_id=_configured_athlete_id(settings),
            question=body.message,
            conversation=body.conversation,
        )
    except CoachingChatError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post("/runs", response_model=RunUploadResponse)
async def upload_strava_run(
    request: Request,
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
    filename: Annotated[
        str,
        Header(
            alias="X-RunCoach-Filename",
            min_length=1,
            max_length=1_024,
            description="Percent-encoded original FIT filename.",
        ),
    ],
    title: Annotated[
        str,
        Header(
            alias="X-RunCoach-Title",
            min_length=1,
            max_length=1_024,
            description="Percent-encoded athlete-authored run title.",
        ),
    ],
) -> RunUploadResponse:
    """Import one private Strava FIT run and return refreshed coaching advice."""

    try:
        safe_filename, normalized_title, suffix = _validate_upload_metadata(
            unquote(filename),
            unquote(title),
        )
    except RunUploadValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    athlete_id = _configured_athlete_id(settings)
    athlete = database_session.get(Athlete, athlete_id)
    if athlete is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The configured athlete does not exist. Import summaries first.",
        )
    athlete_timezone = ZoneInfo(athlete.timezone)

    settings.private_data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(
            prefix="runcoach-upload-",
            dir=settings.private_data_dir,
        ) as temporary_directory:
            staged_path = Path(temporary_directory) / f"activity{suffix}"
            size_bytes = await _write_upload(request, staged_path)
            prepared = prepare_strava_fit_upload(
                path=staged_path,
                filename=safe_filename,
                title=normalized_title,
                size_bytes=size_bytes,
                athlete_id=athlete_id,
                athlete_timezone=athlete_timezone,
            )
    except RunUploadValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    known_hashes = known_strava_hashes(database_session, athlete_id)
    inputs = () if prepared.activity.source.content_sha256 in known_hashes else (prepared.input,)
    try:
        pipeline = update_coaching_from_inputs(
            session=database_session,
            athlete_id=athlete_id,
            inputs=inputs,
        )
    except (
        AnalyticsPersistenceError,
        SensorPersistenceError,
        TrainingPlanPersistenceError,
        TrainingPlanQueryError,
        TrainingPlanTrackingError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    return RunUploadResponse(
        status="duplicate" if not inputs else "updated",
        activity=_uploaded_activity_response(prepared, athlete_timezone),
        parser_findings=prepared.parser_findings,
        import_summary=(
            None
            if pipeline.sensor_import is None
            else SensorImportSummaryResponse.model_validate(pipeline.sensor_import)
        ),
        analytics=AnalyticsRefreshResponse.model_validate(pipeline.analytics),
        plan_refresh=PlanRefreshResponse(
            status=pipeline.plan_refresh_status,
            new_version_created=pipeline.plan_version_created,
        ),
        tracking=ActivePlanTrackingResponse.model_validate(pipeline.tracking),
    )
