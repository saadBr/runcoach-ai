"""Persistence rules for time-valid athlete physiology profiles."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import HEART_RATE_ZONE_METHOD
from runcoach.db.models import Athlete, PhysiologyProfile


class PhysiologyProfileError(RuntimeError):
    """Raised when a physiology profile cannot be configured safely."""


class PhysiologyProfileConflictError(PhysiologyProfileError):
    """Raised when a requested profile conflicts with existing history."""


@dataclass(frozen=True, slots=True)
class PhysiologyProfileInput:
    """Validated inputs for one time-valid physiology profile."""

    athlete_id: UUID
    valid_from: date
    valid_to: date | None = None
    observed_max_hr_bpm: int | None = None
    resting_hr_bpm: int | None = None
    lactate_threshold_hr_bpm: int | None = None
    threshold_pace_seconds_per_km: int | None = None
    zone_method: str = HEART_RATE_ZONE_METHOD
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Profile valid_to must be later than valid_from.")

        if self.observed_max_hr_bpm is not None and (not 100 <= self.observed_max_hr_bpm <= 250):
            raise ValueError("Observed maximum heart rate is outside the plausible range.")

        if self.resting_hr_bpm is not None and (not 25 <= self.resting_hr_bpm <= 120):
            raise ValueError("Resting heart rate is outside the plausible range.")

        if self.lactate_threshold_hr_bpm is not None and (
            not 80 <= self.lactate_threshold_hr_bpm <= 230
        ):
            raise ValueError("Lactate-threshold heart rate is outside the plausible range.")

        if (
            self.observed_max_hr_bpm is not None
            and self.resting_hr_bpm is not None
            and self.resting_hr_bpm >= self.observed_max_hr_bpm
        ):
            raise ValueError("Resting heart rate must be lower than maximum heart rate.")

        if (
            self.observed_max_hr_bpm is not None
            and self.lactate_threshold_hr_bpm is not None
            and self.lactate_threshold_hr_bpm >= self.observed_max_hr_bpm
        ):
            raise ValueError("Threshold heart rate must be lower than maximum heart rate.")

        if (
            self.threshold_pace_seconds_per_km is not None
            and self.threshold_pace_seconds_per_km <= 0
        ):
            raise ValueError("Threshold pace must be positive.")

        if not self.zone_method.strip():
            raise ValueError("Zone method must not be blank.")


@dataclass(frozen=True, slots=True)
class ConfiguredPhysiologyProfile:
    """Result of idempotent physiology-profile configuration."""

    profile_id: UUID
    created: bool


def _periods_overlap(
    first_start: date,
    first_end: date | None,
    second_start: date,
    second_end: date | None,
) -> bool:
    effective_first_end = first_end or date.max
    effective_second_end = second_end or date.max

    return first_start < effective_second_end and second_start < effective_first_end


def _matches(
    existing: PhysiologyProfile,
    requested: PhysiologyProfileInput,
) -> bool:
    return (
        existing.athlete_id == requested.athlete_id
        and existing.valid_from == requested.valid_from
        and existing.valid_to == requested.valid_to
        and existing.observed_max_hr_bpm == requested.observed_max_hr_bpm
        and existing.resting_hr_bpm == requested.resting_hr_bpm
        and existing.lactate_threshold_hr_bpm == requested.lactate_threshold_hr_bpm
        and existing.threshold_pace_seconds_per_km == requested.threshold_pace_seconds_per_km
        and existing.zone_method == requested.zone_method
        and existing.notes == requested.notes
    )


class PhysiologyProfileService:
    """Create or reuse non-overlapping physiology profiles."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def configure(
        self,
        profile_input: PhysiologyProfileInput,
    ) -> ConfiguredPhysiologyProfile:
        """Persist one profile atomically and idempotently."""

        try:
            with self._session.begin():
                return self._configure(profile_input)
        except PhysiologyProfileError:
            raise
        except Exception as error:
            raise PhysiologyProfileError(
                "Physiology profile configuration failed and was rolled back."
            ) from error

    def _configure(
        self,
        profile_input: PhysiologyProfileInput,
    ) -> ConfiguredPhysiologyProfile:
        athlete = self._session.get(
            Athlete,
            profile_input.athlete_id,
        )
        if athlete is None:
            raise PhysiologyProfileError("The athlete must exist before configuring physiology.")

        existing_profiles = list(
            self._session.scalars(
                select(PhysiologyProfile)
                .where(PhysiologyProfile.athlete_id == profile_input.athlete_id)
                .order_by(PhysiologyProfile.valid_from)
            )
        )

        for existing in existing_profiles:
            if _matches(existing, profile_input):
                return ConfiguredPhysiologyProfile(
                    profile_id=existing.id,
                    created=False,
                )

            if _periods_overlap(
                existing.valid_from,
                existing.valid_to,
                profile_input.valid_from,
                profile_input.valid_to,
            ):
                raise PhysiologyProfileConflictError(
                    "The requested physiology profile overlaps existing history."
                )

        profile = PhysiologyProfile(
            athlete_id=profile_input.athlete_id,
            valid_from=profile_input.valid_from,
            valid_to=profile_input.valid_to,
            observed_max_hr_bpm=profile_input.observed_max_hr_bpm,
            resting_hr_bpm=profile_input.resting_hr_bpm,
            lactate_threshold_hr_bpm=(profile_input.lactate_threshold_hr_bpm),
            threshold_pace_seconds_per_km=(profile_input.threshold_pace_seconds_per_km),
            zone_method=profile_input.zone_method,
            notes=profile_input.notes,
        )
        self._session.add(profile)
        self._session.flush()

        return ConfiguredPhysiologyProfile(
            profile_id=profile.id,
            created=True,
        )
