"""Transactional persistence for deterministic running analytics."""

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import (
    ACTIVITY_METRICS_VERSION,
    DURATION_LOAD_METHOD,
    ActivityMetricInput,
    ActivityMetricResult,
    SensorSample,
    calculate_activity_metrics,
)
from runcoach.analytics.workload import (
    DAILY_LOAD_ALGORITHM_VERSION,
    DailyLoadObservation,
    DailyLoadResult,
    calculate_daily_load_series,
)
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
    PhysiologyProfile,
    Trackpoint,
)


class AnalyticsPersistenceError(RuntimeError):
    """Raised when deterministic analytics cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class AnalyticsCalculationSummary:
    """Aggregate result of one deterministic analytics calculation."""

    as_of_date: date
    activities_processed: int
    activities_with_profile: int
    activities_with_heart_rate_load: int
    activity_metrics_created: int
    activity_metrics_reused: int
    daily_loads_created: int
    daily_loads_updated: int
    daily_loads_reused: int


def _required_decimal(
    value: float,
    quantum: str,
) -> Decimal:
    return Decimal(str(value)).quantize(
        Decimal(quantum),
        rounding=ROUND_HALF_UP,
    )


def _optional_decimal(
    value: float | None,
    quantum: str,
) -> Decimal | None:
    if value is None:
        return None

    return _required_decimal(value, quantum)


def _profile_for_date(
    profiles: Sequence[PhysiologyProfile],
    local_date: date,
) -> PhysiologyProfile | None:
    matching = tuple(
        profile
        for profile in profiles
        if profile.valid_from <= local_date
        and (profile.valid_to is None or local_date < profile.valid_to)
    )

    if len(matching) > 1:
        raise AnalyticsPersistenceError(
            "More than one physiology profile applies to an activity date."
        )

    return matching[0] if matching else None


def _metric_input_hash(
    activity: Activity,
    profile: PhysiologyProfile | None,
    samples: tuple[SensorSample, ...],
) -> str:
    """Hash only calculation inputs, without retaining raw coordinates."""

    digest = sha256()
    header = {
        "algorithm_version": ACTIVITY_METRICS_VERSION,
        "activity_id": str(activity.id),
        "distance_m": str(activity.distance_m),
        "moving_time_ms": activity.moving_time_ms,
        "elapsed_time_ms": activity.elapsed_time_ms,
        "profile_id": str(profile.id) if profile is not None else None,
        "observed_max_hr_bpm": (profile.observed_max_hr_bpm if profile is not None else None),
    }
    digest.update(
        json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    for sample in samples:
        sample_values = (
            sample.elapsed_ms,
            sample.heart_rate_bpm,
            sample.has_position,
            sample.cadence_spm,
            sample.is_paused,
        )
        digest.update(
            json.dumps(
                sample_values,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    return digest.hexdigest()


def _zone_document(
    result: ActivityMetricResult,
) -> dict[str, Any]:
    return {
        "method": result.heart_rate_zone_method,
        "zones": [
            {
                "zone": zone.zone.value,
                "seconds": zone.seconds,
                "percent_of_observed_hr_time": (zone.percent_of_observed_hr_time),
            }
            for zone in result.zone_distribution
        ],
    }


def _additional_metrics_document(
    result: ActivityMetricResult,
    sample_count: int,
) -> dict[str, Any]:
    return {
        "average_elapsed_pace_seconds_per_km": (result.average_elapsed_pace_seconds_per_km),
        "edwards_trimp": result.edwards_trimp,
        "sample_gap_cap_seconds": result.sample_gap_cap_seconds,
        "sample_count": sample_count,
    }


def _daily_load_matches(
    existing: DailyLoad,
    calculated: DailyLoadResult,
) -> bool:
    return (
        existing.daily_load == _required_decimal(calculated.daily_load, "0.0001")
        and existing.acute_load == _optional_decimal(calculated.acute_load, "0.0001")
        and existing.chronic_load == _optional_decimal(calculated.chronic_load, "0.0001")
        and existing.fitness_index == _optional_decimal(calculated.fitness_index, "0.0001")
        and existing.fatigue_index == _optional_decimal(calculated.fatigue_index, "0.0001")
        and existing.form_index == _optional_decimal(calculated.form_index, "0.0001")
        and existing.coverage_pct == _required_decimal(calculated.coverage_pct, "0.001")
    )


class DeterministicAnalyticsService:
    """Calculate and persist versioned activity and daily metrics."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def calculate(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date,
    ) -> AnalyticsCalculationSummary:
        """Calculate analytics atomically for one athlete and date."""

        try:
            with self._session.begin():
                return self._calculate(
                    athlete_id=athlete_id,
                    as_of_date=as_of_date,
                )
        except AnalyticsPersistenceError:
            raise
        except Exception as error:
            raise AnalyticsPersistenceError(
                "Analytics calculation failed and was rolled back."
            ) from error

    def _calculate(
        self,
        *,
        athlete_id: UUID,
        as_of_date: date,
    ) -> AnalyticsCalculationSummary:
        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise AnalyticsPersistenceError("The athlete must exist before calculating analytics.")

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.verification_status != "excluded",
                    Activity.local_start_date <= as_of_date,
                )
                .order_by(
                    Activity.local_start_date,
                    Activity.start_time_utc,
                    Activity.id,
                )
            )
        )
        if not activities:
            raise AnalyticsPersistenceError(
                "No eligible activities exist on or before the requested date."
            )

        profiles = tuple(
            self._session.scalars(
                select(PhysiologyProfile)
                .where(PhysiologyProfile.athlete_id == athlete_id)
                .order_by(PhysiologyProfile.valid_from)
            )
        )

        samples_by_activity = self._load_samples(tuple(activity.id for activity in activities))

        existing_metrics = {
            (
                metric.activity_id,
                metric.algorithm_version,
                metric.input_hash,
            ): metric
            for metric in self._session.scalars(
                select(ActivityMetric).where(
                    ActivityMetric.activity_id.in_(tuple(activity.id for activity in activities)),
                    ActivityMetric.algorithm_version == ACTIVITY_METRICS_VERSION,
                )
            )
        }

        metrics_created = 0
        metrics_reused = 0
        activities_with_profile = 0
        activities_with_heart_rate_load = 0
        daily_totals: dict[date, float] = defaultdict(float)

        for activity in activities:
            profile = _profile_for_date(
                profiles,
                activity.local_start_date,
            )
            if profile is not None:
                activities_with_profile += 1

            samples = samples_by_activity.get(activity.id, ())
            metric_input = ActivityMetricInput(
                distance_m=float(activity.distance_m),
                moving_time_ms=activity.moving_time_ms,
                elapsed_time_ms=activity.elapsed_time_ms,
                observed_max_hr_bpm=(profile.observed_max_hr_bpm if profile is not None else None),
                samples=samples,
            )
            result = calculate_activity_metrics(metric_input)
            input_hash = _metric_input_hash(
                activity,
                profile,
                samples,
            )
            metric_key = (
                activity.id,
                result.algorithm_version,
                input_hash,
            )

            if metric_key in existing_metrics:
                metrics_reused += 1
            else:
                self._session.add(
                    ActivityMetric(
                        activity_id=activity.id,
                        algorithm_version=result.algorithm_version,
                        profile_id=(profile.id if profile is not None else None),
                        input_hash=input_hash,
                        average_pace_seconds_per_km=_optional_decimal(
                            result.average_moving_pace_seconds_per_km,
                            "0.001",
                        ),
                        heart_rate_coverage_pct=_required_decimal(
                            result.heart_rate_coverage_pct,
                            "0.001",
                        ),
                        gps_coverage_pct=_required_decimal(
                            result.gps_coverage_pct,
                            "0.001",
                        ),
                        cadence_coverage_pct=_required_decimal(
                            result.cadence_coverage_pct,
                            "0.001",
                        ),
                        load_method=result.load_method,
                        training_load=_required_decimal(
                            result.training_load,
                            "0.0001",
                        ),
                        zone_distribution=_zone_document(result),
                        additional_metrics=_additional_metrics_document(
                            result,
                            len(samples),
                        ),
                    )
                )
                metrics_created += 1

            if result.edwards_trimp is not None:
                activities_with_heart_rate_load += 1

            daily_totals[activity.local_start_date] += result.training_load

        observations = tuple(
            DailyLoadObservation(
                local_date=local_date,
                daily_load=round(daily_load, 6),
                coverage_pct=100.0,
            )
            for local_date, daily_load in sorted(daily_totals.items())
        )
        daily_results = calculate_daily_load_series(
            observations,
            end_date=as_of_date,
        )

        daily_created, daily_updated, daily_reused = self._persist_daily_loads(
            athlete_id=athlete_id,
            calculated=daily_results,
        )

        self._session.flush()

        return AnalyticsCalculationSummary(
            as_of_date=as_of_date,
            activities_processed=len(activities),
            activities_with_profile=activities_with_profile,
            activities_with_heart_rate_load=(activities_with_heart_rate_load),
            activity_metrics_created=metrics_created,
            activity_metrics_reused=metrics_reused,
            daily_loads_created=daily_created,
            daily_loads_updated=daily_updated,
            daily_loads_reused=daily_reused,
        )

    def _load_samples(
        self,
        activity_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[SensorSample, ...]]:
        samples: dict[UUID, list[SensorSample]] = defaultdict(list)

        trackpoints = self._session.scalars(
            select(Trackpoint)
            .where(Trackpoint.activity_id.in_(activity_ids))
            .order_by(
                Trackpoint.activity_id,
                Trackpoint.sequence_number,
            )
        ).yield_per(5_000)

        for trackpoint in trackpoints:
            samples[trackpoint.activity_id].append(
                SensorSample(
                    elapsed_ms=trackpoint.elapsed_ms,
                    heart_rate_bpm=trackpoint.heart_rate_bpm,
                    has_position=(
                        trackpoint.latitude is not None and trackpoint.longitude is not None
                    ),
                    cadence_spm=(
                        float(trackpoint.cadence_spm)
                        if trackpoint.cadence_spm is not None
                        else None
                    ),
                    is_paused=trackpoint.is_paused,
                )
            )

        return {
            activity_id: tuple(activity_samples)
            for activity_id, activity_samples in samples.items()
        }

    def _persist_daily_loads(
        self,
        *,
        athlete_id: UUID,
        calculated: tuple[DailyLoadResult, ...],
    ) -> tuple[int, int, int]:
        existing_by_date = {
            daily_load.local_date: daily_load
            for daily_load in self._session.scalars(
                select(DailyLoad).where(
                    DailyLoad.athlete_id == athlete_id,
                    DailyLoad.load_method == DURATION_LOAD_METHOD,
                    DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
                )
            )
        }

        created = 0
        updated = 0
        reused = 0

        for result in calculated:
            existing = existing_by_date.get(result.local_date)

            if existing is None:
                self._session.add(
                    DailyLoad(
                        athlete_id=athlete_id,
                        local_date=result.local_date,
                        load_method=DURATION_LOAD_METHOD,
                        algorithm_version=result.algorithm_version,
                        daily_load=_required_decimal(
                            result.daily_load,
                            "0.0001",
                        ),
                        acute_load=_optional_decimal(
                            result.acute_load,
                            "0.0001",
                        ),
                        chronic_load=_optional_decimal(
                            result.chronic_load,
                            "0.0001",
                        ),
                        fitness_index=_optional_decimal(
                            result.fitness_index,
                            "0.0001",
                        ),
                        fatigue_index=_optional_decimal(
                            result.fatigue_index,
                            "0.0001",
                        ),
                        form_index=_optional_decimal(
                            result.form_index,
                            "0.0001",
                        ),
                        coverage_pct=_required_decimal(
                            result.coverage_pct,
                            "0.001",
                        ),
                    )
                )
                created += 1
                continue

            if _daily_load_matches(existing, result):
                reused += 1
                continue

            existing.daily_load = _required_decimal(
                result.daily_load,
                "0.0001",
            )
            existing.acute_load = _optional_decimal(
                result.acute_load,
                "0.0001",
            )
            existing.chronic_load = _optional_decimal(
                result.chronic_load,
                "0.0001",
            )
            existing.fitness_index = _optional_decimal(
                result.fitness_index,
                "0.0001",
            )
            existing.fatigue_index = _optional_decimal(
                result.fatigue_index,
                "0.0001",
            )
            existing.form_index = _optional_decimal(
                result.form_index,
                "0.0001",
            )
            existing.coverage_pct = _required_decimal(
                result.coverage_pct,
                "0.001",
            )
            existing.calculated_at = datetime.now(UTC)
            updated += 1

        return created, updated, reused
