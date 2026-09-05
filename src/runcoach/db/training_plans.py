"""Query and persistence services for versioned athlete training plans."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from runcoach.analytics.performance import StandardDistance
from runcoach.analytics.training_plan import (
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
                goal = self._session.scalar(
                    select(Goal).where(
                        Goal.athlete_id == athlete_id,
                        Goal.status == "active",
                        Goal.priority == "primary",
                    )
                )
                if goal is None:
                    raise TrainingPlanQueryError("No active persisted training plan exists.")
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
                )
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
