"""Configure a time-valid athlete physiology profile."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from uuid import UUID

from runcoach.config import get_settings
from runcoach.db.physiology import (
    PhysiologyProfileInput,
    PhysiologyProfileService,
)
from runcoach.db.session import SessionFactory


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure a time-valid athlete physiology profile."
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument("--valid-from", type=_iso_date, required=True)
    parser.add_argument("--valid-to", type=_iso_date)
    parser.add_argument("--observed-max-hr", type=int)
    parser.add_argument("--resting-hr", type=int)
    parser.add_argument("--lactate-threshold-hr", type=int)
    parser.add_argument("--threshold-pace-seconds-per-km", type=int)
    parser.add_argument(
        "--notes",
        help="Short provenance or limitation note.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Validate and persist one physiology profile."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    profile_input = PhysiologyProfileInput(
        athlete_id=athlete_id,
        valid_from=parsed.valid_from,
        valid_to=parsed.valid_to,
        observed_max_hr_bpm=parsed.observed_max_hr,
        resting_hr_bpm=parsed.resting_hr,
        lactate_threshold_hr_bpm=parsed.lactate_threshold_hr,
        threshold_pace_seconds_per_km=(parsed.threshold_pace_seconds_per_km),
        notes=parsed.notes,
    )

    with SessionFactory() as session:
        result = PhysiologyProfileService(session).configure(profile_input)

    print(
        json.dumps(
            asdict(result),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
