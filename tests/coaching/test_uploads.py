"""Tests for preparing one uploaded Strava FIT run."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from runcoach.coaching import uploads
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
CONTENT_SHA256 = "b" * 64


def _activity(kind: ActivityKind = ActivityKind.RUNNING) -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=SourceReference(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT,
            source_file_name="staged.fit",
            content_sha256=CONTENT_SHA256,
        ),
        activity_kind=kind,
        provider_activity_type=kind.value,
        start_time_utc=datetime(2026, 9, 6, 17, 30, tzinfo=UTC),
        elapsed_time_s=4_000.0,
        distance_m=18_000.0,
    )


def test_prepare_upload_preserves_title_and_private_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        uploads,
        "parse_fit_activity",
        lambda *_: ParseResult(activities=(_activity(),)),
    )

    result = uploads.prepare_strava_fit_upload(
        path=Path("activity.fit"),
        filename="Progressive_Long_Run.fit",
        title="Progressive long run",
        size_bytes=10_000,
        athlete_id=ATHLETE_ID,
        athlete_timezone=ZoneInfo("Africa/Casablanca"),
    )

    assert result.activity.name == "Progressive long run"
    assert result.activity.timezone_name == "Africa/Casablanca"
    assert result.activity.source.source_file_name == ("uploads/Progressive_Long_Run.fit")
    assert result.input.activity_type == "long"
    assert result.input.file.storage_key == f"strava/uploads/{CONTENT_SHA256}"
    assert result.input.file.size_bytes == 10_000


@pytest.mark.parametrize(
    ("parse_result", "message"),
    (
        (
            ParseResult(activities=(_activity(ActivityKind.OTHER),)),
            "exactly one running activity",
        ),
        (ParseResult(), "could not be parsed"),
    ),
)
def test_prepare_upload_rejects_non_running_or_unparseable_payload(
    parse_result: ParseResult,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uploads, "parse_fit_activity", lambda *_: parse_result)

    with pytest.raises(uploads.RunUploadValidationError, match=message):
        uploads.prepare_strava_fit_upload(
            path=Path("activity.fit"),
            filename="activity.fit",
            title="Morning Run",
            size_bytes=100,
            athlete_id=ATHLETE_ID,
            athlete_timezone=ZoneInfo("Africa/Casablanca"),
        )
