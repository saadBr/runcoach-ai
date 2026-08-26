"""Transactional persistence for reconciled ingestion results."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from pathlib import PurePosixPath
from string import hexdigits
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.db.models import (
    Activity,
    ActivityFieldSource,
    Athlete,
    DataQualityIssue,
    ImportBatch,
    ImportFile,
    SourceActivity,
)
from runcoach.ingestion.contracts import (
    NormalizedActivity,
    SourceFormat,
    SourceProvider,
    SourceReference,
)
from runcoach.ingestion.reconciliation import (
    MatchMethod,
    ReconciledActivity,
    ReconciliationResult,
)

type FileIdentity = tuple[str, str, str]
type ReferenceIdentity = tuple[str, str, str, str, str | None, int | None]


class IngestionPersistenceError(RuntimeError):
    """Raised when a reconciliation result cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class ImportFileDescriptor:
    """Privacy-safe metadata for one file included in an import batch."""

    provider: SourceProvider
    source_format: SourceFormat
    source_file_name: str
    content_sha256: str
    storage_key: str
    size_bytes: int
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.source_file_name.strip():
            raise ValueError("source_file_name must not be blank")

        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

        normalized_hash = self.content_sha256.lower()
        if len(normalized_hash) != 64 or any(
            character not in hexdigits for character in normalized_hash
        ):
            raise ValueError("content_sha256 must be a 64-character hexadecimal digest")

        normalized_key = self.storage_key.replace("\\", "/")
        key_path = PurePosixPath(normalized_key)
        has_windows_drive = len(normalized_key) >= 2 and normalized_key[1] == ":"

        if (
            not normalized_key
            or key_path.is_absolute()
            or has_windows_drive
            or ".." in key_path.parts
        ):
            raise ValueError("storage_key must be a safe relative logical path")

        object.__setattr__(self, "content_sha256", normalized_hash)
        object.__setattr__(self, "storage_key", normalized_key)


@dataclass(frozen=True, slots=True)
class PersistedImportSummary:
    """Stable identifiers and counts returned after a successful transaction."""

    import_batch_id: UUID
    accepted_files: int
    duplicate_files: int
    activities_created: int
    activities_reused: int
    source_activities_created: int
    quality_issues_created: int


def _file_identity(
    provider: SourceProvider,
    content_sha256: str,
    source_file_name: str,
) -> FileIdentity:
    return provider.value, content_sha256.lower(), source_file_name


def _reference_identity(source: SourceReference) -> ReferenceIdentity:
    return (
        source.provider.value,
        source.source_format.value,
        source.source_file_name,
        source.content_sha256.lower(),
        source.source_activity_id,
        source.source_row_number,
    )


def _decimal(value: float | int | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _milliseconds(value: float | int | None) -> int | None:
    if value is None:
        return None

    milliseconds = Decimal(str(value)) * Decimal(1000)
    return int(milliseconds.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _local_start_date(
    activity: NormalizedActivity,
    athlete_timezone: str,
) -> date:
    timezone_name = activity.timezone_name or athlete_timezone

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(athlete_timezone)

    return activity.start_time_utc.astimezone(timezone).date()


def _required_measurements(
    activity: NormalizedActivity,
) -> tuple[Decimal, int, int]:
    distance = _decimal(activity.distance_m)
    elapsed_time = _milliseconds(activity.elapsed_time_s)

    if distance is None:
        raise IngestionPersistenceError("Canonical activity cannot be persisted without distance.")
    if elapsed_time is None:
        raise IngestionPersistenceError(
            "Canonical activity cannot be persisted without elapsed time."
        )

    moving_time = _milliseconds(activity.moving_time_s)
    if moving_time is None:
        moving_time = elapsed_time

    return distance, moving_time, elapsed_time


def _dedupe_fingerprint(activity: NormalizedActivity) -> str:
    elapsed_time = _milliseconds(activity.elapsed_time_s)
    distance = _decimal(activity.distance_m)

    payload = "|".join(
        (
            str(activity.athlete_id),
            activity.source.provider.value,
            activity.start_time_utc.astimezone(UTC).isoformat(),
            activity.activity_kind.value,
            "" if distance is None else str(distance.quantize(Decimal("0.001"))),
            "" if elapsed_time is None else str(elapsed_time),
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _source_metadata(
    activity: NormalizedActivity,
    match_method: MatchMethod,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_format": activity.source.source_format.value,
        "source_file_name": activity.source.source_file_name,
        "source_row_number": activity.source.source_row_number,
        "activity_kind": activity.activity_kind.value,
        "match_method": match_method.value,
    }

    optional_values: dict[str, Any] = {
        "minimum_heart_rate_bpm": activity.minimum_heart_rate_bpm,
        "maximum_cadence_spm": activity.maximum_cadence_spm,
        "steps": activity.steps,
        "provider_vo2max": activity.provider_vo2max,
        "provider_aerobic_training_effect": (activity.provider_aerobic_training_effect),
        "provider_anaerobic_training_effect": (activity.provider_anaerobic_training_effect),
        "provider_training_effect_label": (activity.provider_training_effect_label),
    }

    metadata.update(
        {field_name: value for field_name, value in optional_values.items() if value is not None}
    )
    return metadata


class ReconciliationPersistenceService:
    """Persist one reconciliation result as a single database transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist(
        self,
        *,
        athlete_id: UUID,
        athlete_timezone: str,
        parser_bundle_version: str,
        files: tuple[ImportFileDescriptor, ...],
        result: ReconciliationResult,
        athlete_display_name: str | None = None,
    ) -> PersistedImportSummary:
        """Persist athlete, import audit, canonical records, and provenance."""

        if not athlete_timezone.strip():
            raise ValueError("athlete_timezone must not be blank")
        try:
            ZoneInfo(athlete_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("athlete_timezone must be a valid IANA timezone.") from error
        if not parser_bundle_version.strip():
            raise ValueError("parser_bundle_version must not be blank")
        if not files:
            raise ValueError("At least one import file descriptor is required")

        file_identities = {
            _file_identity(
                descriptor.provider,
                descriptor.content_sha256,
                descriptor.source_file_name,
            )
            for descriptor in files
        }
        if len(file_identities) != len(files):
            raise ValueError("Import file descriptors must be unique")

        with self._session.begin():
            athlete = self._ensure_athlete(
                athlete_id=athlete_id,
                timezone_name=athlete_timezone,
                display_name=athlete_display_name,
            )
            batch = ImportBatch(
                athlete_id=athlete.id,
                status="processing",
                started_at=datetime.now(UTC),
                parser_bundle_version=parser_bundle_version,
                total_files=len(files),
            )
            self._session.add(batch)
            self._session.flush()

            import_files, accepted_files, duplicate_files = self._persist_files(
                athlete_id=athlete.id,
                batch=batch,
                files=files,
                parser_bundle_version=parser_bundle_version,
            )

            activities_created = 0
            activities_reused = 0
            source_activities_created = 0

            for reconciled in result.activities:
                created, created_sources = self._persist_activity(
                    athlete=athlete,
                    reconciled=reconciled,
                    import_files=import_files,
                )
                activities_created += int(created)
                activities_reused += int(not created)
                source_activities_created += created_sources

            quality_issues_created = self._persist_findings(
                batch=batch,
                result=result,
            )
            warning_count = sum(finding.severity.value != "info" for finding in result.findings)

            batch.accepted_files = accepted_files
            batch.duplicate_files = duplicate_files
            batch.warning_count = warning_count
            batch.status = "completed_with_warnings" if warning_count else "completed"
            batch.completed_at = datetime.now(UTC)
            self._session.flush()

            return PersistedImportSummary(
                import_batch_id=batch.id,
                accepted_files=accepted_files,
                duplicate_files=duplicate_files,
                activities_created=activities_created,
                activities_reused=activities_reused,
                source_activities_created=source_activities_created,
                quality_issues_created=quality_issues_created,
            )

    def _ensure_athlete(
        self,
        *,
        athlete_id: UUID,
        timezone_name: str,
        display_name: str | None,
    ) -> Athlete:
        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            athlete = Athlete(
                id=athlete_id,
                timezone=timezone_name,
                display_name=display_name,
            )
            self._session.add(athlete)
            self._session.flush()
            return athlete

        athlete.timezone = timezone_name
        if display_name is not None:
            athlete.display_name = display_name
        return athlete

    def _persist_files(
        self,
        *,
        athlete_id: UUID,
        batch: ImportBatch,
        files: tuple[ImportFileDescriptor, ...],
        parser_bundle_version: str,
    ) -> tuple[dict[FileIdentity, ImportFile], int, int]:
        persisted_files: dict[FileIdentity, ImportFile] = {}
        accepted_files = 0
        duplicate_files = 0

        for descriptor in files:
            previous_file = self._session.scalar(
                select(ImportFile)
                .join(ImportBatch)
                .where(
                    ImportBatch.athlete_id == athlete_id,
                    ImportFile.source_provider == descriptor.provider.value,
                    ImportFile.sha256 == descriptor.content_sha256,
                    ImportFile.status == "accepted",
                )
                .limit(1)
            )
            status = "duplicate" if previous_file is not None else "accepted"
            accepted_files += int(status == "accepted")
            duplicate_files += int(status == "duplicate")

            import_file = ImportFile(
                import_batch_id=batch.id,
                original_name=descriptor.source_file_name,
                source_provider=descriptor.provider.value,
                media_type=descriptor.media_type,
                size_bytes=descriptor.size_bytes,
                sha256=descriptor.content_sha256,
                storage_key=descriptor.storage_key,
                status=status,
                detected_format=descriptor.source_format.value,
                parser_name=f"runcoach.{descriptor.source_format.value}",
                parser_version=parser_bundle_version,
                processed_at=datetime.now(UTC),
            )
            self._session.add(import_file)
            self._session.flush()

            persisted_files[
                _file_identity(
                    descriptor.provider,
                    descriptor.content_sha256,
                    descriptor.source_file_name,
                )
            ] = import_file

        return persisted_files, accepted_files, duplicate_files

    def _persist_activity(
        self,
        *,
        athlete: Athlete,
        reconciled: ReconciledActivity,
        import_files: dict[FileIdentity, ImportFile],
    ) -> tuple[bool, int]:
        existing_sources = {
            _reference_identity(representation.source): self._find_source_activity(representation)
            for representation in reconciled.representations
        }
        linked_activity_ids = {
            source_activity.activity_id
            for source_activity in existing_sources.values()
            if source_activity is not None and source_activity.activity_id is not None
        }

        if len(linked_activity_ids) > 1:
            raise IngestionPersistenceError(
                "Source representations are linked to conflicting canonical activities."
            )

        existing_activity_id = next(iter(linked_activity_ids), None)
        activity = (
            self._session.get(Activity, existing_activity_id)
            if existing_activity_id is not None
            else None
        )
        created = activity is None

        if activity is None:
            activity = Activity(
                athlete_id=athlete.id,
                sport="running",
                activity_type="unknown",
                name=reconciled.canonical.name,
                start_time_utc=reconciled.canonical.start_time_utc,
                original_timezone=reconciled.canonical.timezone_name,
                local_start_date=reconciled.canonical.start_time_utc.date(),
                distance_m=Decimal(0),
                moving_time_ms=0,
                elapsed_time_ms=0,
                verification_status="unverified",
            )
            self._session.add(activity)

        self._apply_canonical_values(
            activity,
            reconciled.canonical,
            athlete.timezone,
        )
        self._session.flush()

        source_records: dict[ReferenceIdentity, SourceActivity] = {}
        created_sources = 0

        for representation in reconciled.representations:
            reference_key = _reference_identity(representation.source)
            source_activity = existing_sources[reference_key]

            if source_activity is None:
                import_file = import_files.get(
                    _file_identity(
                        representation.source.provider,
                        representation.source.content_sha256,
                        representation.source.source_file_name,
                    )
                )
                if import_file is None:
                    raise IngestionPersistenceError(
                        "A source representation has no matching import file descriptor."
                    )

                source_activity = SourceActivity(
                    import_file_id=import_file.id,
                    provider=representation.source.provider.value,
                    external_activity_id=representation.source.source_activity_id,
                    source_start_time=representation.start_time_utc,
                    source_sport=representation.provider_activity_type,
                    source_distance_m=_decimal(representation.distance_m),
                    source_duration_ms=_milliseconds(representation.elapsed_time_s),
                    dedupe_fingerprint=_dedupe_fingerprint(representation),
                    resolution_status="canonical",
                    raw_metadata=_source_metadata(
                        representation,
                        reconciled.match_method,
                    ),
                )
                self._session.add(source_activity)
                created_sources += 1

            source_activity.activity_id = activity.id
            source_activity.resolution_status = "canonical"
            source_records[reference_key] = source_activity

        self._session.flush()
        self._persist_field_provenance(
            activity=activity,
            reconciled=reconciled,
            source_records=source_records,
        )
        return created, created_sources

    def _find_source_activity(
        self,
        activity: NormalizedActivity,
    ) -> SourceActivity | None:
        external_activity_id = activity.source.source_activity_id
        if external_activity_id is not None:
            existing = self._session.scalar(
                select(SourceActivity)
                .where(
                    SourceActivity.provider == activity.source.provider.value,
                    SourceActivity.external_activity_id == external_activity_id,
                )
                .limit(1)
            )
            if existing is not None:
                return existing

        return self._session.scalar(
            select(SourceActivity)
            .where(
                SourceActivity.provider == activity.source.provider.value,
                SourceActivity.dedupe_fingerprint == _dedupe_fingerprint(activity),
            )
            .limit(1)
        )

    def _apply_canonical_values(
        self,
        persisted: Activity,
        canonical: NormalizedActivity,
        athlete_timezone: str,
    ) -> None:
        distance, moving_time, elapsed_time = _required_measurements(canonical)

        persisted.name = canonical.name
        persisted.start_time_utc = canonical.start_time_utc
        persisted.original_timezone = canonical.timezone_name
        persisted.local_start_date = _local_start_date(
            canonical,
            athlete_timezone,
        )
        persisted.distance_m = distance
        persisted.moving_time_ms = moving_time
        persisted.elapsed_time_ms = elapsed_time
        persisted.elevation_gain_m = _decimal(canonical.elevation_gain_m)
        persisted.average_hr_bpm = _decimal(canonical.average_heart_rate_bpm)
        persisted.max_hr_bpm = canonical.maximum_heart_rate_bpm
        persisted.average_cadence_spm = _decimal(canonical.average_cadence_spm)
        persisted.calories_kcal = _decimal(canonical.calories_kcal)

    def _persist_field_provenance(
        self,
        *,
        activity: Activity,
        reconciled: ReconciledActivity,
        source_records: dict[ReferenceIdentity, SourceActivity],
    ) -> None:
        for provenance in reconciled.field_provenance:
            source_activity = source_records.get(_reference_identity(provenance.source))
            if source_activity is None:
                raise IngestionPersistenceError(
                    "Field provenance references an unknown source representation."
                )

            persisted = self._session.scalar(
                select(ActivityFieldSource)
                .where(
                    ActivityFieldSource.activity_id == activity.id,
                    ActivityFieldSource.field_name == provenance.field_name,
                )
                .limit(1)
            )
            if persisted is None:
                persisted = ActivityFieldSource(
                    activity_id=activity.id,
                    field_name=provenance.field_name,
                    source_activity_id=source_activity.id,
                    selection_reason=reconciled.match_method.value,
                )
                self._session.add(persisted)
            else:
                persisted.source_activity_id = source_activity.id
                persisted.selection_reason = reconciled.match_method.value

    def _persist_findings(
        self,
        *,
        batch: ImportBatch,
        result: ReconciliationResult,
    ) -> int:
        for finding in result.findings:
            observed_value = (
                {"source_row_number": finding.source_row_number}
                if finding.source_row_number is not None
                else None
            )
            self._session.add(
                DataQualityIssue(
                    import_batch_id=batch.id,
                    code=finding.code,
                    severity=finding.severity.value,
                    field_name=finding.field_name,
                    message=finding.message,
                    observed_value=observed_value,
                    resolution_status="open",
                )
            )

        return len(result.findings)
