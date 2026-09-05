"""Read-only orchestration for personalized experimental goal assessments."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import DURATION_LOAD_METHOD
from runcoach.analytics.goal_assessment import (
    GOAL_ASSESSMENT_VERSION,
    TRAINING_WINDOW_DAYS,
    GoalAssessment,
    TrainingBlock,
    assess_goal,
)
from runcoach.analytics.performance import StandardDistance, match_standard_distance
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.models import Activity, Athlete, DailyLoad, PersonalBest
from runcoach.db.performance_audit import (
    PerformanceAuditQueryService,
    PerformanceTrainingRow,
)


class GoalAssessmentQueryError(RuntimeError):
    """Raised when stored evidence cannot support a goal assessment."""


@dataclass(frozen=True, slots=True)
class GoalAssessmentReport:
    """All available standard-distance assessments at one evidence cutoff."""

    as_of_date: date
    data_through_date: date
    algorithm_version: str
    method_status: str
    assessments: tuple[GoalAssessment, ...]
    unavailable_distances: tuple[StandardDistance, ...]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _current_training_block(
    *,
    activities: tuple[Activity, ...],
    as_of_date: date,
    form_index: Decimal | None,
) -> TrainingBlock:
    window_start = as_of_date - timedelta(days=TRAINING_WINDOW_DAYS - 1)
    window = tuple(
        activity
        for activity in activities
        if window_start <= activity.local_start_date <= as_of_date
    )
    distance_m = sum(float(activity.distance_m) for activity in window)
    moving_time_ms = sum(activity.moving_time_ms for activity in window)
    return TrainingBlock(
        end_date=as_of_date,
        runs=len(window),
        distance_km=round(distance_m / 1_000, 6),
        moving_hours=round(moving_time_ms / 3_600_000, 6),
        longest_run_km=(
            round(max(float(activity.distance_m) for activity in window) / 1_000, 6)
            if window
            else None
        ),
        form_index=float(form_index) if form_index is not None else None,
        last_run_date=max((activity.local_start_date for activity in window), default=None),
    )


def _reference_training_block(row: PerformanceTrainingRow) -> TrainingBlock | None:
    window = next(
        (window for window in row.training_windows if window.days == TRAINING_WINDOW_DAYS),
        None,
    )
    if window is None:
        return None
    return TrainingBlock(
        end_date=row.achieved_at.date() - timedelta(days=1),
        runs=window.runs,
        distance_km=window.distance_km,
        moving_hours=window.moving_hours,
        longest_run_km=window.longest_run_km,
        form_index=row.prior_form_index,
        last_run_date=None,
    )


def _distance_for_pb(record: PersonalBest) -> StandardDistance:
    match = match_standard_distance(float(record.distance_m), tolerance_pct=0.01)
    if match is None:
        raise GoalAssessmentQueryError(
            "An active personal best uses an unsupported standard distance."
        )
    return match.distance


class GoalAssessmentQueryService:
    """Build same-distance assessments from canonical training and verified PBs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def assess(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date | None = None,
    ) -> GoalAssessmentReport:
        """Return experimental ranges without changing stored analytics or labels."""

        if self._session.get(Athlete, athlete_id) is None:
            raise GoalAssessmentQueryError("The configured athlete does not exist.")

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.sport == "running",
                    Activity.verification_status != "excluded",
                )
                .order_by(Activity.start_time_utc, Activity.id)
            )
        )
        if not activities:
            raise GoalAssessmentQueryError("No eligible running activities are available.")

        latest_workload = self._session.scalar(
            select(DailyLoad)
            .where(
                DailyLoad.athlete_id == athlete_id,
                DailyLoad.load_method == DURATION_LOAD_METHOD,
                DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
                *((DailyLoad.local_date <= as_of_date,) if as_of_date is not None else ()),
            )
            .order_by(DailyLoad.local_date.desc(), DailyLoad.id.desc())
        )
        effective_date = as_of_date
        if effective_date is None:
            effective_date = (
                latest_workload.local_date
                if latest_workload is not None
                else max(activity.local_start_date for activity in activities)
            )

        eligible_activities = tuple(
            activity for activity in activities if activity.local_start_date <= effective_date
        )
        if not eligible_activities:
            raise GoalAssessmentQueryError("No running activities exist by the requested date.")
        data_through_date = max(activity.local_start_date for activity in eligible_activities)

        if latest_workload is None or latest_workload.local_date > effective_date:
            latest_workload = self._session.scalar(
                select(DailyLoad)
                .where(
                    DailyLoad.athlete_id == athlete_id,
                    DailyLoad.load_method == DURATION_LOAD_METHOD,
                    DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
                    DailyLoad.local_date <= effective_date,
                )
                .order_by(DailyLoad.local_date.desc(), DailyLoad.id.desc())
            )

        current_block = _current_training_block(
            activities=eligible_activities,
            as_of_date=effective_date,
            form_index=latest_workload.form_index if latest_workload is not None else None,
        )
        dataset = PerformanceAuditQueryService(self._session).training_dataset(
            athlete_id=athlete_id
        )
        rows_by_activity = {
            row.activity_id: row for row in dataset.rows if row.review_status == "verified"
        }

        end_of_day = datetime.combine(effective_date, time.max, tzinfo=UTC)
        personal_bests = tuple(
            self._session.scalars(
                select(PersonalBest)
                .where(
                    PersonalBest.athlete_id == athlete_id,
                    PersonalBest.superseded_at.is_(None),
                )
                .order_by(PersonalBest.distance_m, PersonalBest.achieved_at)
            )
        )
        current_by_distance: dict[StandardDistance, PersonalBest] = {}
        for record in personal_bests:
            if _as_utc(record.achieved_at) > end_of_day:
                continue
            distance = _distance_for_pb(record)
            if distance in current_by_distance:
                raise GoalAssessmentQueryError(
                    f"Multiple active personal bests exist for {distance.value}."
                )
            current_by_distance[distance] = record

        assessments: list[GoalAssessment] = []
        unavailable: list[StandardDistance] = []
        for distance in StandardDistance:
            selected_record = current_by_distance.get(distance)
            if selected_record is None:
                unavailable.append(distance)
                continue
            row = rows_by_activity.get(selected_record.activity_id)
            reference_block = _reference_training_block(row) if row is not None else None
            if reference_block is None:
                unavailable.append(distance)
                continue
            assessments.append(
                assess_goal(
                    distance=distance,
                    reference_pb_seconds=selected_record.elapsed_time_ms / 1_000,
                    reference_pb_date=_as_utc(selected_record.achieved_at).date(),
                    current_block=current_block,
                    reference_block=reference_block,
                )
            )

        if not assessments:
            raise GoalAssessmentQueryError(
                "No verified PB has the required pre-event training evidence."
            )

        return GoalAssessmentReport(
            as_of_date=effective_date,
            data_through_date=data_through_date,
            algorithm_version=GOAL_ASSESSMENT_VERSION,
            method_status="experimental_not_validated",
            assessments=tuple(assessments),
            unavailable_distances=tuple(unavailable),
        )
