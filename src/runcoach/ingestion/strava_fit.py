"""Shared normalization rules for standalone Strava FIT activities."""

import re
from pathlib import Path
from typing import Literal

from runcoach.ingestion.contracts import ActivityKind, NormalizedActivity

type ActivityType = Literal["race", "workout", "easy", "long", "unknown", "other"]

RUNNING_ACTIVITY_KINDS = frozenset(
    {
        ActivityKind.RUNNING,
        ActivityKind.TRAIL_RUNNING,
        ActivityKind.TREADMILL_RUNNING,
    }
)


def title_from_filename(path: Path) -> str:
    """Derive a human-readable activity title from a downloaded FIT filename."""

    name = path.name
    if name.lower().endswith(".fit.gz"):
        name = name[:-7]
    elif name.lower().endswith(".fit"):
        name = name[:-4]

    name = re.sub(r" \(\d+\)$", "", name)
    return re.sub(r"_+", " ", name).strip()


def infer_activity_type(title: str) -> ActivityType:
    """Map an explicit Strava title to the persisted coarse activity type."""

    lowered = title.casefold()
    if "race" in lowered:
        return "race"
    if "long" in lowered:
        return "long"
    if "easy" in lowered or "aerobic" in lowered:
        return "easy"
    workout_markers = (
        "hill",
        "interval",
        "session",
        "tempo",
        "threshold",
        "time trial",
        "wu",
        "warm up",
    )
    if any(marker in lowered for marker in workout_markers):
        return "workout"
    return "unknown"


def single_running_activity(
    activities: tuple[NormalizedActivity, ...],
) -> NormalizedActivity | None:
    """Return the only running activity in a parsed FIT payload, if unambiguous."""

    running = [
        activity for activity in activities if activity.activity_kind in RUNNING_ACTIVITY_KINDS
    ]
    if len(running) != 1:
        return None
    return running[0]
