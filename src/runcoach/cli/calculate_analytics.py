"""Calculate and persist deterministic running analytics."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from uuid import UUID

from runcoach.config import get_settings
from runcoach.db.analytics import DeterministicAnalyticsService
from runcoach.db.session import SessionFactory


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate versioned activity metrics and daily workload "
            "indicators from canonical running data."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--as-of-date",
        type=_iso_date,
        required=True,
        help=("Last local date included in the workload series, using YYYY-MM-DD format."),
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run deterministic analytics for one athlete."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    with SessionFactory() as session:
        summary = DeterministicAnalyticsService(session).calculate(
            athlete_id=athlete_id,
            as_of_date=parsed.as_of_date,
        )

    print(
        json.dumps(
            asdict(summary),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
