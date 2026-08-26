"""Import raw Garmin and Strava running files into canonical sensor storage."""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach import __version__
from runcoach.config import get_settings
from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.models import Activity, SourceActivity
from runcoach.db.sensors import (
    SensorActivityInput,
    SensorPersistenceService,
)
from runcoach.db.session import SessionFactory
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    ParseResult,
    SourceFormat,
    SourceProvider,
)
from runcoach.ingestion.fit import parse_fit_activity
from runcoach.ingestion.gpx import parse_gpx_activity


@dataclass(slots=True)
class CollectionStatistics:
    """Sanitized aggregate statistics from raw-file discovery and parsing."""

    strava_references: int = 0
    strava_files_parsed: int = 0
    strava_missing_files: int = 0
    strava_parse_failures: int = 0
    garmin_fit_files_discovered: int = 0
    garmin_fit_files_scanned: int = 0
    garmin_running_files: int = 0
    garmin_ignored_files: int = 0
    garmin_parse_failures: int = 0
    parser_findings: int = 0
    duplicate_inputs_skipped: int = 0
    total_inputs: int = 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover private raw Garmin and Strava files, parse running "
            "activities, and persist canonical laps and trackpoints."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--strava-root",
        type=Path,
        help="Root of the extracted Strava bulk export.",
    )
    parser.add_argument(
        "--garmin-root",
        type=Path,
        help="Root of the extracted Garmin export.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=250,
        help="Report aggregate Garmin scan progress every N files.",
    )
    return parser


def _detect_format(path: Path) -> SourceFormat | None:
    lower_name = path.name.lower()

    if lower_name.endswith(".fit.gz"):
        return SourceFormat.FIT_GZ
    if lower_name.endswith(".fit"):
        return SourceFormat.FIT
    if lower_name.endswith(".gpx"):
        return SourceFormat.GPX
    return None


def _activity_kind(value: str) -> ActivityKind:
    try:
        activity_kind = ActivityKind(value)
    except ValueError:
        return ActivityKind.RUNNING

    if activity_kind == ActivityKind.OTHER:
        return ActivityKind.RUNNING
    return activity_kind


def _source_row_number(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("source_row_number")

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None

    return None


def _safe_referenced_path(
    root: Path,
    referenced_file_name: str,
) -> Path | None:
    logical_path = PurePosixPath(referenced_file_name)
    if (
        logical_path.is_absolute()
        or ".." in logical_path.parts
        or any(":" in part for part in logical_path.parts)
    ):
        return None

    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*logical_path.parts).resolve()

    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return None

    return candidate


def _single_running_activity(
    result: ParseResult,
) -> NormalizedActivity | None:
    running_activities = [
        activity
        for activity in result.activities
        if activity.activity_kind
        in {
            ActivityKind.RUNNING,
            ActivityKind.TRAIL_RUNNING,
            ActivityKind.TREADMILL_RUNNING,
        }
    ]

    if len(running_activities) != 1:
        return None

    return running_activities[0]


def _descriptor(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    root: Path,
    path: Path,
    activity: NormalizedActivity,
) -> ImportFileDescriptor:
    relative_path = path.resolve().relative_to(root.resolve()).as_posix()
    return ImportFileDescriptor(
        provider=provider,
        source_format=source_format,
        source_file_name=relative_path,
        content_sha256=activity.source.content_sha256,
        storage_key=f"{provider.value}/{relative_path}",
        size_bytes=path.stat().st_size,
        media_type=None,
    )


def _collect_strava_inputs(
    *,
    session: Session,
    athlete_id: UUID,
    root: Path,
    statistics: CollectionStatistics,
) -> list[SensorActivityInput]:
    rows = session.execute(
        select(SourceActivity, Activity)
        .join(Activity, SourceActivity.activity_id == Activity.id)
        .where(
            Activity.athlete_id == athlete_id,
            SourceActivity.provider == SourceProvider.STRAVA.value,
        )
        .order_by(Activity.start_time_utc)
    ).all()

    inputs: list[SensorActivityInput] = []

    for source_activity, canonical_activity in rows:
        metadata = dict(source_activity.raw_metadata or {})
        referenced_file_name = metadata.get("referenced_file_name")

        if not isinstance(referenced_file_name, str) or not referenced_file_name:
            continue

        statistics.strava_references += 1
        source_path = _safe_referenced_path(root, referenced_file_name)
        if source_path is None or not source_path.is_file():
            statistics.strava_missing_files += 1
            continue

        source_format = _detect_format(source_path)
        if source_format is None:
            statistics.strava_parse_failures += 1
            continue

        try:
            if source_format in {SourceFormat.FIT, SourceFormat.FIT_GZ}:
                result = parse_fit_activity(
                    source_path,
                    athlete_id,
                    SourceProvider.STRAVA,
                    source_activity_id=source_activity.external_activity_id,
                    source_row_number=_source_row_number(metadata),
                    activity_kind_override=_activity_kind(canonical_activity.sport),
                )
            else:
                result = parse_gpx_activity(
                    source_path,
                    athlete_id,
                    activity_kind=_activity_kind(canonical_activity.sport),
                    source_activity_id=source_activity.external_activity_id,
                    source_row_number=_source_row_number(metadata),
                )
        except Exception:
            statistics.strava_parse_failures += 1
            continue

        statistics.parser_findings += len(result.findings)
        activity = _single_running_activity(result)
        if activity is None:
            statistics.strava_parse_failures += 1
            continue

        statistics.strava_files_parsed += 1
        inputs.append(
            SensorActivityInput(
                file=_descriptor(
                    provider=SourceProvider.STRAVA,
                    source_format=source_format,
                    root=root,
                    path=source_path,
                    activity=activity,
                ),
                activity=activity,
            )
        )

    return inputs


def _garmin_fit_paths(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.name.lower().endswith(".fit")),
        key=lambda path: path.as_posix().lower(),
    )


def _collect_garmin_inputs(
    *,
    athlete_id: UUID,
    root: Path,
    statistics: CollectionStatistics,
    progress_every: int,
    progress_callback: Callable[[int, int], None] | None,
) -> list[SensorActivityInput]:
    paths = _garmin_fit_paths(root)
    statistics.garmin_fit_files_discovered = len(paths)
    inputs: list[SensorActivityInput] = []

    for index, source_path in enumerate(paths, start=1):
        statistics.garmin_fit_files_scanned += 1

        try:
            result = parse_fit_activity(
                source_path,
                athlete_id,
                SourceProvider.GARMIN,
            )
        except Exception:
            statistics.garmin_parse_failures += 1
            continue

        statistics.parser_findings += len(result.findings)
        activity = _single_running_activity(result)

        if activity is None:
            statistics.garmin_ignored_files += 1
        else:
            statistics.garmin_running_files += 1
            inputs.append(
                SensorActivityInput(
                    file=_descriptor(
                        provider=SourceProvider.GARMIN,
                        source_format=SourceFormat.FIT,
                        root=root,
                        path=source_path,
                        activity=activity,
                    ),
                    activity=activity,
                )
            )

        if progress_callback is not None and (index % progress_every == 0 or index == len(paths)):
            progress_callback(index, len(paths))

    return inputs


def _deduplicate_inputs(
    inputs: list[SensorActivityInput],
    statistics: CollectionStatistics,
) -> tuple[SensorActivityInput, ...]:
    unique_inputs: list[SensorActivityInput] = []
    seen: set[tuple[SourceProvider, str]] = set()

    for item in inputs:
        identity = (
            item.file.provider,
            item.file.content_sha256,
        )
        if identity in seen:
            statistics.duplicate_inputs_skipped += 1
            continue

        seen.add(identity)
        unique_inputs.append(item)

    statistics.total_inputs = len(unique_inputs)
    return tuple(unique_inputs)


def _progress(completed: int, total: int) -> None:
    print(
        f"GARMIN_SCAN={completed}/{total}",
        file=sys.stderr,
        flush=True,
    )


def main(arguments: list[str] | None = None) -> int:
    """Run raw-file discovery, parsing, reconciliation, and persistence."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    if parsed.strava_root is None and parsed.garmin_root is None:
        parser.error("Provide at least one raw export root.")

    if parsed.progress_every <= 0:
        parser.error("--progress-every must be greater than zero.")

    if parsed.strava_root is not None and not parsed.strava_root.is_dir():
        parser.error("--strava-root must be an existing directory.")

    if parsed.garmin_root is not None and not parsed.garmin_root.is_dir():
        parser.error("--garmin-root must be an existing directory.")

    statistics = CollectionStatistics()

    with SessionFactory() as session:
        inputs: list[SensorActivityInput] = []

        if parsed.strava_root is not None:
            inputs.extend(
                _collect_strava_inputs(
                    session=session,
                    athlete_id=athlete_id,
                    root=parsed.strava_root,
                    statistics=statistics,
                )
            )

        if parsed.garmin_root is not None:
            inputs.extend(
                _collect_garmin_inputs(
                    athlete_id=athlete_id,
                    root=parsed.garmin_root,
                    statistics=statistics,
                    progress_every=parsed.progress_every,
                    progress_callback=_progress,
                )
            )

        unique_inputs = _deduplicate_inputs(inputs, statistics)

        if not unique_inputs:
            parser.error("No parseable running activity files were found.")

        # Read-only discovery may have opened an implicit transaction.
        session.rollback()

        summary = SensorPersistenceService(session).persist(
            athlete_id=athlete_id,
            parser_bundle_version=__version__,
            inputs=unique_inputs,
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
