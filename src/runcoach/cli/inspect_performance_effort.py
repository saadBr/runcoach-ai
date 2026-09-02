"""Inspect trackpoint evidence for one verified standard-distance performance."""

import argparse
import json
from dataclasses import asdict
from uuid import UUID

from runcoach.analytics.performance import StandardDistance
from runcoach.config import get_settings
from runcoach.db.performance_audit import PerformanceAuditQueryService
from runcoach.db.session import SessionFactory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a recorded activity total with its interpolated standard-distance crossing."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--activity-id",
        type=UUID,
        required=True,
        help="Canonical activity UUID to inspect.",
    )
    parser.add_argument(
        "--distance",
        type=StandardDistance,
        choices=tuple(StandardDistance),
        required=True,
        help="Standard distance to derive from cumulative trackpoints.",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Print one privacy-minimized evidence result as JSON."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id

    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    with SessionFactory() as session:
        evidence = PerformanceAuditQueryService(session).evidence(
            athlete_id=athlete_id,
            activity_id=parsed.activity_id,
            target_distance=parsed.distance,
        )

    print(
        json.dumps(
            asdict(evidence),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
