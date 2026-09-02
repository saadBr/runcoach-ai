"""Read-only candidate queries for the verified-performance label audit."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    DEFAULT_DISTANCE_TOLERANCE_PCT,
    STANDARD_DISTANCE_AUDIT_VERSION,
    DistanceSample,
    StandardDistance,
    StandardDistanceEffort,
    calculate_standard_distance_effort,
    match_standard_distance,
)
from runcoach.db.models import Activity, Athlete, Trackpoint


class PerformanceAuditQueryError(RuntimeError):
    """Raised when a performance audit cannot be produced."""


@dataclass(frozen=True, slots=True)
class PerformanceCandidate:
    """A whole activity near a standard distance and awaiting human review."""

    activity_id: UUID
    achieved_at: datetime
    measured_distance_m: float
    elapsed_time_seconds: float
    elapsed_pace_seconds_per_km: float
    activity_type: str
    verification_status: str
    matched_distance: StandardDistance
    official_distance_m: float
    distance_deviation_m: float
    distance_deviation_pct: float


@dataclass(frozen=True, slots=True)
class PerformanceAudit:
    """Versioned summary of standard-distance candidates for manual labeling."""

    audit_version: str
    distance_tolerance_pct: float
    eligible_activities: int
    candidates: tuple[PerformanceCandidate, ...]


@dataclass(frozen=True, slots=True)
class PerformanceEvidence:
    """Recorded activity totals and an optional exact-distance derived effort."""

    activity_id: UUID
    achieved_at: datetime
    recorded_distance_m: float
    recorded_elapsed_time_seconds: float
    distance_samples: int
    target_distance: StandardDistance
    derived_effort: StandardDistanceEffort | None


class PerformanceAuditQueryService:
    """Read canonical activities and nominate possible verified performances."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def audit(
        self,
        *,
        athlete_id: UUID,
        distance_tolerance_pct: float = DEFAULT_DISTANCE_TOLERANCE_PCT,
    ) -> PerformanceAudit:
        """Return candidates without changing activity types or verification states."""

        if self._session.get(Athlete, athlete_id) is None:
            raise PerformanceAuditQueryError("The configured athlete does not exist.")

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.sport == "running",
                    Activity.verification_status != "excluded",
                    Activity.distance_m > 0,
                    Activity.elapsed_time_ms > 0,
                )
                .order_by(
                    Activity.start_time_utc,
                    Activity.id,
                )
            )
        )
        candidates: list[PerformanceCandidate] = []

        for activity in activities:
            measured_distance_m = float(activity.distance_m)
            match = match_standard_distance(
                measured_distance_m,
                tolerance_pct=distance_tolerance_pct,
            )
            if match is None:
                continue

            elapsed_time_seconds = activity.elapsed_time_ms / 1_000
            candidates.append(
                PerformanceCandidate(
                    activity_id=activity.id,
                    achieved_at=activity.start_time_utc,
                    measured_distance_m=measured_distance_m,
                    elapsed_time_seconds=elapsed_time_seconds,
                    elapsed_pace_seconds_per_km=round(
                        elapsed_time_seconds / (measured_distance_m / 1_000),
                        6,
                    ),
                    activity_type=activity.activity_type,
                    verification_status=activity.verification_status,
                    matched_distance=match.distance,
                    official_distance_m=match.official_distance_m,
                    distance_deviation_m=match.deviation_m,
                    distance_deviation_pct=match.deviation_pct,
                )
            )

        return PerformanceAudit(
            audit_version=STANDARD_DISTANCE_AUDIT_VERSION,
            distance_tolerance_pct=distance_tolerance_pct,
            eligible_activities=len(activities),
            candidates=tuple(candidates),
        )

    def evidence(
        self,
        *,
        athlete_id: UUID,
        activity_id: UUID,
        target_distance: StandardDistance,
    ) -> PerformanceEvidence:
        """Derive the standard-distance crossing supported by stored trackpoints."""

        activity = self._session.scalar(
            select(Activity).where(
                Activity.id == activity_id,
                Activity.athlete_id == athlete_id,
                Activity.sport == "running",
                Activity.verification_status != "excluded",
            )
        )
        if activity is None:
            raise PerformanceAuditQueryError(
                "The requested eligible running activity does not exist."
            )

        trackpoints = tuple(
            self._session.scalars(
                select(Trackpoint)
                .where(
                    Trackpoint.activity_id == activity_id,
                    Trackpoint.distance_m.is_not(None),
                )
                .order_by(Trackpoint.sequence_number)
            )
        )
        samples = tuple(
            DistanceSample(
                elapsed_ms=trackpoint.elapsed_ms,
                distance_m=float(trackpoint.distance_m),
            )
            for trackpoint in trackpoints
            if trackpoint.distance_m is not None
        )

        return PerformanceEvidence(
            activity_id=activity.id,
            achieved_at=activity.start_time_utc,
            recorded_distance_m=float(activity.distance_m),
            recorded_elapsed_time_seconds=activity.elapsed_time_ms / 1_000,
            distance_samples=len(samples),
            target_distance=target_distance,
            derived_effort=calculate_standard_distance_effort(
                samples,
                target_distance,
            ),
        )
