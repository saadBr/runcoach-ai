"""Import standalone Strava FIT activities created after the last bulk export."""

import argparse
import gzip
import json
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from runcoach import __version__
from runcoach.config import get_settings
from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.models import Athlete
from runcoach.db.sensors import (
    SensorActivityInput,
    SensorPersistenceService,
)
from runcoach.db.session import SessionFactory
from runcoach.ingestion.contracts import (
    SourceProvider,
)
from runcoach.ingestion.fit import parse_fit_activity
from runcoach.ingestion.strava_fit import (
    RUNNING_ACTIVITY_KINDS,
    infer_activity_type,
    single_running_activity,
    title_from_filename,
)

RUNNING_KINDS = RUNNING_ACTIVITY_KINDS


class _BinaryReader(Protocol):
    def read(self, size: int = -1) -> bytes:
        """Read up to size bytes from the source."""


@dataclass(slots=True)
class CollectionStatistics:
    """Sanitized counts for direct Strava FIT discovery and parsing."""

    files_discovered: int = 0
    files_selected: int = 0
    known_files_skipped: int = 0
    bulk_export_files_skipped: int = 0
    files_before_since: int = 0
    non_running_files: int = 0
    parse_failures: int = 0
    parser_findings: int = 0


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import standalone Strava FIT downloads as canonical running activities "
            "with laps and trackpoints."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--activity-dir",
        type=Path,
        help=(
            "Directory containing Strava FIT downloads; defaults to "
            "data/private/strava/extracted/activities."
        ),
    )
    parser.add_argument(
        "--since",
        type=_iso_date,
        required=True,
        help="Import activities on or after this athlete-local date.",
    )
    return parser


def _fit_paths(activity_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in activity_dir.iterdir()
            if path.is_file()
            and (path.name.lower().endswith(".fit") or path.name.lower().endswith(".fit.gz"))
        ),
        key=lambda path: path.name.lower(),
    )


def _stream_sha256(stream: _BinaryReader) -> str:
    digest = sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(path: Path) -> str:
    if path.name.lower().endswith(".fit.gz"):
        with gzip.open(path, "rb") as stream:
            return _stream_sha256(stream)
    with path.open("rb") as stream:
        return _stream_sha256(stream)


def _is_bulk_export_fit(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".fit.gz") and name[:-7].isdigit()


def _collect_inputs(
    *,
    activity_dir: Path,
    athlete_id: UUID,
    athlete_timezone: ZoneInfo,
    since: date,
    known_content_sha256: frozenset[str] = frozenset(),
    skip_unseen_bulk_export_files: bool = False,
) -> tuple[tuple[SensorActivityInput, ...], CollectionStatistics]:
    statistics = CollectionStatistics()
    inputs: list[SensorActivityInput] = []
    paths = _fit_paths(activity_dir)
    statistics.files_discovered = len(paths)

    for path in paths:
        if _content_sha256(path) in known_content_sha256:
            statistics.known_files_skipped += 1
            continue
        if skip_unseen_bulk_export_files and _is_bulk_export_fit(path):
            statistics.bulk_export_files_skipped += 1
            continue

        result = parse_fit_activity(path, athlete_id, SourceProvider.STRAVA)
        statistics.parser_findings += len(result.findings)
        normalized = single_running_activity(result.activities)
        if normalized is None:
            if result.activities:
                statistics.non_running_files += 1
            else:
                statistics.parse_failures += 1
            continue

        local_date = normalized.start_time_utc.astimezone(athlete_timezone).date()
        if local_date < since:
            statistics.files_before_since += 1
            continue

        title = title_from_filename(path)
        normalized = normalized.model_copy(
            update={
                "name": title,
                "timezone_name": athlete_timezone.key,
                "source": normalized.source.model_copy(
                    update={"source_file_name": f"activities/{path.name}"}
                ),
            }
        )
        source_format = normalized.source.source_format
        inputs.append(
            SensorActivityInput(
                file=ImportFileDescriptor(
                    provider=SourceProvider.STRAVA,
                    source_format=source_format,
                    source_file_name=f"activities/{path.name}",
                    content_sha256=normalized.source.content_sha256,
                    storage_key=f"strava/activities/{path.name}",
                    size_bytes=path.stat().st_size,
                    media_type="application/octet-stream",
                ),
                activity=normalized,
                activity_type=infer_activity_type(title),
            )
        )

    statistics.files_selected = len(inputs)
    return tuple(inputs), statistics


# Compatibility aliases retained for callers and tests written before the upload workflow.
_title_from_filename = title_from_filename
_activity_type = infer_activity_type
_single_running_activity = single_running_activity


def main(arguments: list[str] | None = None) -> int:
    """Discover, parse, and persist standalone Strava FIT activities."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id
    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    activity_dir = parsed.activity_dir or (
        settings.private_data_dir / "strava" / "extracted" / "activities"
    )
    if not activity_dir.is_dir():
        parser.error("--activity-dir must be an existing directory.")

    with SessionFactory() as session:
        athlete = session.get(Athlete, athlete_id)
        if athlete is None:
            parser.error("The configured athlete does not exist. Import summaries first.")

        athlete_timezone = ZoneInfo(athlete.timezone)
        inputs, statistics = _collect_inputs(
            activity_dir=activity_dir,
            athlete_id=athlete_id,
            athlete_timezone=athlete_timezone,
            since=parsed.since,
        )
        if not inputs:
            parser.error("No running FIT activities matched the requested date range.")

        session.rollback()
        summary = SensorPersistenceService(session).persist(
            athlete_id=athlete_id,
            parser_bundle_version=f"runcoach-{__version__}",
            inputs=inputs,
            create_missing_strava_activities=True,
        )

    print(
        json.dumps(
            {
                "collection": asdict(statistics),
                "persistence": asdict(summary),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
