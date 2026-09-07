"""Read-only adherence and revision history for persisted training plans."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from runcoach.analytics.session_classification import (
    SessionClassification,
    SessionKind,
    classify_session,
)
from runcoach.db.models import Activity, DailyLoad, Goal, TrainingPlan


class TrainingPlanTrackingError(RuntimeError):
    """Raised when an active plan cannot be evaluated safely."""


MINIMUM_OVER_TARGET_DISTANCE_KM = 5.0


@dataclass(frozen=True, slots=True)
class PlanWeekProgress:
    """Actual running completed against one planned calendar week."""

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


@dataclass(frozen=True, slots=True)
class PlanSessionProgress:
    """One prescribed first-week session matched to canonical activity evidence."""

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


@dataclass(frozen=True, slots=True)
class PlanVersionSummary:
    """A compact, auditable summary of one generated plan version."""

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


@dataclass(frozen=True, slots=True)
class ActivePlanTracking:
    """Plan-to-actual progress plus immutable plan revision history."""

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
    weeks: tuple[PlanWeekProgress, ...]
    sessions: tuple[PlanSessionProgress, ...]
    recommendation_code: str
    recommendation: str
    versions: tuple[PlanVersionSummary, ...]


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")
    return cast(dict[str, Any], value)


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")
    return cast(list[object], value)


def _date_value(value: object, label: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.") from error
    raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")


def _float_value(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")
    return float(value)


def _int_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")
    return value


def _string_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TrainingPlanTrackingError(f"Stored plan {label} is invalid.")
    return value


def _week_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    weeks = _sequence(payload.get("weekly_outline"), "weekly outline")
    if not weeks:
        raise TrainingPlanTrackingError("Stored plan weekly outline is empty.")
    return [_mapping(week, "week") for week in weeks]


def _session_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sessions = _sequence(payload.get("first_week"), "first-week sessions")
    if not sessions:
        raise TrainingPlanTrackingError("Stored plan first-week sessions are empty.")
    return [_mapping(session, "session") for session in sessions]


def _scheduled_distance_to_date(
    *,
    payload: dict[str, Any],
    as_of_date: date,
) -> float:
    """Return detailed-session distance due through one date."""

    return sum(
        _float_value(session.get("distance_km"), "session distance")
        for session in _session_payloads(payload)
        if _date_value(session.get("scheduled_date"), "session date") <= as_of_date
    )


def _is_kind_compatible(
    *,
    planned_kind: str,
    classification: SessionClassification,
    activity_type: str,
    actual_distance_km: float,
    target_distance_km: float,
) -> bool:
    if planned_kind in {"easy", "recovery"}:
        return classification.has_tag(SessionKind.EASY) or (
            classification.primary_kind is SessionKind.UNCLASSIFIED
            and activity_type in {"easy", "unknown"}
        )
    if planned_kind == "quality":
        return classification.is_quality_session or activity_type == "workout"
    if planned_kind == "long":
        return (
            classification.has_tag(SessionKind.LONG)
            or classification.has_tag(SessionKind.PROGRESSIVE)
            or activity_type == "long"
            or actual_distance_km >= target_distance_km * 0.9
        )
    if planned_kind == "race":
        return classification.has_tag(SessionKind.RACE) or activity_type == "race"
    return False


def _candidate_score(
    *,
    activity: Activity,
    scheduled_date: date,
    planned_kind: str,
    target_distance_km: float,
) -> float:
    actual_distance_km = float(activity.distance_m) / 1_000
    classification = classify_session(activity.name)
    date_score = 100.0 if activity.local_start_date == scheduled_date else 35.0
    kind_score = (
        50.0
        if _is_kind_compatible(
            planned_kind=planned_kind,
            classification=classification,
            activity_type=activity.activity_type,
            actual_distance_km=actual_distance_km,
            target_distance_km=target_distance_km,
        )
        else 0.0
    )
    relative_error = (
        abs(actual_distance_km - target_distance_km) / target_distance_km
        if target_distance_km
        else 0.0
    )
    return date_score + kind_score + max(0.0, 25.0 - relative_error * 25.0)


def _match_first_week_sessions(
    *,
    payload: dict[str, Any],
    activities: list[Activity],
    as_of_date: date,
) -> tuple[PlanSessionProgress, ...]:
    session_payloads = _session_payloads(payload)
    matches: dict[int, Activity] = {}
    used_activity_ids: set[UUID] = set()

    for allow_adjacent_date in (False, True):
        for index, session_payload in enumerate(session_payloads):
            if index in matches:
                continue
            scheduled_date = _date_value(
                session_payload.get("scheduled_date"),
                "session date",
            )
            planned_kind = _string_value(session_payload.get("kind"), "session kind")
            target_distance = _float_value(
                session_payload.get("distance_km"),
                "session distance",
            )
            candidates = [
                activity
                for activity in activities
                if activity.id not in used_activity_ids
                and activity.local_start_date <= as_of_date
                and (
                    abs((activity.local_start_date - scheduled_date).days) <= 1
                    if allow_adjacent_date
                    else activity.local_start_date == scheduled_date
                )
            ]
            if allow_adjacent_date:
                candidates = [
                    activity
                    for activity in candidates
                    if _is_kind_compatible(
                        planned_kind=planned_kind,
                        classification=classify_session(activity.name),
                        activity_type=activity.activity_type,
                        actual_distance_km=float(activity.distance_m) / 1_000,
                        target_distance_km=target_distance,
                    )
                ]
            if not candidates:
                continue
            selected = max(
                candidates,
                key=lambda activity: _candidate_score(
                    activity=activity,
                    scheduled_date=scheduled_date,
                    planned_kind=planned_kind,
                    target_distance_km=target_distance,
                ),
            )
            matches[index] = selected
            used_activity_ids.add(selected.id)

    results: list[PlanSessionProgress] = []
    for index, session_payload in enumerate(session_payloads):
        scheduled_date = _date_value(session_payload.get("scheduled_date"), "session date")
        planned_kind = _string_value(session_payload.get("kind"), "session kind")
        title = _string_value(session_payload.get("title"), "session title")
        target_distance = _float_value(
            session_payload.get("distance_km"),
            "session distance",
        )
        activity = matches.get(index)
        if activity is None:
            if scheduled_date > as_of_date:
                status = "upcoming"
            elif scheduled_date == as_of_date:
                status = "due"
            else:
                status = "missed"
            results.append(
                PlanSessionProgress(
                    scheduled_date=scheduled_date,
                    kind=planned_kind,
                    title=title,
                    target_distance_km=target_distance,
                    status=status,
                    matched_activity_date=None,
                    matched_activity_name=None,
                    actual_distance_km=None,
                    actual_pace_seconds_per_km=None,
                    classified_as=None,
                    distance_completion_pct=None,
                    pace_status="unavailable",
                )
            )
            continue

        actual_distance = float(activity.distance_m) / 1_000
        classification = classify_session(activity.name)
        kind_compatible = _is_kind_compatible(
            planned_kind=planned_kind,
            classification=classification,
            activity_type=activity.activity_type,
            actual_distance_km=actual_distance,
            target_distance_km=target_distance,
        )
        distance_completion = actual_distance / target_distance * 100 if target_distance else 0.0
        if not kind_compatible:
            status = "substituted"
        elif distance_completion < 75:
            status = "partial"
        else:
            status = "completed"

        actual_pace = (
            activity.moving_time_ms / 1_000 / actual_distance if actual_distance > 0 else None
        )
        pace_status = _pace_status(
            planned_kind=planned_kind,
            planned_pace=session_payload.get("pace"),
            actual_pace_seconds_per_km=actual_pace,
        )
        results.append(
            PlanSessionProgress(
                scheduled_date=scheduled_date,
                kind=planned_kind,
                title=title,
                target_distance_km=target_distance,
                status=status,
                matched_activity_date=activity.local_start_date,
                matched_activity_name=activity.name,
                actual_distance_km=round(actual_distance, 3),
                actual_pace_seconds_per_km=(
                    round(actual_pace, 3) if actual_pace is not None else None
                ),
                classified_as=classification.primary_kind.value,
                distance_completion_pct=round(distance_completion, 1),
                pace_status=pace_status,
            )
        )
    return tuple(results)


def _pace_status(
    *,
    planned_kind: str,
    planned_pace: object,
    actual_pace_seconds_per_km: float | None,
) -> str:
    if planned_kind in {"quality", "race"}:
        return "not_applicable"
    if planned_pace is None or actual_pace_seconds_per_km is None:
        return "unavailable"
    pace = _mapping(planned_pace, "session pace")
    faster = _float_value(pace.get("faster_seconds_per_km"), "faster session pace")
    slower = _float_value(pace.get("slower_seconds_per_km"), "slower session pace")
    if actual_pace_seconds_per_km < faster:
        return "faster_than_planned"
    if actual_pace_seconds_per_km > slower:
        return "easier_than_planned"
    return "within_range"


def _coaching_recommendation(
    *,
    plan_status: str,
    sessions: tuple[PlanSessionProgress, ...],
    adherence_pct: float | None,
    planned_distance_to_date_km: float,
    actual_distance_to_date_km: float,
) -> tuple[str, str]:
    critical_kinds = {"quality", "long", "race"}
    missed_critical = next(
        (
            session
            for session in sessions
            if session.status == "missed" and session.kind in critical_kinds
        ),
        None,
    )
    if missed_critical is not None:
        return (
            "avoid_makeup_quality",
            f"The {missed_critical.title.lower()} was missed. Do not stack it onto the next "
            "day; continue with the next scheduled session and preserve recovery.",
        )
    partial_critical = next(
        (
            session
            for session in sessions
            if session.status == "partial" and session.kind in critical_kinds
        ),
        None,
    )
    if partial_critical is not None:
        return (
            "accept_partial_quality",
            f"The {partial_critical.title.lower()} was partially completed. Count the work "
            "already done and do not repeat the unfinished portion on the next day.",
        )
    distance_over_target = actual_distance_to_date_km - planned_distance_to_date_km
    if (
        adherence_pct is not None
        and adherence_pct > 115
        and distance_over_target >= MINIMUM_OVER_TARGET_DISTANCE_KM
    ):
        return (
            "reduce_optional_volume",
            "Completed volume is both more than 15 percent and at least 5 km above the "
            "plan-to-date target. Keep the next hard session unchanged only if recovered, "
            "and trim optional easy volume.",
        )
    next_session = next(
        (session for session in sessions if session.status in {"due", "upcoming"}),
        None,
    )
    if plan_status == "not_started" and next_session is not None:
        return (
            "plan_not_started",
            f"The plan begins with {next_session.target_distance_km:.1f} km of "
            f"{next_session.title.lower()} on {next_session.scheduled_date.isoformat()}.",
        )
    if next_session is not None:
        return (
            "continue_as_planned",
            f"Continue with {next_session.target_distance_km:.1f} km of "
            f"{next_session.title.lower()} on {next_session.scheduled_date.isoformat()}.",
        )
    return (
        "first_week_complete",
        "The detailed first week is complete. Refresh the active plan after recalculating "
        "analytics to generate the next dated schedule.",
    )


def _version_summary(plan: TrainingPlan) -> PlanVersionSummary:
    payload = _mapping(plan.plan_payload, "payload")
    weeks = _week_payloads(payload)
    targets = [_float_value(week.get("target_distance_km"), "weekly distance") for week in weeks]
    long_runs = [_float_value(week.get("long_run_km"), "long-run distance") for week in weeks]
    return PlanVersionSummary(
        plan_id=plan.id,
        version=plan.version,
        status=plan.status,
        evidence_as_of_date=plan.evidence_as_of_date,
        created_at=plan.created_at,
        superseded_at=plan.superseded_at,
        recent_weekly_distance_km=_float_value(
            payload.get("recent_weekly_distance_km"),
            "recent weekly distance",
        ),
        first_week_target_km=targets[0],
        peak_week_target_km=max(targets),
        peak_long_run_km=max(long_runs),
    )


class TrainingPlanTrackingService:
    """Compare canonical runs with the active plan and expose revision history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def overview(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date | None = None,
    ) -> ActivePlanTracking:
        """Return deterministic weekly adherence for the active primary goal."""

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
            raise TrainingPlanTrackingError("No active persisted training plan exists.")

        goal, active_plan = row._tuple()
        payload = _mapping(active_plan.plan_payload, "payload")
        week_payloads = _week_payloads(payload)
        plan_start = _date_value(payload.get("plan_start_date"), "start date")
        final_week_end = _date_value(week_payloads[-1].get("end_date"), "week end date")
        resolved_as_of = as_of_date or self._latest_evidence_date(athlete_id)
        if resolved_as_of is None:
            resolved_as_of = active_plan.evidence_as_of_date

        activity_rows: list[Activity] = []
        if resolved_as_of >= plan_start:
            activity_rows = list(
                self._session.scalars(
                    select(Activity).where(
                        Activity.athlete_id == athlete_id,
                        Activity.sport == "running",
                        Activity.local_start_date >= plan_start,
                        Activity.local_start_date <= min(resolved_as_of, final_week_end),
                    )
                )
            )

        weeks: list[PlanWeekProgress] = []
        planned_to_date = 0.0
        actual_to_date = 0.0
        current_week_number: int | None = None
        completed_weeks = 0

        for week_payload in week_payloads:
            week_number = _int_value(week_payload.get("week_number"), "week number")
            start = _date_value(week_payload.get("start_date"), "week start date")
            end = _date_value(week_payload.get("end_date"), "week end date")
            target_distance = _float_value(
                week_payload.get("target_distance_km"),
                "weekly distance",
            )
            target_long_run = _float_value(
                week_payload.get("long_run_km"),
                "long-run distance",
            )
            matching_distances = [
                float(activity.distance_m) / 1_000
                for activity in activity_rows
                if start <= activity.local_start_date <= end
            ]
            actual_distance = round(sum(matching_distances), 3)
            actual_long_run = round(max(matching_distances, default=0.0), 3)

            if resolved_as_of < start:
                week_status = "upcoming"
                planned_fraction = 0.0
            elif resolved_as_of > end:
                week_status = "completed"
                planned_fraction = 1.0
                completed_weeks += 1
            else:
                week_status = "in_progress"
                current_week_number = week_number
                planned_fraction = min((resolved_as_of - start).days + 1, 7) / 7

            if week_number == 1 and week_status == "in_progress":
                planned_to_date += _scheduled_distance_to_date(
                    payload=payload,
                    as_of_date=resolved_as_of,
                )
            else:
                planned_to_date += target_distance * planned_fraction
            actual_to_date += actual_distance
            weeks.append(
                PlanWeekProgress(
                    week_number=week_number,
                    start_date=start,
                    end_date=end,
                    phase=_string_value(week_payload.get("phase"), "week phase"),
                    status=week_status,
                    target_distance_km=target_distance,
                    target_long_run_km=target_long_run,
                    actual_runs=len(matching_distances),
                    actual_distance_km=actual_distance,
                    actual_long_run_km=actual_long_run,
                    distance_completion_pct=round(
                        actual_distance / target_distance * 100 if target_distance else 0.0,
                        1,
                    ),
                    long_run_completion_pct=round(
                        actual_long_run / target_long_run * 100 if target_long_run else 0.0,
                        1,
                    ),
                )
            )

        if resolved_as_of < plan_start:
            plan_status = "not_started"
        elif resolved_as_of > final_week_end:
            plan_status = "completed"
        else:
            plan_status = "in_progress"

        versions = tuple(
            _version_summary(plan)
            for plan in self._session.scalars(
                select(TrainingPlan)
                .where(TrainingPlan.goal_id == goal.id)
                .order_by(TrainingPlan.version.desc())
            )
        )
        rounded_planned = round(planned_to_date, 3)
        rounded_actual = round(actual_to_date, 3)
        adherence_pct = (
            round(rounded_actual / rounded_planned * 100, 1) if rounded_planned > 0 else None
        )
        sessions = _match_first_week_sessions(
            payload=payload,
            activities=activity_rows,
            as_of_date=resolved_as_of,
        )
        recommendation_code, recommendation = _coaching_recommendation(
            plan_status=plan_status,
            sessions=sessions,
            adherence_pct=adherence_pct,
            planned_distance_to_date_km=rounded_planned,
            actual_distance_to_date_km=rounded_actual,
        )
        return ActivePlanTracking(
            goal_id=goal.id,
            plan_id=active_plan.id,
            active_version=active_plan.version,
            as_of_date=resolved_as_of,
            plan_start_date=plan_start,
            race_date=goal.race_date,
            status=plan_status,
            completed_weeks=completed_weeks,
            total_weeks=len(weeks),
            current_week_number=current_week_number,
            planned_distance_to_date_km=rounded_planned,
            actual_distance_to_date_km=rounded_actual,
            adherence_pct=adherence_pct,
            weeks=tuple(weeks),
            sessions=sessions,
            recommendation_code=recommendation_code,
            recommendation=recommendation,
            versions=versions,
        )

    def _latest_evidence_date(self, athlete_id: UUID) -> date | None:
        latest_load_date = self._session.scalar(
            select(func.max(DailyLoad.local_date)).where(DailyLoad.athlete_id == athlete_id)
        )
        if latest_load_date is not None:
            return latest_load_date
        return self._session.scalar(
            select(func.max(Activity.local_start_date)).where(Activity.athlete_id == athlete_id)
        )
