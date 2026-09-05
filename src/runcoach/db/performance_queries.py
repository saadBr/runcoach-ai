"""Read-only verified-performance queries for the analytical dashboard."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
    VerifiedPerformance,
    standard_distance_meters,
)
from runcoach.db.models import Athlete, PersonalBest

DISTANCE_BY_METERS = {
    Decimal("5000.000"): StandardDistance.FIVE_K,
    Decimal("10000.000"): StandardDistance.TEN_K,
    Decimal("21097.500"): StandardDistance.HALF_MARATHON,
    Decimal("42195.000"): StandardDistance.MARATHON,
}


class PerformanceQueryError(RuntimeError):
    """Raised when verified performance evidence is unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class PersonalBestSummary:
    """One active verified personal best and its evidence reference."""

    personal_best_id: UUID
    activity_id: UUID
    distance: StandardDistance
    distance_m: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float
    achieved_at: datetime
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    verification_source: str
    algorithm_version: str


@dataclass(frozen=True, slots=True)
class PerformanceOverview:
    """Current verified personal bests and honest model-readiness state."""

    personal_bests: tuple[PersonalBestSummary, ...]
    prediction_status: str
    prediction_method: str
    verified_labels: int
    interpretation_role: str
    limitations: tuple[str, ...]


def _standard_distance(distance_m: Decimal) -> StandardDistance:
    try:
        return DISTANCE_BY_METERS[distance_m]
    except KeyError as error:
        raise PerformanceQueryError(
            "A current personal best uses an unsupported standard distance."
        ) from error


def _utc_datetime(value: datetime) -> datetime:
    """Preserve PostgreSQL timestamps and normalize SQLite test values as UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


class PerformanceQueryService:
    """Read verified PBs without presenting formula estimates as predictions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def overview(self, *, athlete_id: UUID) -> PerformanceOverview:
        """Return current PBs and the training-model readiness state."""

        if self._session.get(Athlete, athlete_id) is None:
            raise PerformanceQueryError("The configured athlete does not exist.")

        records = tuple(
            self._session.scalars(
                select(PersonalBest)
                .where(
                    PersonalBest.athlete_id == athlete_id,
                    PersonalBest.superseded_at.is_(None),
                )
                .order_by(PersonalBest.distance_m, PersonalBest.achieved_at)
            )
        )
        if not records:
            raise PerformanceQueryError("No verified personal bests are available.")

        summaries: list[PersonalBestSummary] = []
        observed_distances: set[StandardDistance] = set()

        for record in records:
            distance = _standard_distance(record.distance_m)
            if distance in observed_distances:
                raise PerformanceQueryError(
                    f"Multiple current personal bests exist for {distance.value}."
                )
            observed_distances.add(distance)

            achieved_at = _utc_datetime(record.achieved_at)
            elapsed_time_seconds = record.elapsed_time_ms / 1_000
            performance = VerifiedPerformance(
                activity_id=record.activity_id,
                distance=distance,
                elapsed_time_seconds=elapsed_time_seconds,
                achieved_at=achieved_at,
                label=PerformanceLabel(record.verification_status),
            )
            summaries.append(
                PersonalBestSummary(
                    personal_best_id=record.id,
                    activity_id=record.activity_id,
                    distance=distance,
                    distance_m=standard_distance_meters(distance),
                    elapsed_time_seconds=elapsed_time_seconds,
                    pace_seconds_per_km=round(
                        elapsed_time_seconds / (standard_distance_meters(distance) / 1_000),
                        6,
                    ),
                    achieved_at=achieved_at,
                    verification_status=performance.label,
                    effort_type=PerformanceEffortType(record.effort_type),
                    verification_source=record.verification_source,
                    algorithm_version=record.algorithm_version,
                )
            )

        return PerformanceOverview(
            personal_bests=tuple(summaries),
            prediction_status="label_audit_required",
            prediction_method="training_feature_model",
            verified_labels=len(summaries),
            interpretation_role="openai_explains_validated_outputs_only",
            limitations=(
                "No training-informed prediction is published before label audit and "
                "chronological evaluation pass.",
                "OpenAI may explain validated evidence but does not calculate race times.",
                "Only active verified personal bests linked to stored activities are included.",
            ),
        )
