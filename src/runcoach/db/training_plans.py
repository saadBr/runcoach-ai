"""Query and persistence services for versioned athlete training plans."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
    PlannedWeek,
    PlanPhase,
    TrainingGoal,
    TrainingPlanPreview,
    build_training_plan_preview,
)
from runcoach.db.models import Athlete, Goal, TrainingPlan
from runcoach.db.performance_queries import (
    PerformanceQueryError,
    PerformanceQueryService,
)

type PlanPayload = dict[str, Any]


class TrainingPlanQueryError(RuntimeError):
    """Raised when available evidence cannot support a requested plan."""


class TrainingPlanPersistenceError(RuntimeError):
    """Raised when a generated plan cannot be persisted atomically."""


@dataclass(frozen=True, slots=True)
class PersistedTrainingPlan:
    """Identity and payload for one active plan version."""

    goal_id: UUID
    plan_id: UUID
    version: int
    created: bool
    preview: PlanPayload


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"Unsupported plan value: {type(value).__name__}.")


def _serialize_preview(preview: TrainingPlanPreview) -> tuple[PlanPayload, str]:
    encoded = json.dumps(
        asdict(preview),
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = cast(PlanPayload, json.loads(encoded))
    return payload, sha256(encoded.encode("utf-8")).hexdigest()


def _stored_result(
    *,
    goal: Goal,
    plan: TrainingPlan,
    created: bool,
) -> PersistedTrainingPlan:
    return PersistedTrainingPlan(
        goal_id=goal.id,
        plan_id=plan.id,
        version=plan.version,
        created=created,
        preview=plan.plan_payload,
    )


def _retain_completed_weeks(
    preview: TrainingPlanPreview,
    previous_payload: PlanPayload,
) -> TrainingPlanPreview:
    """Keep completed weekly targets fixed while adapting the remaining outline."""

    previous_weeks = previous_payload.get("weekly_outline")
    if not isinstance(previous_weeks, list) or len(previous_weeks) != len(preview.weekly_outline):
        raise TrainingPlanQueryError("Active plan has an invalid weekly outline.")

    detailed_start = next(
        week.start_date
        for week in preview.weekly_outline
        if week.start_date <= preview.first_week[0].scheduled_date <= week.end_date
    )
    revised_weeks = list(preview.weekly_outline)
    for index, generated in enumerate(revised_weeks):
        if generated.end_date >= detailed_start:
            break
        stored = previous_weeks[index]
        if not isinstance(stored, dict):
            raise TrainingPlanQueryError("Active plan has an invalid completed week.")
        try:
            previous = PlannedWeek(
                week_number=int(stored["week_number"]),
                start_date=date.fromisoformat(stored["start_date"]),
                end_date=date.fromisoformat(stored["end_date"]),
                phase=PlanPhase(stored["phase"]),
                target_distance_km=float(stored["target_distance_km"]),
                long_run_km=float(stored["long_run_km"]),
                quality_focus=str(stored["quality_focus"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TrainingPlanQueryError("Active plan has an invalid completed week.") from error
        if (
            previous.week_number != generated.week_number
            or previous.start_date != generated.start_date
            or previous.end_date != generated.end_date
        ):
            raise TrainingPlanQueryError("Active plan calendar changed unexpectedly.")
        revised_weeks[index] = previous
    return replace(preview, weekly_outline=tuple(revised_weeks))


class TrainingPlanQueryService:
    """Combine current-fitness evidence with a user-selected race goal."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def preview(
        self,
        *,
        athlete_id: UUID,
        distance: StandardDistance,
        race_date: date,
        target_time_seconds: float | None,
        days_per_week: int,
        plan_start_date: date | None = None,
    ) -> TrainingPlanPreview:
        """Return a deterministic preview without persisting a goal or plan."""

        try:
            performance = PerformanceQueryService(self._session).overview(athlete_id=athlete_id)
            return build_training_plan_preview(
                goal=TrainingGoal(
                    distance=distance,
                    race_date=race_date,
                    target_time_seconds=target_time_seconds,
                    days_per_week=days_per_week,
                ),
                fitness=performance.current_fitness,
                plan_start_date=plan_start_date,
            )
        except (PerformanceQueryError, ValueError) as error:
            raise TrainingPlanQueryError(str(error)) from error


class TrainingPlanPersistenceService:
    """Create, reuse, and refresh the athlete's active versioned plan."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_refresh(
        self,
        *,
        athlete_id: UUID,
        distance: StandardDistance,
        race_date: date,
        target_time_seconds: float | None,
        days_per_week: int,
    ) -> PersistedTrainingPlan:
        """Generate and atomically activate a plan for the selected goal."""

        try:
            with self._session.begin():
                preview = TrainingPlanQueryService(self._session).preview(
                    athlete_id=athlete_id,
                    distance=distance,
                    race_date=race_date,
                    target_time_seconds=target_time_seconds,
                    days_per_week=days_per_week,
                )
                return self._persist_preview(athlete_id=athlete_id, preview=preview)
        except (TrainingPlanPersistenceError, TrainingPlanQueryError):
            raise
        except Exception as error:
            raise TrainingPlanPersistenceError(
                "Training-plan persistence failed and was rolled back."
            ) from error

    def load_active(self, *, athlete_id: UUID) -> PersistedTrainingPlan:
        """Load the current primary goal and its active generated plan."""

        row = self._session.execute(
            select(Goal, TrainingPlan)
            .join(TrainingPlan, TrainingPlan.goal_id == Goal.id)
            .where(
                Goal.athlete_id == athlete_id,
                Goal.status == "active",
                Goal.priority == "primary",
                TrainingPlan.status == "active",
            )
            .order_by(TrainingPlan.version.desc())
        ).first()
        if row is None:
            raise TrainingPlanQueryError("No active persisted training plan exists.")
        goal, plan = row._tuple()
        return _stored_result(goal=goal, plan=plan, created=False)

    def refresh_active(self, *, athlete_id: UUID) -> PersistedTrainingPlan:
        """Regenerate the active goal against the latest training evidence."""

        try:
            with self._session.begin():
                row = self._session.execute(
                    select(Goal, TrainingPlan)
                    .join(TrainingPlan, TrainingPlan.goal_id == Goal.id)
                    .where(
                        Goal.athlete_id == athlete_id,
                        Goal.status == "active",
                        Goal.priority == "primary",
                        TrainingPlan.status == "active",
                    )
                    .order_by(TrainingPlan.version.desc())
                ).first()
                if row is None:
                    raise TrainingPlanQueryError("No active persisted training plan exists.")
                goal, active_plan = row._tuple()
                stored_start = active_plan.plan_payload.get("plan_start_date")
                if not isinstance(stored_start, str):
                    raise TrainingPlanQueryError("Active plan is missing its start date.")
                try:
                    preserved_start = date.fromisoformat(stored_start)
                except ValueError as error:
                    raise TrainingPlanQueryError(
                        "Active plan has an invalid start date."
                    ) from error
                preview = TrainingPlanQueryService(self._session).preview(
                    athlete_id=athlete_id,
                    distance=StandardDistance(goal.race_type),
                    race_date=goal.race_date,
                    target_time_seconds=(
                        float(goal.target_time_seconds)
                        if goal.target_time_seconds is not None
                        else None
                    ),
                    days_per_week=goal.days_per_week,
                    plan_start_date=preserved_start,
                )
                preview = _retain_completed_weeks(preview, active_plan.plan_payload)
                return self._persist_preview(
                    athlete_id=athlete_id,
                    preview=preview,
                    existing_goal=goal,
                )
        except (TrainingPlanPersistenceError, TrainingPlanQueryError):
            raise
        except Exception as error:
            raise TrainingPlanPersistenceError(
                "Training-plan refresh failed and was rolled back."
            ) from error

    def _persist_preview(
        self,
        *,
        athlete_id: UUID,
        preview: TrainingPlanPreview,
        existing_goal: Goal | None = None,
    ) -> PersistedTrainingPlan:
        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise TrainingPlanPersistenceError(
                "The athlete must exist before creating a training plan."
            )

        goal = existing_goal or self._session.scalar(
            select(Goal).where(
                Goal.athlete_id == athlete_id,
                Goal.race_type == preview.goal.distance.value,
                Goal.race_date == preview.goal.race_date,
            )
        )
        if goal is None:
            goal = Goal(
                athlete_id=athlete_id,
                race_type=preview.goal.distance.value,
                race_date=preview.goal.race_date,
                target_time_seconds=None,
                days_per_week=preview.goal.days_per_week,
                status="active",
                priority="primary",
            )
            self._session.add(goal)
            self._session.flush()

        now = datetime.now(UTC)
        for other_goal in self._session.scalars(
            select(Goal).where(
                Goal.athlete_id == athlete_id,
                Goal.status == "active",
                Goal.priority == "primary",
                Goal.id != goal.id,
            )
        ):
            other_goal.status = "planned"
            for other_plan in self._session.scalars(
                select(TrainingPlan).where(
                    TrainingPlan.goal_id == other_goal.id,
                    TrainingPlan.status == "active",
                )
            ):
                other_plan.status = "superseded"
                other_plan.superseded_at = now

        goal.target_time_seconds = (
            round(preview.goal.target_time_seconds)
            if preview.goal.target_time_seconds is not None
            else None
        )
        goal.days_per_week = preview.goal.days_per_week
        goal.status = "active"
        goal.priority = "primary"

        payload, evidence_hash = _serialize_preview(preview)
        current = self._session.scalar(
            select(TrainingPlan).where(
                TrainingPlan.goal_id == goal.id,
                TrainingPlan.status == "active",
            )
        )
        matching = self._session.scalar(
            select(TrainingPlan).where(
                TrainingPlan.goal_id == goal.id,
                TrainingPlan.evidence_hash == evidence_hash,
            )
        )
        if matching is not None:
            if current is not None and current.id != matching.id:
                current.status = "superseded"
                current.superseded_at = now
            matching.status = "active"
            matching.superseded_at = None
            return _stored_result(goal=goal, plan=matching, created=False)

        if current is not None:
            current.status = "superseded"
            current.superseded_at = now

        maximum_version = self._session.scalar(
            select(func.max(TrainingPlan.version)).where(TrainingPlan.goal_id == goal.id)
        )
        plan = TrainingPlan(
            goal_id=goal.id,
            version=(maximum_version or 0) + 1,
            algorithm_version=preview.algorithm_version,
            evidence_as_of_date=preview.as_of_date,
            evidence_hash=evidence_hash,
            status="active",
            plan_payload=payload,
            superseded_at=None,
        )
        self._session.add(plan)
        self._session.flush()
        return _stored_result(goal=goal, plan=plan, created=True)
