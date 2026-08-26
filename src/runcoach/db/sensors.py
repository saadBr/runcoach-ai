"""Transactional persistence for raw activity sensor data."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.models import (
    Activity,
    Athlete,
    DataQualityIssue,
    ImportBatch,
    ImportFile,
    Lap,
    SourceActivity,
    SourceActivityFile,
    Trackpoint,
)
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    SourceFormat,
    SourceProvider,
)

RUNNING_KINDS = frozenset(
    {
        ActivityKind.RUNNING,
        ActivityKind.TRAIL_RUNNING,
        ActivityKind.TREADMILL_RUNNING,
    }
)
FIT_FORMATS = frozenset({SourceFormat.FIT, SourceFormat.FIT_GZ})
TRACKPOINT_INSERT_CHUNK_SIZE = 5_000

type MatchStatus = Literal["matched", "unmatched", "ambiguous"]


class SensorPersistenceError(RuntimeError):
    """Raised when a raw sensor import cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class SensorActivityInput:
    """One parsed raw activity and its durable file descriptor."""

    file: ImportFileDescriptor
    activity: NormalizedActivity

    def __post_init__(self) -> None:
        if self.file.provider != self.activity.source.provider:
            raise ValueError("File and activity providers must match.")

        if self.file.source_format != self.activity.source.source_format:
            raise ValueError("File and activity source formats must match.")

        if self.file.content_sha256 != self.activity.source.content_sha256:
            raise ValueError("File and activity SHA-256 values must match.")

        if self.file.source_format not in FIT_FORMATS | {SourceFormat.GPX}:
            raise ValueError("Raw sensor persistence accepts only FIT, FIT.GZ, or GPX files.")

        if self.activity.activity_kind not in RUNNING_KINDS:
            raise ValueError("Raw sensor persistence accepts only running activities.")


@dataclass(frozen=True, slots=True)
class PersistedSensorImportSummary:
    """Aggregate result of one raw sensor persistence transaction."""

    import_batch_id: UUID
    total_files: int
    accepted_files: int
    duplicate_files: int
    matched_files: int
    unmatched_files: int
    ambiguous_files: int
    source_links_created: int
    activities_enriched: int
    activities_unchanged: int
    laps_written: int
    trackpoints_written: int
    quality_issues_created: int


@dataclass(frozen=True, slots=True)
class _SensorCandidate:
    """A raw activity resolved to its canonical and provider records."""

    input: SensorActivityInput
    canonical_activity: Activity
    source_activity: SourceActivity
    import_file: ImportFile


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _milliseconds(value: float | None) -> int | None:
    if value is None:
        return None

    milliseconds = Decimal(str(value)) * Decimal(1_000)
    return int(milliseconds.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _decimal(value: float | None, quantum: str = "0.001") -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value)).quantize(
        Decimal(quantum),
        rounding=ROUND_HALF_UP,
    )


def _file_role(source_format: SourceFormat) -> str:
    if source_format == SourceFormat.GPX:
        return "route"
    return "sensor"


def _media_type(source_format: SourceFormat) -> str:
    if source_format == SourceFormat.GPX:
        return "application/gpx+xml"
    return "application/octet-stream"


def _selection_priority(candidate: _SensorCandidate) -> int:
    provider = candidate.input.file.provider
    source_format = candidate.input.file.source_format

    if provider == SourceProvider.GARMIN and source_format in FIT_FORMATS:
        return 400

    if provider == SourceProvider.STRAVA and source_format in FIT_FORMATS:
        return 300

    if provider == SourceProvider.GARMIN and source_format == SourceFormat.GPX:
        return 200

    if provider == SourceProvider.STRAVA and source_format == SourceFormat.GPX:
        return 100

    return 0


def _is_compatible(
    raw_activity: NormalizedActivity,
    canonical_activity: Activity,
) -> bool:
    start_delta = abs(
        (
            _as_utc(raw_activity.start_time_utc) - _as_utc(canonical_activity.start_time_utc)
        ).total_seconds()
    )
    if start_delta > 2:
        return False

    raw_duration_ms = _milliseconds(raw_activity.elapsed_time_s)
    if raw_duration_ms is None:
        return False

    duration_tolerance_ms: int = max(
        60_000,
        round(canonical_activity.elapsed_time_ms * 0.02),
    )
    if abs(raw_duration_ms - canonical_activity.elapsed_time_ms) > duration_tolerance_ms:
        return False

    if raw_activity.distance_m is None:
        return False

    canonical_distance_m = float(canonical_activity.distance_m)
    distance_tolerance_m = max(50.0, canonical_distance_m * 0.005)
    return abs(raw_activity.distance_m - canonical_distance_m) <= distance_tolerance_m


class SensorPersistenceService:
    """Persist raw-file provenance and selected canonical sensor detail."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist(
        self,
        *,
        athlete_id: UUID,
        parser_bundle_version: str,
        inputs: tuple[SensorActivityInput, ...],
    ) -> PersistedSensorImportSummary:
        """Persist one atomic batch of parsed raw running activities."""

        if not inputs:
            raise ValueError("At least one raw sensor activity is required.")

        if any(item.activity.athlete_id != athlete_id for item in inputs):
            raise ValueError("Every raw activity must belong to the requested athlete.")

        try:
            with self._session.begin():
                return self._persist(
                    athlete_id=athlete_id,
                    parser_bundle_version=parser_bundle_version,
                    inputs=inputs,
                )
        except SensorPersistenceError:
            raise
        except Exception as error:
            raise SensorPersistenceError(
                "Raw sensor persistence failed and was rolled back."
            ) from error

    def _persist(
        self,
        *,
        athlete_id: UUID,
        parser_bundle_version: str,
        inputs: tuple[SensorActivityInput, ...],
    ) -> PersistedSensorImportSummary:
        if self._session.get(Athlete, athlete_id) is None:
            raise SensorPersistenceError(
                "The athlete must exist before raw sensor data can be imported."
            )

        now = _utc_now()
        batch = ImportBatch(
            athlete_id=athlete_id,
            status="processing",
            requested_at=now,
            started_at=now,
            retry_count=0,
            parser_bundle_version=parser_bundle_version,
            total_files=len(inputs),
            accepted_files=0,
            rejected_files=0,
            duplicate_files=0,
            warning_count=0,
        )
        self._session.add(batch)
        self._session.flush()

        canonical_activities = list(
            self._session.scalars(select(Activity).where(Activity.athlete_id == athlete_id))
        )
        canonical_by_id = {activity.id: activity for activity in canonical_activities}

        source_activities = list(
            self._session.scalars(
                select(SourceActivity)
                .join(Activity, SourceActivity.activity_id == Activity.id)
                .where(Activity.athlete_id == athlete_id)
            )
        )

        sources_by_external_id: dict[
            tuple[str, str],
            list[SourceActivity],
        ] = defaultdict(list)
        sources_by_activity_provider: dict[
            tuple[UUID, str],
            list[SourceActivity],
        ] = defaultdict(list)

        for source_activity in source_activities:
            if source_activity.external_activity_id is not None:
                sources_by_external_id[
                    (
                        source_activity.provider,
                        source_activity.external_activity_id,
                    )
                ].append(source_activity)

            if source_activity.activity_id is not None:
                sources_by_activity_provider[
                    (
                        source_activity.activity_id,
                        source_activity.provider,
                    )
                ].append(source_activity)

        accepted_files = 0
        duplicate_files = 0
        matched_files = 0
        unmatched_files = 0
        ambiguous_files = 0
        source_links_created = 0
        quality_issues_created = 0

        candidates_by_activity: dict[UUID, list[_SensorCandidate]] = defaultdict(list)

        for item in inputs:
            import_file, is_duplicate = self._register_file(
                batch=batch,
                descriptor=item.file,
                parser_bundle_version=parser_bundle_version,
                processed_at=now,
            )

            if is_duplicate:
                duplicate_files += 1
            else:
                accepted_files += 1

            status, canonical_activity, resolved_source_activity = self._resolve_activity(
                item=item,
                canonical_activities=canonical_activities,
                canonical_by_id=canonical_by_id,
                sources_by_external_id=sources_by_external_id,
                sources_by_activity_provider=sources_by_activity_provider,
            )

            if status == "unmatched":
                unmatched_files += 1
                self._record_matching_issue(
                    batch=batch,
                    item=item,
                    code="RAW_ACTIVITY_UNMATCHED",
                    message="Raw activity did not match exactly one canonical activity.",
                )
                quality_issues_created += 1
                continue

            if status == "ambiguous":
                ambiguous_files += 1
                self._record_matching_issue(
                    batch=batch,
                    item=item,
                    code="RAW_ACTIVITY_AMBIGUOUS",
                    message="Raw activity matched more than one canonical activity.",
                )
                quality_issues_created += 1
                continue

            if canonical_activity is None or resolved_source_activity is None:
                raise SensorPersistenceError("Matched activity resolution was incomplete.")

            matched_files += 1

            if self._ensure_source_file_link(
                source_activity=resolved_source_activity,
                import_file=import_file,
                file_role=_file_role(item.file.source_format),
            ):
                source_links_created += 1

            if not item.activity.laps and not item.activity.trackpoints:
                self._session.add(
                    DataQualityIssue(
                        import_batch_id=batch.id,
                        source_activity_id=resolved_source_activity.id,
                        activity_id=canonical_activity.id,
                        code="RAW_ACTIVITY_HAS_NO_DETAIL",
                        severity="warning",
                        field_name=None,
                        message="Matched raw activity contained no laps or trackpoints.",
                        observed_value=item.file.source_format.value,
                        resolution_status="open",
                    )
                )
                quality_issues_created += 1
                continue

            candidates_by_activity[canonical_activity.id].append(
                _SensorCandidate(
                    input=item,
                    canonical_activity=canonical_activity,
                    source_activity=resolved_source_activity,
                    import_file=import_file,
                )
            )

        activities_enriched = 0
        activities_unchanged = 0
        laps_written = 0
        trackpoints_written = 0

        for candidates in candidates_by_activity.values():
            selected = sorted(
                candidates,
                key=lambda candidate: (
                    -_selection_priority(candidate),
                    -len(candidate.input.activity.trackpoints),
                    -len(candidate.input.activity.laps),
                    candidate.input.file.content_sha256,
                ),
            )[0]

            changed, written_laps, written_trackpoints = self._persist_selection(
                selected=selected,
                selected_at=now,
            )

            if changed:
                activities_enriched += 1
                laps_written += written_laps
                trackpoints_written += written_trackpoints
            else:
                activities_unchanged += 1

        batch.status = "completed_with_warnings" if quality_issues_created > 0 else "completed"
        batch.completed_at = _utc_now()
        batch.accepted_files = accepted_files
        batch.duplicate_files = duplicate_files
        batch.warning_count = quality_issues_created

        self._session.flush()

        return PersistedSensorImportSummary(
            import_batch_id=batch.id,
            total_files=len(inputs),
            accepted_files=accepted_files,
            duplicate_files=duplicate_files,
            matched_files=matched_files,
            unmatched_files=unmatched_files,
            ambiguous_files=ambiguous_files,
            source_links_created=source_links_created,
            activities_enriched=activities_enriched,
            activities_unchanged=activities_unchanged,
            laps_written=laps_written,
            trackpoints_written=trackpoints_written,
            quality_issues_created=quality_issues_created,
        )

    def _register_file(
        self,
        *,
        batch: ImportBatch,
        descriptor: ImportFileDescriptor,
        parser_bundle_version: str,
        processed_at: datetime,
    ) -> tuple[ImportFile, bool]:
        existing_file = self._session.scalars(
            select(ImportFile)
            .where(
                ImportFile.source_provider == descriptor.provider.value,
                ImportFile.sha256 == descriptor.content_sha256,
                ImportFile.status == "accepted",
            )
            .order_by(ImportFile.processed_at, ImportFile.id)
        ).first()

        current_file = ImportFile(
            import_batch_id=batch.id,
            original_name=descriptor.source_file_name,
            source_provider=descriptor.provider.value,
            media_type=descriptor.media_type or _media_type(descriptor.source_format),
            size_bytes=descriptor.size_bytes,
            sha256=descriptor.content_sha256,
            storage_key=descriptor.storage_key,
            status="duplicate" if existing_file is not None else "accepted",
            detected_format=descriptor.source_format.value,
            parser_name="raw-activity-adapter",
            parser_version=parser_bundle_version,
            processed_at=processed_at,
        )
        self._session.add(current_file)
        self._session.flush()

        if existing_file is not None:
            return existing_file, True

        return current_file, False

    def _resolve_activity(
        self,
        *,
        item: SensorActivityInput,
        canonical_activities: list[Activity],
        canonical_by_id: dict[UUID, Activity],
        sources_by_external_id: dict[
            tuple[str, str],
            list[SourceActivity],
        ],
        sources_by_activity_provider: dict[
            tuple[UUID, str],
            list[SourceActivity],
        ],
    ) -> tuple[MatchStatus, Activity | None, SourceActivity | None]:
        provider = item.file.provider.value
        external_id = item.activity.source.source_activity_id

        if external_id is not None:
            external_matches = sources_by_external_id.get(
                (provider, external_id),
                [],
            )

            if len(external_matches) > 1:
                return "ambiguous", None, None

            if len(external_matches) == 1:
                source_activity = external_matches[0]
                if source_activity.activity_id is None:
                    return "unmatched", None, None

                canonical_activity = canonical_by_id.get(source_activity.activity_id)
                if canonical_activity is None:
                    return "unmatched", None, None

                return "matched", canonical_activity, source_activity

        compatible_activities = [
            activity for activity in canonical_activities if _is_compatible(item.activity, activity)
        ]

        if not compatible_activities:
            return "unmatched", None, None

        if len(compatible_activities) > 1:
            return "ambiguous", None, None

        canonical_activity = compatible_activities[0]
        provider_sources = sources_by_activity_provider.get(
            (canonical_activity.id, provider),
            [],
        )

        if not provider_sources:
            return "unmatched", None, None

        if len(provider_sources) > 1:
            return "ambiguous", None, None

        return "matched", canonical_activity, provider_sources[0]

    def _ensure_source_file_link(
        self,
        *,
        source_activity: SourceActivity,
        import_file: ImportFile,
        file_role: str,
    ) -> bool:
        existing_link = self._session.scalar(
            select(SourceActivityFile).where(
                SourceActivityFile.source_activity_id == source_activity.id,
                SourceActivityFile.import_file_id == import_file.id,
                SourceActivityFile.file_role == file_role,
            )
        )
        if existing_link is not None:
            return False

        self._session.add(
            SourceActivityFile(
                source_activity_id=source_activity.id,
                import_file_id=import_file.id,
                file_role=file_role,
            )
        )
        return True

    def _record_matching_issue(
        self,
        *,
        batch: ImportBatch,
        item: SensorActivityInput,
        code: str,
        message: str,
    ) -> None:
        observed_value = (
            f"provider={item.file.provider.value};"
            f"format={item.file.source_format.value};"
            f"start={item.activity.start_time_utc.isoformat()}"
        )
        self._session.add(
            DataQualityIssue(
                import_batch_id=batch.id,
                source_activity_id=None,
                activity_id=None,
                code=code,
                severity="warning",
                field_name="start_time_utc",
                message=message,
                observed_value=observed_value,
                resolution_status="open",
            )
        )

    def _persist_selection(
        self,
        *,
        selected: _SensorCandidate,
        selected_at: datetime,
    ) -> tuple[bool, int, int]:
        canonical_activity = selected.canonical_activity
        source_activity = selected.source_activity
        normalized = selected.input.activity
        selected_sha256 = selected.input.file.content_sha256

        metadata = dict(source_activity.raw_metadata or {})
        selection_is_unchanged = (
            canonical_activity.canonical_sensor_source_id == source_activity.id
            and metadata.get("canonical_sensor_sha256") == selected_sha256
        )
        if selection_is_unchanged:
            return False, 0, 0

        self._clear_previous_selection(canonical_activity)

        self._session.execute(delete(Lap).where(Lap.activity_id == canonical_activity.id))
        self._session.execute(
            delete(Trackpoint).where(Trackpoint.activity_id == canonical_activity.id)
        )

        lap_rows: list[dict[str, Any]] = []
        for lap in normalized.laps:
            lap_rows.append(
                {
                    "activity_id": canonical_activity.id,
                    "lap_index": lap.sequence,
                    "start_time_utc": lap.start_time_utc,
                    "distance_m": _decimal(lap.distance_m),
                    "moving_time_ms": _milliseconds(lap.moving_time_s),
                    "elapsed_time_ms": _milliseconds(lap.elapsed_time_s),
                    "elevation_gain_m": _decimal(lap.elevation_gain_m),
                    "average_hr_bpm": _decimal(
                        lap.average_heart_rate_bpm,
                        "0.01",
                    ),
                    "max_hr_bpm": lap.maximum_heart_rate_bpm,
                    "average_cadence_spm": _decimal(lap.average_cadence_spm),
                }
            )

        if lap_rows:
            self._session.execute(insert(Lap), lap_rows)

        trackpoint_rows: list[dict[str, Any]] = []
        for trackpoint in normalized.trackpoints:
            elapsed_time_s = trackpoint.elapsed_time_s
            if elapsed_time_s is None:
                elapsed_time_s = max(
                    0.0,
                    (
                        _as_utc(trackpoint.timestamp_utc) - _as_utc(normalized.start_time_utc)
                    ).total_seconds(),
                )

            elapsed_ms = _milliseconds(elapsed_time_s)
            if elapsed_ms is None:
                raise SensorPersistenceError("Trackpoint elapsed time could not be derived.")
            trackpoint_rows.append(
                {
                    "activity_id": canonical_activity.id,
                    "sequence_number": trackpoint.sequence,
                    "recorded_at": trackpoint.timestamp_utc,
                    "elapsed_ms": elapsed_ms,
                    "distance_m": _decimal(trackpoint.distance_m),
                    "latitude": _decimal(
                        trackpoint.latitude_deg,
                        "0.000001",
                    ),
                    "longitude": _decimal(
                        trackpoint.longitude_deg,
                        "0.000001",
                    ),
                    "altitude_m": _decimal(trackpoint.altitude_m),
                    "heart_rate_bpm": trackpoint.heart_rate_bpm,
                    "cadence_spm": _decimal(trackpoint.cadence_spm),
                    "speed_mps": _decimal(trackpoint.speed_mps),
                    "power_watts": _decimal(trackpoint.power_watts),
                    "temperature_c": _decimal(
                        trackpoint.temperature_c,
                        "0.01",
                    ),
                    "is_paused": False,
                }
            )

        for start in range(
            0,
            len(trackpoint_rows),
            TRACKPOINT_INSERT_CHUNK_SIZE,
        ):
            chunk = trackpoint_rows[start : start + TRACKPOINT_INSERT_CHUNK_SIZE]
            self._session.execute(insert(Trackpoint), chunk)

        metadata.update(
            {
                "canonical_sensor_sha256": selected_sha256,
                "canonical_sensor_format": (selected.input.file.source_format.value),
                "canonical_sensor_file_name": (selected.input.file.source_file_name),
                "canonical_sensor_selected_at": selected_at.isoformat(),
                "sensor_lap_count": len(lap_rows),
                "sensor_trackpoint_count": len(trackpoint_rows),
            }
        )
        source_activity.raw_metadata = metadata
        canonical_activity.canonical_sensor_source_id = source_activity.id
        canonical_activity.updated_at = selected_at

        return True, len(lap_rows), len(trackpoint_rows)

    def _clear_previous_selection(
        self,
        canonical_activity: Activity,
    ) -> None:
        previous_source_id = canonical_activity.canonical_sensor_source_id
        if previous_source_id is None:
            return

        previous_source = self._session.get(
            SourceActivity,
            previous_source_id,
        )
        if previous_source is None:
            return

        previous_metadata = dict(previous_source.raw_metadata or {})
        for key in (
            "canonical_sensor_sha256",
            "canonical_sensor_format",
            "canonical_sensor_file_name",
            "canonical_sensor_selected_at",
            "sensor_lap_count",
            "sensor_trackpoint_count",
        ):
            previous_metadata.pop(key, None)

        previous_source.raw_metadata = previous_metadata
