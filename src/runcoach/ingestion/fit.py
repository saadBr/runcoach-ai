"""FIT and FIT.GZ activity adapter using the official Garmin FIT SDK."""

import gzip
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from garmin_fit_sdk import Decoder, Stream
from pydantic import ValidationError

from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    NormalizedLap,
    NormalizedTrackpoint,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
    ValidationFinding,
)

_SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)


def _finding(
    code: str,
    message: str,
    *,
    severity: FindingSeverity = FindingSeverity.ERROR,
) -> ValidationFinding:
    return ValidationFinding(
        severity=severity,
        code=code,
        message=message,
    )


def _read_fit_content(path: Path) -> bytearray:
    if path.name.lower().endswith(".fit.gz"):
        with gzip.open(path, "rb") as stream:
            return bytearray(stream.read())

    return bytearray(path.read_bytes())


def _source_format(path: Path) -> SourceFormat:
    if path.name.lower().endswith(".fit.gz"):
        return SourceFormat.FIT_GZ

    return SourceFormat.FIT


def _content_sha256(content: bytearray) -> str:
    return hashlib.sha256(content).hexdigest()


def _number(
    message: dict[str, Any],
    *field_names: str,
) -> float | None:
    for field_name in field_names:
        value = message.get(field_name)

        if value is None or isinstance(value, bool):
            continue

        if isinstance(value, (int, float)):
            return float(value)

    return None


def _integer(
    message: dict[str, Any],
    *field_names: str,
) -> int | None:
    value = _number(message, *field_names)

    if value is None:
        return None

    return round(value)


def _timestamp(
    message: dict[str, Any],
    *field_names: str,
) -> datetime | None:
    for field_name in field_names:
        value = message.get(field_name)

        if isinstance(value, datetime):
            return value

    return None


def _text(
    message: dict[str, Any],
    field_name: str,
) -> str | None:
    value = message.get(field_name)

    if isinstance(value, str) and value.strip():
        return value.strip().lower()

    return None


def _cadence_spm(
    message: dict[str, Any],
    cadence_field: str,
    fractional_field: str,
) -> float | None:
    cadence = _number(message, cadence_field)

    if cadence is None:
        return None

    fractional = _number(message, fractional_field) or 0.0
    return (cadence + fractional) * 2.0


def _activity_kind(
    session: dict[str, Any],
) -> ActivityKind:
    sport = _text(session, "sport")
    sub_sport = _text(session, "sub_sport")

    if sport != "running":
        return ActivityKind.OTHER

    if sub_sport == "trail":
        return ActivityKind.TRAIL_RUNNING

    if sub_sport == "treadmill":
        return ActivityKind.TREADMILL_RUNNING

    return ActivityKind.RUNNING


def _provider_activity_type(
    session: dict[str, Any],
) -> str:
    sport = _text(session, "sport") or "unknown"
    sub_sport = _text(session, "sub_sport")

    if sub_sport and sub_sport != "generic":
        return f"{sport}:{sub_sport}"

    return sport


def _position_degrees(value: float) -> float:
    return value * _SEMICIRCLE_TO_DEGREES


def _normalized_trackpoints(
    records: list[dict[str, Any]],
    start_time: datetime,
    findings: list[ValidationFinding],
) -> tuple[NormalizedTrackpoint, ...]:
    trackpoints: list[NormalizedTrackpoint] = []
    previous_timestamp: datetime | None = None

    for record in records:
        timestamp = _timestamp(record, "timestamp")

        if timestamp is None:
            findings.append(
                _finding(
                    "FIT_RECORD_TIMESTAMP_MISSING",
                    "A FIT record has no usable timestamp.",
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        if timestamp < start_time or (
            previous_timestamp is not None and timestamp < previous_timestamp
        ):
            findings.append(
                _finding(
                    "FIT_RECORD_TIME_INVALID",
                    "A FIT record has a non-monotonic timestamp.",
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        latitude_raw = _number(record, "position_lat")
        longitude_raw = _number(record, "position_long")

        latitude = None
        longitude = None

        if latitude_raw is not None and longitude_raw is not None:
            latitude = _position_degrees(latitude_raw)
            longitude = _position_degrees(longitude_raw)

        try:
            trackpoint = NormalizedTrackpoint(
                sequence=len(trackpoints),
                timestamp_utc=timestamp,
                elapsed_time_s=(timestamp - start_time).total_seconds(),
                distance_m=_number(record, "distance"),
                latitude_deg=latitude,
                longitude_deg=longitude,
                altitude_m=_number(
                    record,
                    "enhanced_altitude",
                    "altitude",
                ),
                heart_rate_bpm=_integer(
                    record,
                    "heart_rate",
                ),
                cadence_spm=_cadence_spm(
                    record,
                    "cadence",
                    "fractional_cadence",
                ),
                speed_mps=_number(
                    record,
                    "enhanced_speed",
                    "speed",
                ),
                power_watts=_number(record, "power"),
                temperature_c=_number(
                    record,
                    "temperature",
                ),
            )
        except ValidationError:
            findings.append(
                _finding(
                    "FIT_RECORD_INVALID",
                    "A FIT record could not be normalized.",
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        trackpoints.append(trackpoint)
        previous_timestamp = timestamp

    return tuple(trackpoints)


def _normalized_laps(
    lap_messages: list[dict[str, Any]],
    findings: list[ValidationFinding],
) -> tuple[NormalizedLap, ...]:
    laps: list[NormalizedLap] = []

    for lap_message in lap_messages:
        try:
            lap = NormalizedLap(
                sequence=len(laps),
                start_time_utc=_timestamp(
                    lap_message,
                    "start_time",
                ),
                elapsed_time_s=_number(
                    lap_message,
                    "total_elapsed_time",
                ),
                moving_time_s=_number(
                    lap_message,
                    "total_timer_time",
                ),
                distance_m=_number(
                    lap_message,
                    "total_distance",
                ),
                elevation_gain_m=_number(
                    lap_message,
                    "total_ascent",
                ),
                elevation_loss_m=_number(
                    lap_message,
                    "total_descent",
                ),
                average_heart_rate_bpm=_integer(
                    lap_message,
                    "avg_heart_rate",
                ),
                maximum_heart_rate_bpm=_integer(
                    lap_message,
                    "max_heart_rate",
                ),
                average_cadence_spm=_cadence_spm(
                    lap_message,
                    "avg_cadence",
                    "avg_fractional_cadence",
                ),
                maximum_cadence_spm=_cadence_spm(
                    lap_message,
                    "max_cadence",
                    "max_fractional_cadence",
                ),
            )
        except ValidationError:
            findings.append(
                _finding(
                    "FIT_LAP_INVALID",
                    "A FIT lap could not be normalized.",
                    severity=FindingSeverity.WARNING,
                )
            )
            continue

        laps.append(lap)

    return tuple(laps)


def parse_fit_activity(
    path: Path,
    athlete_id: UUID,
    provider: SourceProvider,
    *,
    source_activity_id: str | None = None,
    source_row_number: int | None = None,
    activity_kind_override: ActivityKind | None = None,
) -> ParseResult:
    """Decode one FIT or FIT.GZ activity into canonical units."""

    try:
        content = _read_fit_content(path)
        stream = Stream.from_byte_array(content)
        decoder = Decoder(stream)

        if not decoder.is_fit():
            return ParseResult(
                findings=(
                    _finding(
                        "FIT_FILE_INVALID",
                        "File does not contain a valid FIT signature.",
                    ),
                )
            )
        decoded_messages, decode_errors = decoder.read(
            enable_crc_check=True,
            convert_datetimes_to_dates=True,
            convert_types_to_strings=True,
            merge_heart_rates=False,
        )
    except (OSError, RuntimeError, ValueError):
        return ParseResult(
            findings=(
                _finding(
                    "FIT_FILE_INVALID",
                    "FIT file could not be read safely.",
                ),
            )
        )

    if decode_errors:
        return ParseResult(
            findings=(
                _finding(
                    "FIT_DECODE_ERROR",
                    "FIT decoder reported one or more errors.",
                ),
            )
        )

    messages = cast(
        dict[str, list[dict[str, Any]]],
        decoded_messages,
    )
    sessions = messages.get("session_mesgs", [])
    records = messages.get("record_mesgs", [])
    lap_messages = messages.get("lap_mesgs", [])

    if not sessions:
        return ParseResult(
            findings=(
                _finding(
                    "FIT_SESSION_MISSING",
                    "FIT activity contains no session message.",
                ),
            )
        )

    session = sessions[0]
    start_time = _timestamp(session, "start_time")

    if start_time is None and records:
        start_time = _timestamp(records[0], "timestamp")

    if start_time is None:
        return ParseResult(
            findings=(
                _finding(
                    "FIT_START_TIME_MISSING",
                    "FIT activity has no usable start timestamp.",
                ),
            )
        )

    findings: list[ValidationFinding] = []

    if len(sessions) > 1:
        findings.append(
            _finding(
                "FIT_MULTIPLE_SESSIONS",
                "Only the first FIT session was normalized.",
                severity=FindingSeverity.WARNING,
            )
        )

    trackpoints = _normalized_trackpoints(
        records,
        start_time,
        findings,
    )
    laps = _normalized_laps(
        lap_messages,
        findings,
    )

    elapsed_time_s = _number(
        session,
        "total_elapsed_time",
        "total_timer_time",
    )

    if elapsed_time_s is None and trackpoints:
        elapsed_time_s = (trackpoints[-1].timestamp_utc - start_time).total_seconds()

    if elapsed_time_s is None:
        return ParseResult(
            findings=(
                *findings,
                _finding(
                    "FIT_DURATION_MISSING",
                    "FIT activity has no usable elapsed duration.",
                ),
            )
        )

    source = SourceReference(
        provider=provider,
        source_format=_source_format(path),
        source_file_name=path.name,
        content_sha256=_content_sha256(content),
        source_activity_id=source_activity_id,
        source_row_number=source_row_number,
    )

    try:
        activity = NormalizedActivity(
            athlete_id=athlete_id,
            source=source,
            activity_kind=(activity_kind_override or _activity_kind(session)),
            provider_activity_type=(_provider_activity_type(session)),
            start_time_utc=start_time,
            elapsed_time_s=elapsed_time_s,
            moving_time_s=_number(
                session,
                "total_timer_time",
            ),
            distance_m=_number(
                session,
                "total_distance",
            ),
            elevation_gain_m=_number(
                session,
                "total_ascent",
            ),
            elevation_loss_m=_number(
                session,
                "total_descent",
            ),
            average_speed_mps=_number(
                session,
                "enhanced_avg_speed",
                "avg_speed",
            ),
            maximum_speed_mps=_number(
                session,
                "enhanced_max_speed",
                "max_speed",
            ),
            average_heart_rate_bpm=_integer(
                session,
                "avg_heart_rate",
            ),
            maximum_heart_rate_bpm=_integer(
                session,
                "max_heart_rate",
            ),
            minimum_heart_rate_bpm=_integer(
                session,
                "min_heart_rate",
            ),
            average_cadence_spm=_cadence_spm(
                session,
                "avg_cadence",
                "avg_fractional_cadence",
            ),
            maximum_cadence_spm=_cadence_spm(
                session,
                "max_cadence",
                "max_fractional_cadence",
            ),
            calories_kcal=_number(
                session,
                "total_calories",
            ),
            laps=laps,
            trackpoints=trackpoints,
        )
    except ValidationError:
        return ParseResult(
            findings=(
                *findings,
                _finding(
                    "FIT_ACTIVITY_INVALID",
                    "FIT activity could not be normalized.",
                ),
            )
        )

    return ParseResult(
        activities=(activity,),
        findings=tuple(findings),
    )
