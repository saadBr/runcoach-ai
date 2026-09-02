"""Record one Strava-verified standard-distance personal best."""

import argparse
import json
from dataclasses import asdict
from uuid import UUID

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.config import get_settings
from runcoach.db.personal_bests import PersonalBestInput, PersonalBestService
from runcoach.db.session import SessionFactory


def _elapsed_time_ms(value: str) -> int:
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("Time must use MM:SS or HH:MM:SS format.")

    try:
        numbers = tuple(int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Time components must be integers.") from error

    if any(number < 0 for number in numbers) or numbers[-1] >= 60:
        raise argparse.ArgumentTypeError("Time components are outside the valid range.")
    if len(numbers) == 3 and numbers[1] >= 60:
        raise argparse.ArgumentTypeError("Time components are outside the valid range.")

    if len(numbers) == 2:
        minutes, seconds = numbers
        total_seconds = minutes * 60 + seconds
    else:
        hours, minutes, seconds = numbers
        total_seconds = hours * 3_600 + minutes * 60 + seconds

    if total_seconds <= 0:
        raise argparse.ArgumentTypeError("Elapsed time must be positive.")
    return total_seconds * 1_000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record one Strava-verified standard-distance personal best."
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument("--activity-id", type=UUID, required=True)
    parser.add_argument(
        "--distance",
        type=StandardDistance,
        choices=tuple(StandardDistance),
        required=True,
    )
    parser.add_argument("--time", type=_elapsed_time_ms, required=True)
    parser.add_argument(
        "--label",
        type=PerformanceLabel,
        choices=tuple(PerformanceLabel),
        required=True,
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Persist one verified personal-best result."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    with SessionFactory() as session:
        result = PersonalBestService(session).record(
            PersonalBestInput(
                athlete_id=athlete_id,
                activity_id=parsed.activity_id,
                distance=parsed.distance,
                elapsed_time_ms=parsed.time,
                label=parsed.label,
            )
        )

    print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
