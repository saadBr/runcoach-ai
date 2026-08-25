"""Tests for source-neutral ingestion contracts."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from runcoach.ingestion import (
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

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
CONTENT_SHA256 = "a" * 64


def source_reference() -> SourceReference:
    """Return deterministic source provenance for tests."""

    return SourceReference(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_file_name="activities.csv",
        content_sha256=CONTENT_SHA256,
        source_activity_id="source-activity-1",
        source_row_number=2,
    )


def test_summary_only_activity_is_valid() -> None:
    activity = NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=source_reference(),
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type="Run",
        start_time_utc=datetime(2026, 4, 1, 6, 30, tzinfo=UTC),
        elapsed_time_s=3_600,
        distance_m=10_000,
    )

    assert activity.start_time_utc.tzinfo is UTC
    assert activity.laps == ()
    assert activity.trackpoints == ()


def test_activity_timestamp_is_normalized_to_utc() -> None:
    source_timezone = timezone(timedelta(hours=1))

    activity = NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=source_reference(),
        activity_kind=ActivityKind.TRAIL_RUNNING,
        provider_activity_type="trail_running",
        start_time_utc=datetime(2026, 4, 1, 7, 30, tzinfo=source_timezone),
        elapsed_time_s=3_600,
    )

    assert activity.start_time_utc == datetime(2026, 4, 1, 6, 30, tzinfo=UTC)


def test_naive_activity_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        NormalizedActivity(
            athlete_id=ATHLETE_ID,
            source=source_reference(),
            activity_kind=ActivityKind.RUNNING,
            provider_activity_type="Run",
            start_time_utc=datetime(2026, 4, 1, 6, 30),
            elapsed_time_s=3_600,
        )


def test_trackpoint_requires_complete_coordinate_pair() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        NormalizedTrackpoint(
            sequence=0,
            timestamp_utc=datetime(2026, 4, 1, 6, 30, tzinfo=UTC),
            latitude_deg=33.5,
        )


def test_negative_measurement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizedActivity(
            athlete_id=ATHLETE_ID,
            source=source_reference(),
            activity_kind=ActivityKind.RUNNING,
            provider_activity_type="Run",
            start_time_utc=datetime(2026, 4, 1, 6, 30, tzinfo=UTC),
            elapsed_time_s=3_600,
            distance_m=-1,
        )


def test_invalid_checksum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            provider=SourceProvider.GARMIN,
            source_format=SourceFormat.FIT,
            source_file_name="activity.fit",
            content_sha256="not-a-sha256",
        )


def test_parse_result_preserves_structured_findings() -> None:
    finding = ValidationFinding(
        severity=FindingSeverity.WARNING,
        code="MISSING_HEART_RATE",
        message="Heart-rate data is unavailable for this activity.",
        source_row_number=2,
        field_name="average_heart_rate_bpm",
    )

    result = ParseResult(findings=(finding,))

    assert result.activities == ()
    assert result.findings == (finding,)
