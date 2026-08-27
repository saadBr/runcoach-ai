"""Read-only query models for training analytics presentation."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import fmean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
)
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
)


class AnalyticsQueryError(RuntimeError):
    """Raised when a requested analytics view is unavailable."""


@dataclass(frozen=True, slots=True)
class TrainingWindowSummary:
    """Aggregated training completed inside one inclusive date window."""

    days: int
    start_date: date
    end_date: date
    runs: int
    distance_km: float
    moving_hours: float


@dataclass(frozen=True, slots=True)
class SensorCoverageSummary:
    """Aggregate coverage of the latest activity-metric versions."""

    activities_with_metrics: int
    activities_with_heart_rate_load: int
    average_heart_rate_coverage_pct: float
    average_gps_coverage_pct: float
    average_cadence_coverage_pct: float


@dataclass(frozen=True, slots=True)
class WorkloadSnapshot:
    """Latest persisted workload state on an exact local date."""

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


@dataclass(frozen=True, slots=True)
class AnalyticsOverview:
    """Dashboard-ready overview without private route coordinates."""

    as_of_date: date
    data_start_date: date
    data_end_date: date
    total_runs: int
    total_distance_km: float
    total_moving_hours: float
    last_7_days: TrainingWindowSummary
    last_28_days: TrainingWindowSummary
    sensor_coverage: SensorCoverageSummary
    workload: WorkloadSnapshot


def _optional_float(
    value: Decimal | float | int | None,
) -> float | None:
    if value is None:
        return None

    return float(value)


def _training_window(
    activities: tuple[Activity, ...],
    *,
    days: int,
    end_date: date,
) -> TrainingWindowSummary:
    start_date = end_date - timedelta(days=days - 1)
    selected = tuple(
        activity for activity in activities if start_date <= activity.local_start_date <= end_date
    )

    return TrainingWindowSummary(
        days=days,
        start_date=start_date,
        end_date=end_date,
        runs=len(selected),
        distance_km=round(
            sum(float(activity.distance_m) for activity in selected) / 1_000,
            3,
        ),
        moving_hours=round(
            sum(activity.moving_time_ms for activity in selected) / 3_600_000,
            3,
        ),
    )


def _sensor_coverage(
    metrics: tuple[ActivityMetric, ...],
) -> SensorCoverageSummary:
    if not metrics:
        return SensorCoverageSummary(
            activities_with_metrics=0,
            activities_with_heart_rate_load=0,
            average_heart_rate_coverage_pct=0.0,
            average_gps_coverage_pct=0.0,
            average_cadence_coverage_pct=0.0,
        )

    return SensorCoverageSummary(
        activities_with_metrics=len(metrics),
        activities_with_heart_rate_load=sum(
            1 for metric in metrics if metric.additional_metrics.get("edwards_trimp") is not None
        ),
        average_heart_rate_coverage_pct=round(
            fmean(float(metric.heart_rate_coverage_pct) for metric in metrics),
            3,
        ),
        average_gps_coverage_pct=round(
            fmean(float(metric.gps_coverage_pct) for metric in metrics),
            3,
        ),
        average_cadence_coverage_pct=round(
            fmean(float(metric.cadence_coverage_pct) for metric in metrics),
            3,
        ),
    )


def _latest_metrics(
    metrics: tuple[ActivityMetric, ...],
) -> tuple[ActivityMetric, ...]:
    latest_by_activity: dict[UUID, ActivityMetric] = {}

    for metric in metrics:
        latest_by_activity.setdefault(metric.activity_id, metric)

    return tuple(latest_by_activity.values())


class AnalyticsQueryService:
    """Read dashboard-ready analytics from persisted calculations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def overview(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date | None = None,
    ) -> AnalyticsOverview:
        """Return one deterministic analytics overview."""

        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise AnalyticsQueryError("The configured athlete does not exist.")

        workload = self._workload_snapshot(
            athlete_id=athlete_id,
            as_of_date=as_of_date,
        )
        effective_date = workload.local_date

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.verification_status != "excluded",
                    Activity.local_start_date <= effective_date,
                )
                .order_by(
                    Activity.local_start_date,
                    Activity.start_time_utc,
                    Activity.id,
                )
            )
        )
        if not activities:
            raise AnalyticsQueryError("No eligible activities exist for the analytics overview.")

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
        latest_metrics = _latest_metrics(metrics)

        return AnalyticsOverview(
            as_of_date=effective_date,
            data_start_date=activities[0].local_start_date,
            data_end_date=activities[-1].local_start_date,
            total_runs=len(activities),
            total_distance_km=round(
                sum(float(activity.distance_m) for activity in activities) / 1_000,
                3,
            ),
            total_moving_hours=round(
                sum(activity.moving_time_ms for activity in activities) / 3_600_000,
                3,
            ),
            last_7_days=_training_window(
                activities,
                days=7,
                end_date=effective_date,
            ),
            last_28_days=_training_window(
                activities,
                days=28,
                end_date=effective_date,
            ),
            sensor_coverage=_sensor_coverage(latest_metrics),
            workload=workload,
        )

    def _workload_snapshot(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date | None,
    ) -> WorkloadSnapshot:
        statement = select(DailyLoad).where(
            DailyLoad.athlete_id == athlete_id,
            DailyLoad.load_method == DURATION_LOAD_METHOD,
            DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
        )

        if as_of_date is None:
            statement = statement.order_by(DailyLoad.local_date.desc()).limit(1)
        else:
            statement = statement.where(DailyLoad.local_date == as_of_date)

        daily_load = self._session.scalar(statement)
        if daily_load is None:
            if as_of_date is None:
                raise AnalyticsQueryError("No calculated daily workload is available.")
            raise AnalyticsQueryError("No calculated daily workload exists for the requested date.")

        return WorkloadSnapshot(
            local_date=daily_load.local_date,
            load_method=daily_load.load_method,
            algorithm_version=daily_load.algorithm_version,
            daily_load=float(daily_load.daily_load),
            acute_load=_optional_float(daily_load.acute_load),
            chronic_load=_optional_float(daily_load.chronic_load),
            fitness_index=_optional_float(daily_load.fitness_index),
            fatigue_index=_optional_float(daily_load.fatigue_index),
            form_index=_optional_float(daily_load.form_index),
            coverage_pct=float(daily_load.coverage_pct),
        )
