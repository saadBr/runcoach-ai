"""Print experimental training-supported race goal ranges."""

import argparse
import json
from dataclasses import asdict
from datetime import date
from uuid import UUID

from runcoach.analytics.performance import StandardDistance
from runcoach.config import get_settings
from runcoach.db.goal_assessments import GoalAssessmentQueryService
from runcoach.db.session import SessionFactory


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare current training with the 42-day build before each verified PB and "
            "print experimental achievable-time ranges."
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
        help="Evidence cutoff in YYYY-MM-DD; defaults to the latest workload date.",
    )
    parser.add_argument(
        "--distance",
        type=StandardDistance,
        choices=tuple(StandardDistance),
        help="Optional single distance; defaults to every supported distance.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run the read-only personalized goal assessment."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id
    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    with SessionFactory() as session:
        report = GoalAssessmentQueryService(session).assess(
            athlete_id=athlete_id,
            as_of_date=parsed.as_of_date,
        )

    payload = asdict(report)
    if parsed.distance is not None:
        payload["assessments"] = [
            assessment
            for assessment in payload["assessments"]
            if assessment["distance"] == parsed.distance
        ]
        if not payload["assessments"]:
            parser.error(f"No assessment is available for {parsed.distance.value}.")

    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
