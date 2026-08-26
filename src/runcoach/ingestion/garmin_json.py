"""Adapter for Garmin summarized-activity JSON exports."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
    ValidationFinding,
)

_ACTIVITY_KIND_BY_GARMIN_TYPE = {
    "running": ActivityKind.RUNNING,
    "trail_running": ActivityKind.TRAIL_RUNNING,
    "treadmill_running": ActivityKind.TREADMILL_RUNNING,
}


def _finding(
    code: str,
    message: str,
) -> ValidationFinding:
    return ValidationFinding(
        severity=FindingSeverity.ERROR,
        code=code,
        message=message,
    )


def _content_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _find_summary_records(
    value: Any,
) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        records = value.get("summarizedActivitiesExport")

        if isinstance(records, list):
            return [record for record in records if isinstance(record, dict)]

        for child in value.values():
            result = _find_summary_records(child)

            if result is not None:
                return result

    elif isinstance(value, list):
        for child in value:
            result = _find_summary_records(child)

            if result is not None:
                return result

    return None


def _number(
    record: dict[str, Any],
    field_name: str,
) -> float | None:
    value = record.get(field_name)

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        normalized = value.strip()

        if not normalized:
            return None

        return float(normalized)

    return None


def _integer(
    record: dict[str, Any],
    field_name: str,
) -> int | None:
    value = _number(record, field_name)

    if value is None:
        return None

    return round(value)


def _scaled_number(
    record: dict[str, Any],
    field_name: str,
    divisor: float,
) -> float | None:
    value = _number(record, field_name)

    if value is None:
        return None

    return value / divisor


def _text(
    record: dict[str, Any],
    field_name: str,
) -> str | None:
    value = record.get(field_name)

    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(
        value,
        bool,
    ):
        numeric_value = float(value)

        if numeric_value > 10_000_000_000:
            numeric_value /= 1000.0

        return datetime.fromtimestamp(
            numeric_value,
            tz=UTC,
        )

    if not isinstance(value, str):
        raise ValueError("Garmin start timestamp is missing")

    normalized = value.strip()

    try:
        numeric_value = float(normalized)
    except ValueError:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)

        return parsed.astimezone(UTC)

    if numeric_value > 10_000_000_000:
        numeric_value /= 1000.0

    return datetime.fromtimestamp(
        numeric_value,
        tz=UTC,
    )


def _activity_kind(
    provider_type: str,
) -> ActivityKind:
    return _ACTIVITY_KIND_BY_GARMIN_TYPE.get(
        provider_type.strip().lower(),
        ActivityKind.OTHER,
    )


def _cadence_spm(
    record: dict[str, Any],
    double_field: str,
    single_field: str,
) -> float | None:
    double_cadence = _number(record, double_field)

    if double_cadence is not None:
        return double_cadence

    single_cadence = _number(record, single_field)

    if single_cadence is None:
        return None

    return single_cadence * 2.0


def parse_garmin_activity_summaries(
    path: Path,
    athlete_id: UUID,
) -> ParseResult:
    """Parse Garmin activity summaries using explicit source units."""

    content_sha256 = _content_sha256(path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ParseResult(
            findings=(
                _finding(
                    "GARMIN_JSON_INVALID",
                    "Garmin summary JSON could not be parsed.",
                ),
            )
        )

    records = _find_summary_records(payload)

    if records is None:
        return ParseResult(
            findings=(
                _finding(
                    "GARMIN_SUMMARY_CONTAINER_MISSING",
                    "Garmin summary container was not found.",
                ),
            )
        )

    activities: list[NormalizedActivity] = []
    findings: list[ValidationFinding] = []

    for record_number, record in enumerate(
        records,
        start=1,
    ):
        try:
            provider_type = _text(
                record,
                "activityType",
            )

            if provider_type is None:
                raise ValueError("Garmin activity type is missing")

            source_activity_id = _text(
                record,
                "activityId",
            )

            if source_activity_id is None:
                raise ValueError("Garmin activity identifier is missing")

            elapsed_time_s = _scaled_number(
                record,
                "elapsedDuration",
                1000.0,
            )

            if elapsed_time_s is None:
                elapsed_time_s = _scaled_number(
                    record,
                    "duration",
                    1000.0,
                )

            if elapsed_time_s is None:
                raise ValueError("Garmin activity duration is missing")

            source = SourceReference(
                provider=SourceProvider.GARMIN,
                source_format=SourceFormat.JSON,
                source_file_name=path.name,
                content_sha256=content_sha256,
                source_activity_id=source_activity_id,
                source_row_number=record_number,
            )

            activities.append(
                NormalizedActivity(
                    athlete_id=athlete_id,
                    source=source,
                    activity_kind=_activity_kind(provider_type),
                    provider_activity_type=provider_type,
                    name=_text(record, "name"),
                    start_time_utc=_parse_timestamp(
                        record.get(
                            "startTimeGmt",
                            record.get("beginTimestamp"),
                        )
                    ),
                    timezone_name=_text(
                        record,
                        "timeZoneId",
                    ),
                    elapsed_time_s=elapsed_time_s,
                    moving_time_s=_scaled_number(
                        record,
                        "movingDuration",
                        1000.0,
                    ),
                    distance_m=_scaled_number(
                        record,
                        "distance",
                        100.0,
                    ),
                    average_speed_mps=_number(
                        record,
                        "avgSpeed",
                    ),
                    maximum_speed_mps=_number(
                        record,
                        "maxSpeed",
                    ),
                    average_heart_rate_bpm=_integer(
                        record,
                        "avgHr",
                    ),
                    maximum_heart_rate_bpm=_integer(
                        record,
                        "maxHr",
                    ),
                    minimum_heart_rate_bpm=_integer(
                        record,
                        "minHr",
                    ),
                    average_cadence_spm=_cadence_spm(
                        record,
                        "avgDoubleCadence",
                        "avgRunCadence",
                    ),
                    maximum_cadence_spm=_cadence_spm(
                        record,
                        "maxDoubleCadence",
                        "maxRunCadence",
                    ),
                    calories_kcal=_number(
                        record,
                        "calories",
                    ),
                    steps=_integer(
                        record,
                        "steps",
                    ),
                    provider_vo2max=_number(
                        record,
                        "vO2MaxValue",
                    ),
                    provider_aerobic_training_effect=(
                        _number(
                            record,
                            "aerobicTrainingEffect",
                        )
                    ),
                    provider_anaerobic_training_effect=(
                        _number(
                            record,
                            "anaerobicTrainingEffect",
                        )
                    ),
                    provider_training_effect_label=(
                        _text(
                            record,
                            "trainingEffectLabel",
                        )
                    ),
                )
            )
        except (
            OverflowError,
            ValueError,
            ValidationError,
        ):
            findings.append(
                ValidationFinding(
                    severity=FindingSeverity.ERROR,
                    code="GARMIN_SUMMARY_RECORD_INVALID",
                    message="Garmin activity summary could not be normalized.",
                    source_row_number=record_number,
                )
            )

    return ParseResult(
        activities=tuple(activities),
        findings=tuple(findings),
    )
