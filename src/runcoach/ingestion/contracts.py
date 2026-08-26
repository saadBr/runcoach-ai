"""Source-neutral contracts produced by activity-file adapters."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonNegativeFloat = Annotated[float, Field(ge=0)]
HeartRate = Annotated[int, Field(ge=1, le=300)]
Cadence = Annotated[float, Field(ge=0, le=500)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceProvider(StrEnum):
    """Supported activity-data providers."""

    GARMIN = "garmin"
    STRAVA = "strava"


class SourceFormat(StrEnum):
    """Inspected activity source formats."""

    CSV = "csv"
    FIT = "fit"
    FIT_GZ = "fit.gz"
    GPX = "gpx"
    JSON = "json"


class ActivityKind(StrEnum):
    """Canonical running classifications."""

    RUNNING = "running"
    TRAIL_RUNNING = "trail_running"
    TREADMILL_RUNNING = "treadmill_running"
    OTHER = "other"


class FindingSeverity(StrEnum):
    """Severity of a structured ingestion finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ContractModel(BaseModel):
    """Strict immutable base for normalized ingestion values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReference(ContractModel):
    """Provenance for one provider representation."""

    provider: SourceProvider
    source_format: SourceFormat
    source_file_name: Annotated[str, Field(min_length=1, max_length=1_024)]
    content_sha256: Sha256Digest
    referenced_file_name: Annotated[str, Field(min_length=1, max_length=1_024)] | None = None
    source_activity_id: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    source_row_number: Annotated[int, Field(ge=1)] | None = None


class NormalizedTrackpoint(ContractModel):
    """One timestamped sensor observation in canonical units."""

    sequence: Annotated[int, Field(ge=0)]
    timestamp_utc: datetime
    elapsed_time_s: NonNegativeFloat | None = None
    distance_m: NonNegativeFloat | None = None
    latitude_deg: Latitude | None = None
    longitude_deg: Longitude | None = None
    altitude_m: float | None = None
    heart_rate_bpm: HeartRate | None = None
    cadence_spm: Cadence | None = None
    speed_mps: NonNegativeFloat | None = None
    power_watts: NonNegativeFloat | None = None
    temperature_c: float | None = None

    @field_validator("timestamp_utc")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Require an absolute timestamp and normalize it to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must be timezone-aware")

        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> Self:
        """Prevent incomplete coordinate pairs."""

        has_latitude = self.latitude_deg is not None
        has_longitude = self.longitude_deg is not None

        if has_latitude != has_longitude:
            raise ValueError("latitude and longitude must be provided together")

        return self


class NormalizedLap(ContractModel):
    """One activity lap in canonical units."""

    sequence: Annotated[int, Field(ge=0)]
    start_time_utc: datetime | None = None
    elapsed_time_s: NonNegativeFloat | None = None
    moving_time_s: NonNegativeFloat | None = None
    distance_m: NonNegativeFloat | None = None
    elevation_gain_m: NonNegativeFloat | None = None
    elevation_loss_m: NonNegativeFloat | None = None
    average_heart_rate_bpm: HeartRate | None = None
    maximum_heart_rate_bpm: HeartRate | None = None
    average_cadence_spm: Cadence | None = None
    maximum_cadence_spm: Cadence | None = None

    @field_validator("start_time_utc")
    @classmethod
    def normalize_start_time(cls, value: datetime | None) -> datetime | None:
        """Normalize an optional lap timestamp to UTC."""

        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_time_utc must be timezone-aware")

        return value.astimezone(UTC)


class NormalizedActivity(ContractModel):
    """One provider activity normalized before deduplication."""

    athlete_id: UUID
    source: SourceReference
    activity_kind: ActivityKind
    provider_activity_type: Annotated[str, Field(min_length=1, max_length=255)]
    start_time_utc: datetime
    timezone_name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    name: Annotated[str, Field(max_length=500)] | None = None
    elapsed_time_s: NonNegativeFloat
    moving_time_s: NonNegativeFloat | None = None
    distance_m: NonNegativeFloat | None = None
    elevation_gain_m: NonNegativeFloat | None = None
    elevation_loss_m: NonNegativeFloat | None = None
    average_speed_mps: NonNegativeFloat | None = None
    maximum_speed_mps: NonNegativeFloat | None = None
    average_heart_rate_bpm: HeartRate | None = None
    maximum_heart_rate_bpm: HeartRate | None = None
    minimum_heart_rate_bpm: HeartRate | None = None
    average_cadence_spm: Cadence | None = None
    maximum_cadence_spm: Cadence | None = None
    calories_kcal: NonNegativeFloat | None = None
    steps: Annotated[int, Field(ge=0)] | None = None
    provider_vo2max: NonNegativeFloat | None = None
    provider_aerobic_training_effect: NonNegativeFloat | None = None
    provider_anaerobic_training_effect: NonNegativeFloat | None = None
    provider_training_effect_label: Annotated[str, Field(min_length=1, max_length=255)] | None = (
        None
    )
    laps: tuple[NormalizedLap, ...] = ()
    trackpoints: tuple[NormalizedTrackpoint, ...] = ()

    @field_validator("start_time_utc")
    @classmethod
    def normalize_start_time(cls, value: datetime) -> datetime:
        """Require an absolute activity timestamp and normalize it to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_time_utc must be timezone-aware")

        return value.astimezone(UTC)


class ValidationFinding(ContractModel):
    """Structured, non-medical finding produced during parsing or validation."""

    severity: FindingSeverity
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    source_row_number: Annotated[int, Field(ge=1)] | None = None
    field_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None


class ParseResult(ContractModel):
    """Complete result returned by an ingestion adapter."""

    activities: tuple[NormalizedActivity, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()
