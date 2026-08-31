"""Read-only weekly training and daily workload trend queries."""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
)
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.analytics_queries import WorkloadSnapshot
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
)


class AnalyticsTrendsQueryError(RuntimeError):
    """Raised when a requested analytics trend is unavailable."""


@dataclass(frozen=True, slots=True)
class WeeklyTrainingSummary:
    """One calendar-week training aggregate."""

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


@dataclass(frozen=True, slots=True)
class AnalyticsTrends:
    """Dashboard-ready weekly and daily trend series."""

    start_date: date
    end_date: date
    requested_weeks: int
    weekly_training: tuple[WeeklyTrainingSummary, ...]
    daily_workload: tuple[WorkloadSnapshot, ...]


def _workload_snapshot(daily_load: DailyLoad) -> WorkloadSnapshot:
    return WorkloadSnapshot(
        local_date=daily_load.local_date,
        load_method=daily_load.load_method,
        algorithm_version=daily_load.algorithm_version,
        daily_load=float(daily_load.daily_load),
        acute_load=(float(daily_load.acute_load) if daily_load.acute_load is not None else None),
        chronic_load=(
            float(daily_load.chronic_load) if daily_load.chronic_load is not None else None
        ),
        fitness_index=(
            float(daily_load.fitness_index) if daily_load.fitness_index is not None else None
        ),
        fatigue_index=(
            float(daily_load.fatigue_index) if daily_load.fatigue_index is not None else None
        ),
        form_index=(float(daily_load.form_index) if daily_load.form_index is not None else None),
        coverage_pct=float(daily_load.coverage_pct),
    )


def _latest_metrics(
    metrics: tuple[ActivityMetric, ...],
) -> dict[UUID, ActivityMetric]:
    latest_by_activity: dict[UUID, ActivityMetric] = {}

    for metric in metrics:
        latest_by_activity.setdefault(metric.activity_id, metric)

    return latest_by_activity


def _edwards_trimp(
    metric: ActivityMetric | None,
) -> float | None:
    if metric is None:
        return None

    value = metric.additional_metrics.get("edwards_trimp")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    return float(value)


def _weekly_summary(
    *,
    week_start: date,
    end_date: date,
    activities: tuple[Activity, ...],
    metrics_by_activity: dict[UUID, ActivityMetric],
) -> WeeklyTrainingSummary:
    week_end = min(
        week_start + timedelta(days=6),
        end_date,
    )
    selected = tuple(
        activity for activity in activities if week_start <= activity.local_start_date <= week_end
    )

    total_distance_m = sum(float(activity.distance_m) for activity in selected)
    total_moving_time_ms = sum(activity.moving_time_ms for activity in selected)
    effective_duration_ms = sum(
        (activity.moving_time_ms if activity.moving_time_ms > 0 else activity.elapsed_time_ms)
        for activity in selected
    )
    elevation_values = tuple(
        float(activity.elevation_gain_m)
        for activity in selected
        if activity.elevation_gain_m is not None
    )
    trimp_values = tuple(
        value
        for activity in selected
        if (value := _edwards_trimp(metrics_by_activity.get(activity.id))) is not None
    )

    weighted_pace = (
        round(total_moving_time_ms / total_distance_m, 3)
        if total_distance_m > 0 and total_moving_time_ms > 0
        else None
    )

    return WeeklyTrainingSummary(
        week_start=week_start,
        week_end=week_end,
        runs=len(selected),
        distance_km=round(total_distance_m / 1_000, 3),
        moving_hours=round(
            total_moving_time_ms / 3_600_000,
            3,
        ),
        duration_load_minutes=round(
            effective_duration_ms / 60_000,
            3,
        ),
        weighted_pace_seconds_per_km=weighted_pace,
        elevation_gain_m=(round(sum(elevation_values), 3) if elevation_values else None),
        heart_rate_load_activities=len(trimp_values),
        edwards_trimp=(round(sum(trimp_values), 3) if trimp_values else None),
    )


class AnalyticsTrendsQueryService:
    """Read weekly training and daily workload trend series."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def trends(
        self,
        *,
        athlete_id: UUID,
        weeks: int = 12,
        end_date: date | None = None,
    ) -> AnalyticsTrends:
        """Return calendar-week and daily workload trends."""

        if not 1 <= weeks <= 52:
            raise AnalyticsTrendsQueryError("Requested weeks must be between 1 and 52.")

        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise AnalyticsTrendsQueryError("The configured athlete does not exist.")

        effective_end_date = self._resolve_end_date(
            athlete_id=athlete_id,
            requested_end_date=end_date,
        )
        latest_week_start = effective_end_date - timedelta(days=effective_end_date.weekday())
        start_date = latest_week_start - timedelta(weeks=weeks - 1)

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.verification_status != "excluded",
                    Activity.local_start_date >= start_date,
                    Activity.local_start_date <= effective_end_date,
                )
                .order_by(
                    Activity.local_start_date,
                    Activity.start_time_utc,
                    Activity.id,
                )
            )
        )

        metrics_by_activity = self._metrics_by_activity(activities)
        daily_workload = tuple(
            _workload_snapshot(daily_load)
            for daily_load in self._session.scalars(
                select(DailyLoad)
                .where(
                    DailyLoad.athlete_id == athlete_id,
                    DailyLoad.load_method == DURATION_LOAD_METHOD,
                    DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
                    DailyLoad.local_date >= start_date,
                    DailyLoad.local_date <= effective_end_date,
                )
                .order_by(DailyLoad.local_date)
            )
        )

        weekly_training = tuple(
            _weekly_summary(
                week_start=start_date + timedelta(weeks=index),
                end_date=effective_end_date,
                activities=activities,
                metrics_by_activity=metrics_by_activity,
            )
            for index in range(weeks)
        )

        return AnalyticsTrends(
            start_date=start_date,
            end_date=effective_end_date,
            requested_weeks=weeks,
            weekly_training=weekly_training,
            daily_workload=daily_workload,
        )

    def _resolve_end_date(
        self,
        *,
        athlete_id: UUID,
        requested_end_date: date | None,
    ) -> date:
        statement = select(DailyLoad.local_date).where(
            DailyLoad.athlete_id == athlete_id,
            DailyLoad.load_method == DURATION_LOAD_METHOD,
            DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
        )

        if requested_end_date is None:
            statement = statement.order_by(DailyLoad.local_date.desc()).limit(1)
        else:
            statement = statement.where(DailyLoad.local_date == requested_end_date)

        effective_end_date = self._session.scalar(statement)
        if effective_end_date is None:
            if requested_end_date is None:
                raise AnalyticsTrendsQueryError("No calculated daily workload is available.")
            raise AnalyticsTrendsQueryError(
                "No calculated daily workload exists for the requested end date."
            )

        return effective_end_date

    def _metrics_by_activity(
        self,
        activities: tuple[Activity, ...],
    ) -> dict[UUID, ActivityMetric]:
        if not activities:
            return {}

        activity_ids = tuple(activity.id for activity in activities)
        metrics = tuple(
            self._session.scalars(
                select(ActivityMetric)
                .where(
                    ActivityMetric.activity_id.in_(activity_ids),
                    ActivityMetric.algorithm_version == ACTIVITY_METRICS_VERSION,
                )
                .order_by(
                    ActivityMetric.activity_id,
                    ActivityMetric.calculated_at.desc(),
                    ActivityMetric.id.desc(),
                )
            )
        )
        return _latest_metrics(metrics)
