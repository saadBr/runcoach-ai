"""Application service for preparing one private Strava FIT upload."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.sensors import SensorActivityInput
from runcoach.ingestion.contracts import NormalizedActivity, SourceProvider
from runcoach.ingestion.fit import parse_fit_activity
from runcoach.ingestion.strava_fit import infer_activity_type, single_running_activity


class RunUploadValidationError(ValueError):
    """Raised when an uploaded payload is not one valid running FIT activity."""


@dataclass(frozen=True, slots=True)
class PreparedRunUpload:
    """Parsed run evidence ready for idempotent persistence."""

    input: SensorActivityInput
    activity: NormalizedActivity
    parser_findings: int


def prepare_strava_fit_upload(
    *,
    path: Path,
    filename: str,
    title: str,
    size_bytes: int,
    athlete_id: UUID,
    athlete_timezone: ZoneInfo,
) -> PreparedRunUpload:
    """Parse and normalize one staged Strava FIT or FIT.GZ upload."""

    result = parse_fit_activity(path, athlete_id, SourceProvider.STRAVA)
    normalized = single_running_activity(result.activities)
    if normalized is None:
        if result.activities:
            raise RunUploadValidationError(
                "The uploaded FIT file does not contain exactly one running activity."
            )
        raise RunUploadValidationError("The uploaded FIT file could not be parsed as an activity.")

    source_name = f"uploads/{filename}"
    normalized = normalized.model_copy(
        update={
            "name": title,
            "timezone_name": athlete_timezone.key,
            "source": normalized.source.model_copy(update={"source_file_name": source_name}),
        }
    )
    source_format = normalized.source.source_format
    sensor_input = SensorActivityInput(
        file=ImportFileDescriptor(
            provider=SourceProvider.STRAVA,
            source_format=source_format,
            source_file_name=source_name,
            content_sha256=normalized.source.content_sha256,
            storage_key=f"strava/uploads/{normalized.source.content_sha256}",
            size_bytes=size_bytes,
            media_type="application/octet-stream",
        ),
        activity=normalized,
        activity_type=infer_activity_type(title),
    )
    return PreparedRunUpload(
        input=sensor_input,
        activity=normalized,
        parser_findings=len(result.findings),
    )
