"""Import new Strava runs and update analytics, plan state, and coaching advice."""

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from runcoach.cli.import_strava_activities import (
    CollectionStatistics,
    _collect_inputs,
)
from runcoach.coaching.update import (
    CoachingPipelineResult,
    known_strava_hashes,
    should_refresh_plan,
    update_coaching_from_inputs,
)
from runcoach.config import get_settings
from runcoach.db.analytics import AnalyticsCalculationSummary
from runcoach.db.models import Athlete
from runcoach.db.sensors import PersistedSensorImportSummary
from runcoach.db.session import SessionFactory
from runcoach.db.training_plan_tracking import ActivePlanTracking

type PlanRefreshStatus = Literal["deferred_active_week", "refreshed"]


@dataclass(frozen=True, slots=True)
class CoachingUpdateResult:
    """Aggregate result of one end-to-end coaching-data update."""

    collection: CollectionStatistics
    sensor_import: PersistedSensorImportSummary | None
    analytics: AnalyticsCalculationSummary
    plan_refresh_status: PlanRefreshStatus
    plan_version_created: bool
    previous_tracking: ActivePlanTracking | None
    tracking: ActivePlanTracking


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import unseen Strava FIT runs, recalculate deterministic analytics, "
            "roll the active plan forward when its detailed week ends, and print "
            "the current coaching recommendation."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--activity-dir",
        type=Path,
        help=(
            "Directory containing Strava FIT downloads; defaults to "
            "data/private/strava/extracted/activities."
        ),
    )
    parser.add_argument(
        "--since",
        type=_iso_date,
        help=(
            "Optional earliest athlete-local activity date. Existing file hashes are "
            "skipped before parsing, so this is normally unnecessary."
        ),
    )
    return parser


def _known_strava_hashes(session: Session, athlete_id: UUID) -> frozenset[str]:
    return known_strava_hashes(session, athlete_id)


def _latest_running_date(session: Session, athlete_id: UUID) -> date | None:
    from runcoach.coaching.update import latest_running_date

    return latest_running_date(session, athlete_id)


def _should_refresh_plan(tracking: ActivePlanTracking) -> bool:
    return should_refresh_plan(tracking)


def run_coaching_update(
    *,
    session: Session,
    athlete_id: UUID,
    activity_dir: Path,
    since: date | None,
) -> CoachingUpdateResult:
    """Run the complete update pipeline while preserving the active weekly schedule."""

    athlete = session.get(Athlete, athlete_id)
    if athlete is None:
        raise ValueError("The configured athlete does not exist. Import summaries first.")
    athlete_timezone = ZoneInfo(athlete.timezone)
    known_hashes = _known_strava_hashes(session, athlete_id)
    session.rollback()

    inputs, collection = _collect_inputs(
        activity_dir=activity_dir,
        athlete_id=athlete_id,
        athlete_timezone=athlete_timezone,
        since=since or date.min,
        known_content_sha256=known_hashes,
        skip_unseen_bulk_export_files=True,
    )
    pipeline: CoachingPipelineResult = update_coaching_from_inputs(
        session=session,
        athlete_id=athlete_id,
        inputs=inputs,
    )
    return CoachingUpdateResult(
        collection=collection,
        sensor_import=pipeline.sensor_import,
        analytics=pipeline.analytics,
        plan_refresh_status=pipeline.plan_refresh_status,
        plan_version_created=pipeline.plan_version_created,
        previous_tracking=pipeline.previous_tracking,
        tracking=pipeline.tracking,
    )


def _session_output(tracking: ActivePlanTracking) -> list[dict[str, Any]]:
    return [
        {
            "scheduled_date": session.scheduled_date.isoformat(),
            "kind": session.kind,
            "title": session.title,
            "target_distance_km": session.target_distance_km,
            "status": session.status,
            "matched_activity_date": (
                session.matched_activity_date.isoformat()
                if session.matched_activity_date is not None
                else None
            ),
            "matched_activity_name": session.matched_activity_name,
            "actual_distance_km": session.actual_distance_km,
            "distance_completion_pct": session.distance_completion_pct,
            "pace_status": session.pace_status,
        }
        for session in tracking.sessions
    ]


def _tracking_output(tracking: ActivePlanTracking) -> dict[str, Any]:
    return {
        "as_of_date": tracking.as_of_date.isoformat(),
        "race_date": tracking.race_date.isoformat(),
        "status": tracking.status,
        "active_version": tracking.active_version,
        "current_week_number": tracking.current_week_number,
        "planned_distance_to_date_km": tracking.planned_distance_to_date_km,
        "actual_distance_to_date_km": tracking.actual_distance_to_date_km,
        "adherence_pct": tracking.adherence_pct,
        "recommendation_code": tracking.recommendation_code,
        "recommendation": tracking.recommendation,
        "sessions": _session_output(tracking),
    }


def _result_output(result: CoachingUpdateResult) -> dict[str, Any]:
    previous_recommendation = (
        None
        if result.previous_tracking is None
        else {
            "code": result.previous_tracking.recommendation_code,
            "message": result.previous_tracking.recommendation,
        }
    )
    return {
        "collection": asdict(result.collection),
        "import": {
            "status": "updated" if result.sensor_import is not None else "no_new_files",
            "summary": (asdict(result.sensor_import) if result.sensor_import is not None else None),
        },
        "analytics": asdict(result.analytics),
        "plan_refresh": {
            "status": result.plan_refresh_status,
            "new_version_created": result.plan_version_created,
            "previous_recommendation": previous_recommendation,
        },
        "tracking": _tracking_output(result.tracking),
    }


def main(arguments: list[str] | None = None) -> int:
    """Run the coaching update and emit one sanitized JSON result."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id
    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    activity_dir = parsed.activity_dir or (
        settings.private_data_dir / "strava" / "extracted" / "activities"
    )
    if not activity_dir.is_dir():
        parser.error("--activity-dir must be an existing directory.")

    with SessionFactory() as session:
        try:
            result = run_coaching_update(
                session=session,
                athlete_id=athlete_id,
                activity_dir=activity_dir,
                since=parsed.since,
            )
        except ValueError as error:
            parser.error(str(error))

    print(json.dumps(_result_output(result), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
