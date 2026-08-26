"""Deterministic cross-source activity reconciliation."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    SourceReference,
    ValidationFinding,
)

_START_TOLERANCE_S = 2.0
_DURATION_TOLERANCE_S = 30.0
_MIN_DISTANCE_TOLERANCE_M = 50.0
_DISTANCE_TOLERANCE_RATIO = 0.005

_RUNNING_KINDS = {
    ActivityKind.RUNNING,
    ActivityKind.TRAIL_RUNNING,
    ActivityKind.TREADMILL_RUNNING,
}

_OPTIONAL_MERGE_FIELDS = (
    "timezone_name",
    "name",
    "moving_time_s",
    "distance_m",
    "elevation_gain_m",
    "elevation_loss_m",
    "average_speed_mps",
    "maximum_speed_mps",
    "average_heart_rate_bpm",
    "maximum_heart_rate_bpm",
    "minimum_heart_rate_bpm",
    "average_cadence_spm",
    "maximum_cadence_spm",
    "calories_kcal",
    "steps",
    "provider_vo2max",
    "provider_aerobic_training_effect",
    "provider_anaerobic_training_effect",
    "provider_training_effect_label",
    "laps",
    "trackpoints",
)


class MatchMethod(StrEnum):
    """Method that produced one canonical activity."""

    SINGLE_SOURCE = "single_source"
    CROSS_SOURCE_STRONG = "cross_source_strong"


class ReconciliationModel(BaseModel):
    """Strict immutable base for reconciliation outputs."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class FieldProvenance(ReconciliationModel):
    """Selected source for one canonical field."""

    field_name: str
    source: SourceReference


class ReconciledActivity(ReconciliationModel):
    """Canonical activity plus all contributing representations."""

    canonical: NormalizedActivity
    representations: tuple[NormalizedActivity, ...]
    match_method: MatchMethod
    field_provenance: tuple[FieldProvenance, ...]


class ReconciliationResult(ReconciliationModel):
    """Result of reconciling Garmin and Strava summaries."""

    activities: tuple[ReconciledActivity, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()
    excluded_strava_representations: int = Field(ge=0)
    excluded_garmin_representations: int = Field(ge=0)


def _is_running(activity: NormalizedActivity) -> bool:
    return activity.activity_kind in _RUNNING_KINDS


def _distance_is_compatible(
    left: float | None,
    right: float | None,
) -> bool:
    if left is None or right is None:
        return False

    tolerance = max(
        _MIN_DISTANCE_TOLERANCE_M,
        max(left, right) * _DISTANCE_TOLERANCE_RATIO,
    )
    return abs(left - right) <= tolerance


def _is_strong_match(
    garmin: NormalizedActivity,
    strava: NormalizedActivity,
) -> bool:
    if garmin.athlete_id != strava.athlete_id:
        return False

    start_delta = abs((garmin.start_time_utc - strava.start_time_utc).total_seconds())

    duration_delta = abs(garmin.elapsed_time_s - strava.elapsed_time_s)

    return (
        start_delta <= _START_TOLERANCE_S
        and duration_delta <= _DURATION_TOLERANCE_S
        and _distance_is_compatible(
            garmin.distance_m,
            strava.distance_m,
        )
    )


def _has_value(value: Any) -> bool:
    return value is not None and value != ()


def _single_source_activity(
    activity: NormalizedActivity,
) -> ReconciledActivity:
    provenance = [
        FieldProvenance(
            field_name="activity_kind",
            source=activity.source,
        ),
        FieldProvenance(
            field_name="start_time_utc",
            source=activity.source,
        ),
        FieldProvenance(
            field_name="elapsed_time_s",
            source=activity.source,
        ),
    ]

    for field_name in _OPTIONAL_MERGE_FIELDS:
        if _has_value(getattr(activity, field_name)):
            provenance.append(
                FieldProvenance(
                    field_name=field_name,
                    source=activity.source,
                )
            )

    return ReconciledActivity(
        canonical=activity,
        representations=(activity,),
        match_method=MatchMethod.SINGLE_SOURCE,
        field_provenance=tuple(provenance),
    )


def _merge_pair(
    garmin: NormalizedActivity,
    strava: NormalizedActivity,
) -> ReconciledActivity:
    values: dict[str, Any] = {
        "athlete_id": garmin.athlete_id,
        "source": garmin.source,
        "activity_kind": garmin.activity_kind,
        "provider_activity_type": (garmin.provider_activity_type),
        "start_time_utc": garmin.start_time_utc,
        "elapsed_time_s": garmin.elapsed_time_s,
    }

    provenance = [
        FieldProvenance(
            field_name="activity_kind",
            source=garmin.source,
        ),
        FieldProvenance(
            field_name="provider_activity_type",
            source=garmin.source,
        ),
        FieldProvenance(
            field_name="start_time_utc",
            source=garmin.source,
        ),
        FieldProvenance(
            field_name="elapsed_time_s",
            source=garmin.source,
        ),
    ]

    for field_name in _OPTIONAL_MERGE_FIELDS:
        garmin_value = getattr(garmin, field_name)
        strava_value = getattr(strava, field_name)

        if _has_value(garmin_value):
            values[field_name] = garmin_value
            selected_source = garmin.source
        elif _has_value(strava_value):
            values[field_name] = strava_value
            selected_source = strava.source
        else:
            continue

        provenance.append(
            FieldProvenance(
                field_name=field_name,
                source=selected_source,
            )
        )

    canonical = NormalizedActivity.model_validate(values)

    return ReconciledActivity(
        canonical=canonical,
        representations=(garmin, strava),
        match_method=MatchMethod.CROSS_SOURCE_STRONG,
        field_provenance=tuple(provenance),
    )


def reconcile_activity_summaries(
    *,
    strava_activities: tuple[NormalizedActivity, ...],
    garmin_activities: tuple[NormalizedActivity, ...],
) -> ReconciliationResult:
    """Create canonical running activities from provider summaries."""

    reconciled: list[ReconciledActivity] = []
    findings: list[ValidationFinding] = []
    used_strava_indexes: set[int] = set()

    running_garmin = [activity for activity in garmin_activities if _is_running(activity)]

    for garmin in running_garmin:
        candidates = [
            (index, strava)
            for index, strava in enumerate(strava_activities)
            if (
                index not in used_strava_indexes
                and _is_strong_match(
                    garmin,
                    strava,
                )
            )
        ]

        if len(candidates) == 1:
            strava_index, strava = candidates[0]
            used_strava_indexes.add(strava_index)
            reconciled.append(
                _merge_pair(
                    garmin,
                    strava,
                )
            )
            continue

        if len(candidates) > 1:
            findings.append(
                ValidationFinding(
                    severity=FindingSeverity.ERROR,
                    code="CROSS_SOURCE_MATCH_AMBIGUOUS",
                    message=("A Garmin running activity has multiple compatible Strava summaries."),
                )
            )

        reconciled.append(_single_source_activity(garmin))

    included_strava_indexes = set(used_strava_indexes)

    for index, strava in enumerate(strava_activities):
        if index in used_strava_indexes:
            continue

        if not _is_running(strava):
            continue

        included_strava_indexes.add(index)
        reconciled.append(_single_source_activity(strava))

    reconciled.sort(
        key=lambda item: (
            item.canonical.start_time_utc,
            item.canonical.source.provider.value,
            item.canonical.source.source_activity_id or "",
        )
    )

    excluded_strava = len(strava_activities) - len(included_strava_indexes)
    excluded_garmin = len(garmin_activities) - len(running_garmin)

    return ReconciliationResult(
        activities=tuple(reconciled),
        findings=tuple(findings),
        excluded_strava_representations=(excluded_strava),
        excluded_garmin_representations=(excluded_garmin),
    )
