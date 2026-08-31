"""Tests for the positional Strava activities CSV adapter."""

import csv
from pathlib import Path
from uuid import UUID

from runcoach.ingestion import (
    ActivityKind,
    SourceFormat,
    parse_strava_activities_csv,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")

HEADER = [
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Elapsed Time",
    "Distance",
    "Filename",
    "Elapsed Time",
    "Moving Time",
    "Distance",
    "Elevation Gain",
    "Elevation Loss",
]


def _write_csv(
    path: Path,
    header: list[str],
    rows: list[list[str]],
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def test_adapter_preserves_duplicate_header_positions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activities.csv"
    _write_csv(
        path,
        HEADER,
        [
            [
                "1001",
                "Apr 1, 2026, 6:30:00 AM",
                "Synthetic morning run",
                "Run",
                "display-elapsed-value",
                "display-distance-value",
                "activities/synthetic.fit.gz",
                "3600",
                "3500",
                "10000",
                "217",
                "210",
            ]
        ],
    )

    result = parse_strava_activities_csv(path, ATHLETE_ID)

    assert result.findings == ()
    assert len(result.activities) == 1

    activity = result.activities[0]
    assert activity.activity_kind is ActivityKind.RUNNING
    assert activity.elapsed_time_s == 3600
    assert activity.moving_time_s == 3500
    assert activity.distance_m == 10000
    assert activity.source.source_format is SourceFormat.CSV
    assert activity.source.referenced_file_name == "activities/synthetic.fit.gz"
    assert activity.source.source_row_number == 2
    assert activity.elevation_gain_m == 217
    assert activity.elevation_loss_m == 210


def test_non_running_row_is_staged_as_other(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activities.csv"
    _write_csv(
        path,
        HEADER,
        [
            [
                "1002",
                "2026-04-02T06:30:00Z",
                "Synthetic walk",
                "Walk",
                "unused-display-value",
                "display-distance-value",
                "",
                "1800",
                "1750",
                "2500",
                "",
                "",
            ]
        ],
    )

    result = parse_strava_activities_csv(path, ATHLETE_ID)

    assert result.findings == ()
    assert result.activities[0].activity_kind is ActivityKind.OTHER
    assert result.activities[0].source.referenced_file_name is None


def test_malformed_row_is_reported_without_stopping_import(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activities.csv"
    _write_csv(
        path,
        HEADER,
        [
            [
                "1001",
                "Apr 1, 2026, 6:30:00 AM",
                "Synthetic run",
                "Run",
                "unused-display-value",
                "display-distance-value",
                "activities/synthetic.fit.gz",
                "3600",
                "3500",
                "10000",
                "217",
                "210",
            ],
            ["malformed"],
        ],
    )

    result = parse_strava_activities_csv(path, ATHLETE_ID)

    assert len(result.activities) == 1
    assert len(result.findings) == 1
    assert result.findings[0].code == "STRAVA_ROW_WIDTH_INVALID"
    assert result.findings[0].source_row_number == 3


def test_missing_duplicate_column_is_a_header_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activities.csv"
    incomplete_header = [
        column
        for index, column in enumerate(HEADER)
        if not (column == "Elapsed Time" and index == 7)
    ]
    _write_csv(path, incomplete_header, [])

    result = parse_strava_activities_csv(path, ATHLETE_ID)

    assert result.activities == ()
    assert len(result.findings) == 1
    assert result.findings[0].code == "STRAVA_HEADER_INVALID"
