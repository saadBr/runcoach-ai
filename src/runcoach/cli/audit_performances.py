"""Print standard-distance activity candidates for manual label verification."""

import argparse
import json
from dataclasses import asdict
from uuid import UUID

from runcoach.analytics.performance import DEFAULT_DISTANCE_TOLERANCE_PCT
from runcoach.config import get_settings
from runcoach.db.performance_audit import PerformanceAuditQueryService
from runcoach.db.session import SessionFactory


def _positive_tolerance(value: str) -> float:
    try:
        tolerance = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Tolerance must be numeric.") from error

    if not 0 < tolerance <= 10:
        raise argparse.ArgumentTypeError(
            "Tolerance must be greater than zero and at most 10 percent."
        )
    return tolerance


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "List whole running activities near standard race distances. "
            "Candidates still require human label verification."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--distance-tolerance-pct",
        type=_positive_tolerance,
        default=DEFAULT_DISTANCE_TOLERANCE_PCT,
        help="Maximum distance deviation percentage; defaults to 3.0.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run the read-only performance candidate audit."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    with SessionFactory() as session:
        audit = PerformanceAuditQueryService(session).audit(
            athlete_id=athlete_id,
            distance_tolerance_pct=parsed.distance_tolerance_pct,
        )

    print(
        json.dumps(
            asdict(audit),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
