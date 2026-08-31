"""Positional adapter for Strava bulk-export activity summaries."""

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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

_STRAVA_DATE_PATTERN = re.compile(
    r"^(?P<month>[A-Za-z]{3}) "
    r"(?P<day>\d{1,2}), "
    r"(?P<year>\d{4}), "
    r"(?P<hour>\d{1,2}):"
    r"(?P<minute>\d{2}):"
    r"(?P<second>\d{2}) "
    r"(?P<period>AM|PM)$",
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_ACTIVITY_KIND_BY_STRAVA_TYPE = {
    "run": ActivityKind.RUNNING,
    "trail run": ActivityKind.TRAIL_RUNNING,
    "treadmill run": ActivityKind.TREADMILL_RUNNING,
    "virtual run": ActivityKind.TREADMILL_RUNNING,
}


@dataclass(frozen=True)
class _Columns:
    activity_id: int
    activity_date: int
    activity_name: int
    activity_type: int
    filename: int
    elapsed_time: int
    moving_time: int
    distance: int
    elevation_gain: int
    elevation_loss: int


def _column_index(
    header: list[str],
    name: str,
    occurrence: int = 1,
) -> int:
    matches = [index for index, column_name in enumerate(header) if column_name == name]

    if len(matches) < occurrence:
        raise ValueError(f"required column occurrence is missing: {name}")

    return matches[occurrence - 1]


def _resolve_columns(header: list[str]) -> _Columns:
    return _Columns(
        activity_id=_column_index(header, "Activity ID"),
        activity_date=_column_index(header, "Activity Date"),
        activity_name=_column_index(header, "Activity Name"),
        activity_type=_column_index(header, "Activity Type"),
        filename=_column_index(header, "Filename"),
        elapsed_time=_column_index(
            header,
            "Elapsed Time",
            occurrence=2,
        ),
        moving_time=_column_index(header, "Moving Time"),
        distance=_column_index(
            header,
            "Distance",
            occurrence=2,
        ),
        elevation_gain=_column_index(
            header,
            "Elevation Gain",
        ),
        elevation_loss=_column_index(
            header,
            "Elevation Loss",
        ),
    )


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        parsed = None

    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)

        return parsed.astimezone(UTC)

    match = _STRAVA_DATE_PATTERN.match(normalized)

    if match is None:
        raise ValueError("unsupported Strava activity timestamp")

    month = _MONTHS.get(match.group("month").lower())

    if month is None:
        raise ValueError("unsupported Strava activity month")

    hour = int(match.group("hour"))
    period = match.group("period").upper()

    if period == "AM" and hour == 12:
        hour = 0
    elif period == "PM" and hour != 12:
        hour += 12

    return datetime(
        year=int(match.group("year")),
        month=month,
        day=int(match.group("day")),
        hour=hour,
        minute=int(match.group("minute")),
        second=int(match.group("second")),
        tzinfo=UTC,
    )


def _required_number(value: str) -> float:
    normalized = value.strip().replace(",", "")

    if not normalized:
        raise ValueError("required numeric value is missing")

    return float(normalized)


def _optional_number(value: str) -> float | None:
    normalized = value.strip().replace(",", "")

    if not normalized:
        return None

    return float(normalized)


def _content_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _activity_kind(provider_type: str) -> ActivityKind:
    return _ACTIVITY_KIND_BY_STRAVA_TYPE.get(
        provider_type.strip().lower(),
        ActivityKind.OTHER,
    )


def _header_error(message: str) -> ParseResult:
    return ParseResult(
        findings=(
            ValidationFinding(
                severity=FindingSeverity.ERROR,
                code="STRAVA_HEADER_INVALID",
                message=message,
            ),
        )
    )


def parse_strava_activities_csv(
    path: Path,
    athlete_id: UUID,
) -> ParseResult:
    """Parse a Strava activities CSV without losing duplicate columns."""

    content_sha256 = _content_sha256(path)
    activities: list[NormalizedActivity] = []
    findings: list[ValidationFinding] = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        reader = csv.reader(stream)
        header = next(reader, None)

        if header is None:
            return _header_error("Strava activities CSV is empty.")

        try:
            columns = _resolve_columns(header)
        except ValueError:
            return _header_error(
                "Strava activities CSV does not contain the required positional schema."
            )

        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                findings.append(
                    ValidationFinding(
                        severity=FindingSeverity.ERROR,
                        code="STRAVA_ROW_WIDTH_INVALID",
                        message="CSV row width does not match the source header.",
                        source_row_number=row_number,
                    )
                )
                continue

            try:
                provider_type = row[columns.activity_type].strip()
                referenced_file_name = row[columns.filename].strip() or None

                source = SourceReference(
                    provider=SourceProvider.STRAVA,
                    source_format=SourceFormat.CSV,
                    source_file_name=path.name,
                    content_sha256=content_sha256,
                    referenced_file_name=referenced_file_name,
                    source_activity_id=row[columns.activity_id].strip(),
                    source_row_number=row_number,
                )

                activities.append(
                    NormalizedActivity(
                        athlete_id=athlete_id,
                        source=source,
                        activity_kind=_activity_kind(provider_type),
                        provider_activity_type=provider_type,
                        name=row[columns.activity_name].strip() or None,
                        start_time_utc=_parse_timestamp(row[columns.activity_date]),
                        elapsed_time_s=_required_number(row[columns.elapsed_time]),
                        moving_time_s=_optional_number(row[columns.moving_time]),
                        distance_m=_optional_number(row[columns.distance]),
                        elevation_gain_m=_optional_number(row[columns.elevation_gain]),
                        elevation_loss_m=_optional_number(row[columns.elevation_loss]),
                    )
                )
            except (ValueError, ValidationError):
                findings.append(
                    ValidationFinding(
                        severity=FindingSeverity.ERROR,
                        code="STRAVA_ROW_INVALID",
                        message="CSV row could not be normalized.",
                        source_row_number=row_number,
                    )
                )

    return ParseResult(
        activities=tuple(activities),
        findings=tuple(findings),
    )
