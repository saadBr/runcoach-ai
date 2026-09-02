"""Transactional persistence for verified personal-best progression."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    STRAVA_BEST_EFFORT_IMPORT_VERSION,
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
    standard_distance_meters,
)
from runcoach.db.models import Activity, Athlete, PersonalBest

STRAVA_BEST_EFFORT_SOURCE = "strava_best_effort"


class PersonalBestError(RuntimeError):
    """Raised when a personal-best record cannot be persisted safely."""


class PersonalBestConflictError(PersonalBestError):
    """Raised when a result is not a chronological personal-best improvement."""


@dataclass(frozen=True, slots=True)
class PersonalBestInput:
    """One externally verified performance linked to a canonical activity."""

    athlete_id: UUID
    activity_id: UUID
    distance: StandardDistance
    elapsed_time_ms: int
    label: PerformanceLabel
    effort_type: PerformanceEffortType = PerformanceEffortType.PROVIDER_BEST_EFFORT
    verification_source: str = STRAVA_BEST_EFFORT_SOURCE
    algorithm_version: str = STRAVA_BEST_EFFORT_IMPORT_VERSION

    def __post_init__(self) -> None:
        if self.elapsed_time_ms <= 0:
            raise ValueError("Personal-best elapsed time must be positive.")
        if not self.verification_source.strip():
            raise ValueError("Verification source must not be blank.")
        if not self.algorithm_version.strip():
            raise ValueError("Algorithm version must not be blank.")


@dataclass(frozen=True, slots=True)
class ConfiguredPersonalBest:
    """Result of idempotent personal-best persistence."""

    personal_best_id: UUID
    created: bool
    superseded_personal_best_id: UUID | None


class PersonalBestService:
    """Create or reuse verified PBs while retaining superseded history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, personal_best_input: PersonalBestInput) -> ConfiguredPersonalBest:
        """Persist one chronological PB event atomically."""

        try:
            with self._session.begin():
                return self._record(personal_best_input)
        except PersonalBestError:
            raise
        except Exception as error:
            raise PersonalBestError(
                "Personal-best persistence failed and was rolled back."
            ) from error

    def _record(self, personal_best_input: PersonalBestInput) -> ConfiguredPersonalBest:
        athlete = self._session.get(Athlete, personal_best_input.athlete_id)
        if athlete is None:
            raise PersonalBestError("The athlete must exist before recording a personal best.")

        activity = self._session.get(Activity, personal_best_input.activity_id)
        if (
            activity is None
            or activity.athlete_id != personal_best_input.athlete_id
            or activity.sport != "running"
            or activity.verification_status == "excluded"
        ):
            raise PersonalBestError(
                "The personal best must reference an eligible running activity "
                "owned by the athlete."
            )

        distance_m = Decimal(str(standard_distance_meters(personal_best_input.distance)))
        identical = self._session.scalar(
            select(PersonalBest).where(
                PersonalBest.activity_id == personal_best_input.activity_id,
                PersonalBest.distance_m == distance_m,
                PersonalBest.elapsed_time_ms == personal_best_input.elapsed_time_ms,
                PersonalBest.effort_type == personal_best_input.effort_type.value,
                PersonalBest.verification_status == personal_best_input.label.value,
                PersonalBest.verification_source == personal_best_input.verification_source,
                PersonalBest.algorithm_version == personal_best_input.algorithm_version,
            )
        )
        if identical is not None:
            return ConfiguredPersonalBest(
                personal_best_id=identical.id,
                created=False,
                superseded_personal_best_id=None,
            )

        current = self._session.scalar(
            select(PersonalBest)
            .where(
                PersonalBest.athlete_id == personal_best_input.athlete_id,
                PersonalBest.distance_m == distance_m,
                PersonalBest.superseded_at.is_(None),
            )
            .order_by(PersonalBest.achieved_at.desc(), PersonalBest.id.desc())
        )
        superseded_id: UUID | None = None

        if current is not None:
            if activity.start_time_utc <= current.achieved_at:
                raise PersonalBestConflictError(
                    "A new personal best must be recorded after the current personal best."
                )
            if personal_best_input.elapsed_time_ms >= current.elapsed_time_ms:
                raise PersonalBestConflictError(
                    "The verified result does not improve the current personal best."
                )
            current.superseded_at = activity.start_time_utc
            superseded_id = current.id

        personal_best = PersonalBest(
            athlete_id=personal_best_input.athlete_id,
            activity_id=personal_best_input.activity_id,
            distance_m=distance_m,
            elapsed_time_ms=personal_best_input.elapsed_time_ms,
            effort_type=personal_best_input.effort_type.value,
            verification_status=personal_best_input.label.value,
            verification_source=personal_best_input.verification_source,
            achieved_at=activity.start_time_utc,
            algorithm_version=personal_best_input.algorithm_version,
            superseded_at=None,
        )
        self._session.add(personal_best)
        self._session.flush()

        return ConfiguredPersonalBest(
            personal_best_id=personal_best.id,
            created=True,
            superseded_personal_best_id=superseded_id,
        )
