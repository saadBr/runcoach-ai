"""Import and reconcile Garmin and Strava activity summaries."""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from runcoach import __version__
from runcoach.config import get_settings
from runcoach.db.ingestion import (
    ImportFileDescriptor,
    ReconciliationPersistenceService,
)
from runcoach.db.session import SessionFactory
from runcoach.ingestion.contracts import (
    ParseResult,
    SourceFormat,
    SourceProvider,
)
from runcoach.ingestion.garmin_json import parse_garmin_activity_summaries
from runcoach.ingestion.reconciliation import (
    ReconciliationResult,
    reconcile_activity_summaries,
)
from runcoach.ingestion.strava_csv import parse_strava_activities_csv


def _existing_file(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError("File does not exist or is not a file.")
    return path


def _content_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_hashes(
    result: ParseResult,
    expected_hash: str,
) -> None:
    observed_hashes = {activity.source.content_sha256 for activity in result.activities}
    if observed_hashes and observed_hashes != {expected_hash}:
        raise RuntimeError("Parser source hashes do not match the imported file.")


def _descriptor(
    *,
    path: Path,
    provider: SourceProvider,
    source_format: SourceFormat,
    storage_key: str,
    media_type: str,
) -> ImportFileDescriptor:
    return ImportFileDescriptor(
        provider=provider,
        source_format=source_format,
        source_file_name=path.name,
        content_sha256=_content_sha256(path),
        storage_key=storage_key,
        size_bytes=path.stat().st_size,
        media_type=media_type,
    )


def _combine_findings(
    *,
    strava_result: ParseResult,
    garmin_result: ParseResult,
    reconciliation: ReconciliationResult,
) -> ReconciliationResult:
    return reconciliation.model_copy(
        update={
            "findings": (
                *strava_result.findings,
                *garmin_result.findings,
                *reconciliation.findings,
            )
        }
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse private Garmin and Strava summary exports, reconcile running "
            "activities, and persist the canonical result."
        )
    )
    parser.add_argument(
        "--athlete-id",
        required=False,
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--timezone",
        required=True,
        help="Athlete IANA timezone, for example Africa/Casablanca.",
    )
    parser.add_argument(
        "--strava-csv",
        required=True,
        type=_existing_file,
        help="Path to the extracted Strava activities.csv file.",
    )
    parser.add_argument(
        "--garmin-json",
        required=True,
        type=_existing_file,
        help="Path to the Garmin summarizedActivities JSON file.",
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="Optional private display name or pseudonym.",
    )
    return parser


def main() -> int:
    """Execute the private summary import command."""

    argument_parser = _build_argument_parser()
    arguments = argument_parser.parse_args()
    settings = get_settings()
    athlete_id = arguments.athlete_id or settings.athlete_id

    if athlete_id is None:
        argument_parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    strava_descriptor = _descriptor(
        path=arguments.strava_csv,
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        storage_key="strava/activities.csv",
        media_type="text/csv",
    )
    garmin_descriptor = _descriptor(
        path=arguments.garmin_json,
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        storage_key="garmin/summarized-activities.json",
        media_type="application/json",
    )

    strava_result = parse_strava_activities_csv(
        arguments.strava_csv,
        athlete_id,
    )
    garmin_result = parse_garmin_activity_summaries(
        arguments.garmin_json,
        athlete_id,
    )

    _validate_source_hashes(
        strava_result,
        strava_descriptor.content_sha256,
    )
    _validate_source_hashes(
        garmin_result,
        garmin_descriptor.content_sha256,
    )

    reconciliation = reconcile_activity_summaries(
        strava_activities=strava_result.activities,
        garmin_activities=garmin_result.activities,
    )
    reconciliation = _combine_findings(
        strava_result=strava_result,
        garmin_result=garmin_result,
        reconciliation=reconciliation,
    )

    if not reconciliation.activities:
        raise RuntimeError("No canonical running activities were produced.")

    with SessionFactory() as session:
        summary = ReconciliationPersistenceService(session).persist(
            athlete_id=athlete_id,
            athlete_timezone=arguments.timezone,
            athlete_display_name=arguments.display_name,
            parser_bundle_version=f"runcoach-{__version__}",
            files=(strava_descriptor, garmin_descriptor),
            result=reconciliation,
        )

    output = asdict(summary)
    output["import_batch_id"] = str(summary.import_batch_id)
    output["canonical_running_activities"] = len(reconciliation.activities)
    output["excluded_strava_representations"] = reconciliation.excluded_strava_representations
    output["excluded_garmin_representations"] = reconciliation.excluded_garmin_representations

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
