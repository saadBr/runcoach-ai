"""Tests for importing standalone Strava FIT downloads."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from runcoach.cli import import_strava_activities
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Evening_Run.fit", "Evening Run"),
        ("Morning_Run (2).fit", "Morning Run"),
        ("Hill_Session.fit.gz", "Hill Session"),
    ],
)
def test_title_is_derived_from_downloaded_filename(
    filename: str,
    expected: str,
) -> None:
    assert import_strava_activities._title_from_filename(Path(filename)) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Local 10K Race", "race"),
        ("Progressive Long Run", "long"),
        ("Easy Aerobic Run", "easy"),
        ("3K WU 25 tempo 1.5K CD", "workout"),
        ("Morning Run", "unknown"),
    ],
)
def test_activity_type_uses_conservative_title_markers(
    title: str,
    expected: str,
) -> None:
    assert import_strava_activities._activity_type(title) == expected


def _parsed_activity(
    *,
    path: Path,
    start_time: datetime,
    kind: ActivityKind,
    digest_character: str,
) -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=SourceReference(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT,
            source_file_name=path.name,
            content_sha256=digest_character * 64,
        ),
        activity_kind=kind,
        provider_activity_type="running" if kind != ActivityKind.OTHER else "cycling",
        start_time_utc=start_time,
        elapsed_time_s=3_600,
        moving_time_s=3_500,
        distance_m=10_000,
    )


def test_collection_selects_only_recent_running_fit_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent_path = tmp_path / "Hill_Session.fit"
    old_path = tmp_path / "Old_Run.fit"
    cycling_path = tmp_path / "Bike_Ride.fit"
    ignored_path = tmp_path / "route.gpx"
    for path in (recent_path, old_path, cycling_path, ignored_path):
        path.write_bytes(b"synthetic")

    def fake_parse(
        path: Path,
        athlete_id: UUID,
        provider: SourceProvider,
    ) -> ParseResult:
        assert athlete_id == ATHLETE_ID
        assert provider == SourceProvider.STRAVA
        if path == recent_path:
            activity = _parsed_activity(
                path=path,
                start_time=datetime(2026, 9, 3, 5, 0, tzinfo=UTC),
                kind=ActivityKind.RUNNING,
                digest_character="a",
            )
        elif path == old_path:
            activity = _parsed_activity(
                path=path,
                start_time=datetime(2026, 8, 23, 5, 0, tzinfo=UTC),
                kind=ActivityKind.RUNNING,
                digest_character="b",
            )
        else:
            activity = _parsed_activity(
                path=path,
                start_time=datetime(2026, 9, 2, 5, 0, tzinfo=UTC),
                kind=ActivityKind.OTHER,
                digest_character="c",
            )
        return ParseResult(activities=(activity,))

    monkeypatch.setattr(import_strava_activities, "parse_fit_activity", fake_parse)

    inputs, statistics = import_strava_activities._collect_inputs(
        activity_dir=tmp_path,
        athlete_id=ATHLETE_ID,
        athlete_timezone=ZoneInfo("Africa/Casablanca"),
        since=datetime(2026, 8, 24, tzinfo=UTC).date(),
    )

    assert len(inputs) == 1
    assert inputs[0].activity.name == "Hill Session"
    assert inputs[0].activity_type == "workout"
    assert inputs[0].file.source_file_name == "activities/Hill_Session.fit"
    assert statistics.files_discovered == 3
    assert statistics.files_selected == 1
    assert statistics.files_before_since == 1
    assert statistics.non_running_files == 1
    assert statistics.parse_failures == 0
