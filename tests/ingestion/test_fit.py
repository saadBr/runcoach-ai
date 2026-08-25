"""Tests for FIT and FIT.GZ activity parsing."""

import gzip
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from garmin_fit_sdk import FIT_EPOCH_S, Encoder
from garmin_fit_sdk.profile import Profile

from runcoach.ingestion import (
    ActivityKind,
    SourceFormat,
    SourceProvider,
    parse_fit_activity,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
START_TIME = datetime(2026, 4, 1, 6, 30, tzinfo=UTC)


def _semicircles(degrees: float) -> int:
    return int(degrees * (2**31) / 180.0)


def _synthetic_fit(
    *,
    sub_sport: str = "generic",
) -> bytes:
    start_timestamp = int(START_TIME.timestamp()) - FIT_EPOCH_S
    end_timestamp = start_timestamp + 60

    messages = [
        {
            "mesg_num": Profile["mesg_num"]["FILE_ID"],
            "type": "activity",
            "manufacturer": "development",
            "product": 1,
            "time_created": start_timestamp,
            "serial_number": 1,
        },
        {
            "mesg_num": Profile["mesg_num"]["RECORD"],
            "timestamp": start_timestamp,
            "distance": 0,
            "enhanced_speed": 2.5,
            "enhanced_altitude": 10.0,
            "heart_rate": 150,
            "cadence": 85,
            "position_lat": _semicircles(33.5),
            "position_long": _semicircles(-7.6),
        },
        {
            "mesg_num": Profile["mesg_num"]["RECORD"],
            "timestamp": end_timestamp,
            "distance": 10_000,
            "enhanced_speed": 3.0,
            "enhanced_altitude": 11.0,
            "heart_rate": 160,
            "cadence": 90,
            "position_lat": _semicircles(33.5001),
            "position_long": _semicircles(-7.6001),
        },
        {
            "mesg_num": Profile["mesg_num"]["LAP"],
            "message_index": 0,
            "timestamp": end_timestamp,
            "start_time": start_timestamp,
            "total_elapsed_time": 60,
            "total_timer_time": 60,
            "total_distance": 10_000,
            "avg_heart_rate": 155,
            "max_heart_rate": 160,
            "avg_cadence": 85,
            "max_cadence": 90,
        },
        {
            "mesg_num": Profile["mesg_num"]["SESSION"],
            "message_index": 0,
            "timestamp": end_timestamp,
            "start_time": start_timestamp,
            "total_elapsed_time": 60,
            "total_timer_time": 60,
            "total_distance": 10_000,
            "avg_speed": 2.8,
            "max_speed": 3.0,
            "avg_heart_rate": 155,
            "max_heart_rate": 160,
            "avg_cadence": 85,
            "max_cadence": 90,
            "total_calories": 100,
            "sport": "running",
            "sub_sport": sub_sport,
            "first_lap_index": 0,
            "num_laps": 1,
        },
        {
            "mesg_num": Profile["mesg_num"]["ACTIVITY"],
            "timestamp": end_timestamp,
            "num_sessions": 1,
            "total_timer_time": 60,
        },
    ]

    encoder = Encoder()

    for message in messages:
        encoder.write_mesg(message)

    return bytes(encoder.close())


def test_fit_activity_normalizes_session_laps_and_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.fit"
    path.write_bytes(_synthetic_fit())

    result = parse_fit_activity(
        path,
        ATHLETE_ID,
        SourceProvider.GARMIN,
    )

    assert result.findings == ()
    assert len(result.activities) == 1

    activity = result.activities[0]
    assert activity.activity_kind is ActivityKind.RUNNING
    assert activity.source.source_format is SourceFormat.FIT
    assert activity.elapsed_time_s == 60
    assert activity.distance_m == 10_000
    assert activity.average_cadence_spm == 170
    assert len(activity.laps) == 1
    assert activity.laps[0].average_cadence_spm == 170
    assert len(activity.trackpoints) == 2
    assert activity.trackpoints[1].cadence_spm == 180
    assert activity.trackpoints[0].latitude_deg == pytest.approx(
        33.5,
        abs=0.000001,
    )
    assert activity.trackpoints[0].longitude_deg == pytest.approx(
        -7.6,
        abs=0.000001,
    )


def test_fit_gz_uses_logical_fit_content_hash(
    tmp_path: Path,
) -> None:
    content = _synthetic_fit()
    fit_path = tmp_path / "synthetic.fit"
    gzip_path = tmp_path / "synthetic.fit.gz"

    fit_path.write_bytes(content)

    with gzip.open(gzip_path, "wb") as stream:
        stream.write(content)

    fit_result = parse_fit_activity(
        fit_path,
        ATHLETE_ID,
        SourceProvider.GARMIN,
    )
    gzip_result = parse_fit_activity(
        gzip_path,
        ATHLETE_ID,
        SourceProvider.STRAVA,
    )

    fit_activity = fit_result.activities[0]
    gzip_activity = gzip_result.activities[0]

    assert gzip_activity.source.source_format is SourceFormat.FIT_GZ
    assert gzip_activity.source.content_sha256 == fit_activity.source.content_sha256


def test_treadmill_sub_sport_is_normalized(
    tmp_path: Path,
) -> None:
    path = tmp_path / "treadmill.fit"
    path.write_bytes(_synthetic_fit(sub_sport="treadmill"))

    result = parse_fit_activity(
        path,
        ATHLETE_ID,
        SourceProvider.GARMIN,
    )

    assert result.activities[0].activity_kind is ActivityKind.TREADMILL_RUNNING


def test_invalid_fit_file_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.fit"
    path.write_bytes(b"not-a-fit-file")

    result = parse_fit_activity(
        path,
        ATHLETE_ID,
        SourceProvider.STRAVA,
    )

    assert result.activities == ()
    assert result.findings[0].code == "FIT_FILE_INVALID"


def test_fit_without_session_is_rejected(
    tmp_path: Path,
) -> None:
    encoder = Encoder()
    encoder.write_mesg(
        {
            "mesg_num": Profile["mesg_num"]["FILE_ID"],
            "type": "activity",
            "manufacturer": "development",
            "product": 1,
            "time_created": int(START_TIME.timestamp()) - FIT_EPOCH_S,
        }
    )

    path = tmp_path / "no-session.fit"
    path.write_bytes(bytes(encoder.close()))

    result = parse_fit_activity(
        path,
        ATHLETE_ID,
        SourceProvider.GARMIN,
    )

    assert result.activities == ()
    assert result.findings[0].code == "FIT_SESSION_MISSING"
