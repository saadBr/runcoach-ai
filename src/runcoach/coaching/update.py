"""Shared orchestration for importing runs and refreshing coaching evidence."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from runcoach import __version__
from runcoach.db.analytics import (
    AnalyticsCalculationSummary,
    DeterministicAnalyticsService,
)
from runcoach.db.models import Activity, Athlete, ImportBatch, ImportFile
from runcoach.db.sensors import (
    PersistedSensorImportSummary,
    SensorActivityInput,
    SensorPersistenceService,
)
from runcoach.db.training_plan_tracking import (
    ActivePlanTracking,
    TrainingPlanTrackingService,
)
from runcoach.db.training_plans import TrainingPlanPersistenceService

type PlanRefreshStatus = Literal["deferred_active_week", "refreshed"]


@dataclass(frozen=True, slots=True)
class CoachingPipelineResult:
    """Result of persisting new evidence and refreshing derived coaching state."""

    sensor_import: PersistedSensorImportSummary | None
    analytics: AnalyticsCalculationSummary
    plan_refresh_status: PlanRefreshStatus
    plan_version_created: bool
    previous_tracking: ActivePlanTracking | None
    tracking: ActivePlanTracking


def known_strava_hashes(session: Session, athlete_id: UUID) -> frozenset[str]:
    """Return normalized content hashes already imported for one athlete."""

    return frozenset(
        session.scalars(
            select(ImportFile.sha256)
            .join(ImportBatch, ImportFile.import_batch_id == ImportBatch.id)
            .where(
                ImportBatch.athlete_id == athlete_id,
                ImportFile.source_provider == "strava",
            )
        )
    )


def latest_running_date(session: Session, athlete_id: UUID) -> date | None:
    """Return the latest eligible athlete-local running date."""

    return session.scalar(
        select(func.max(Activity.local_start_date)).where(
            Activity.athlete_id == athlete_id,
            Activity.sport == "running",
            Activity.verification_status != "excluded",
        )
    )


def should_refresh_plan(tracking: ActivePlanTracking) -> bool:
    """Refresh only after the final dated session in the stable detailed week."""

    expected_start = (
        tracking.as_of_date + timedelta(days=1)
        if tracking.as_of_date.weekday() == 6
        else tracking.as_of_date - timedelta(days=tracking.as_of_date.weekday())
    )
    if tracking.plan_start_date > expected_start:
        return True
    final_session_date = max(session.scheduled_date for session in tracking.sessions)
    return tracking.status == "completed" or tracking.as_of_date >= final_session_date


def update_coaching_from_inputs(
    *,
    session: Session,
    athlete_id: UUID,
    inputs: tuple[SensorActivityInput, ...],
) -> CoachingPipelineResult:
    """Persist optional run inputs and refresh all deterministic coaching outputs."""

    if session.get(Athlete, athlete_id) is None:
        raise ValueError("The configured athlete does not exist. Import summaries first.")
    session.rollback()

    sensor_import: PersistedSensorImportSummary | None = None
    if inputs:
        sensor_import = SensorPersistenceService(session).persist(
            athlete_id=athlete_id,
            parser_bundle_version=f"runcoach-{__version__}",
            inputs=inputs,
            create_missing_strava_activities=True,
        )

    latest_date = latest_running_date(session, athlete_id)
    session.rollback()
    if latest_date is None:
        raise ValueError("No eligible canonical running activities are available.")

    analytics = DeterministicAnalyticsService(session).calculate(
        athlete_id=athlete_id,
        as_of_date=latest_date,
    )
    prior_tracking = TrainingPlanTrackingService(session).overview(
        athlete_id=athlete_id,
        as_of_date=latest_date,
    )

    if not should_refresh_plan(prior_tracking):
        return CoachingPipelineResult(
            sensor_import=sensor_import,
            analytics=analytics,
            plan_refresh_status="deferred_active_week",
            plan_version_created=False,
            previous_tracking=None,
            tracking=prior_tracking,
        )

    session.rollback()
    persisted_plan = TrainingPlanPersistenceService(session).refresh_active(athlete_id=athlete_id)
    current_tracking = TrainingPlanTrackingService(session).overview(
        athlete_id=athlete_id,
        as_of_date=latest_date,
    )
    return CoachingPipelineResult(
        sensor_import=sensor_import,
        analytics=analytics,
        plan_refresh_status="refreshed",
        plan_version_created=persisted_plan.created,
        previous_tracking=prior_tracking,
        tracking=current_tracking,
    )
