"""Secure GPX adapter for timestamped running trackpoints."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import ValidationError

from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    NormalizedTrackpoint,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
    ValidationFinding,
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _content_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _direct_child_text(
    element: Element,
    child_name: str,
) -> str | None:
    for child in element:
        if _local_name(child.tag) != child_name:
            continue

        if child.text is None:
            return None

        value = child.text.strip()
        return value or None

    return None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("GPX timestamp must include a timezone")

    return parsed.astimezone(UTC)


def _optional_float(value: str | None) -> float | None:
    if value is None:
        return None

    return float(value)


def _track_name(root: Element) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) != "trk":
            continue

        return _direct_child_text(element, "name")

    return None


def _xml_error() -> ParseResult:
    return ParseResult(
        findings=(
            ValidationFinding(
                severity=FindingSeverity.ERROR,
                code="GPX_XML_INVALID",
                message="GPX XML could not be parsed safely.",
            ),
        )
    )


def parse_gpx_activity(
    path: Path,
    athlete_id: UUID,
    *,
    activity_kind: ActivityKind = ActivityKind.RUNNING,
    source_activity_id: str | None = None,
    source_row_number: int | None = None,
) -> ParseResult:
    """Parse one GPX activity into canonical trackpoint units."""

    content_sha256 = _content_sha256(path)

    try:
        root = ElementTree.parse(path).getroot()
    except (DefusedXmlException, OSError, ParseError):
        return _xml_error()
    if root is None:
        return _xml_error()
    findings: list[ValidationFinding] = []
    trackpoints: list[NormalizedTrackpoint] = []
    previous_timestamp: datetime | None = None

    for element in root.iter():
        if _local_name(element.tag) != "trkpt":
            continue

        try:
            latitude_text = element.attrib.get("lat")
            longitude_text = element.attrib.get("lon")
            timestamp_text = _direct_child_text(
                element,
                "time",
            )

            if latitude_text is None or longitude_text is None or timestamp_text is None:
                raise ValueError("required GPX trackpoint field is missing")

            timestamp = _parse_timestamp(timestamp_text)

            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise ValueError("GPX timestamps are not monotonic")

            trackpoint = NormalizedTrackpoint(
                sequence=len(trackpoints),
                timestamp_utc=timestamp,
                latitude_deg=float(latitude_text),
                longitude_deg=float(longitude_text),
                altitude_m=_optional_float(_direct_child_text(element, "ele")),
            )
        except (ValueError, ValidationError):
            findings.append(
                ValidationFinding(
                    severity=FindingSeverity.WARNING,
                    code="GPX_TRACKPOINT_INVALID",
                    message="A GPX trackpoint could not be normalized.",
                )
            )
            continue

        trackpoints.append(trackpoint)
        previous_timestamp = timestamp

    if not trackpoints:
        findings.append(
            ValidationFinding(
                severity=FindingSeverity.ERROR,
                code="GPX_NO_VALID_TRACKPOINTS",
                message="GPX file contains no valid timestamped trackpoints.",
            )
        )
        return ParseResult(findings=tuple(findings))

    start_time = trackpoints[0].timestamp_utc
    elapsed_time_s = (trackpoints[-1].timestamp_utc - start_time).total_seconds()

    source = SourceReference(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.GPX,
        source_file_name=path.name,
        content_sha256=content_sha256,
        source_activity_id=source_activity_id,
        source_row_number=source_row_number,
    )

    try:
        activity = NormalizedActivity(
            athlete_id=athlete_id,
            source=source,
            activity_kind=activity_kind,
            provider_activity_type="gpx",
            name=_track_name(root),
            start_time_utc=start_time,
            elapsed_time_s=elapsed_time_s,
            trackpoints=tuple(trackpoints),
        )
    except ValidationError:
        findings.append(
            ValidationFinding(
                severity=FindingSeverity.ERROR,
                code="GPX_ACTIVITY_INVALID",
                message="GPX activity could not be normalized.",
            )
        )
        return ParseResult(findings=tuple(findings))

    return ParseResult(
        activities=(activity,),
        findings=tuple(findings),
    )
