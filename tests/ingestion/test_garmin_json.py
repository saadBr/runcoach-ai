"""Tests for Garmin summarized-activity JSON parsing."""

import json
from pathlib import Path
from uuid import UUID

from runcoach.ingestion import (
    ActivityKind,
    SourceFormat,
    parse_garmin_activity_summaries,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _write_json(
    path: Path,
    payload: object,
) -> None:
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _running_record() -> dict[str, object]:
    return {
        "activityId": 1001,
        "name": "Synthetic run",
        "activityType": "running",
        "sportType": "RUNNING",
        "timeZoneId": "Africa/Casablanca",
        "startTimeGmt": "2026-04-01T06:30:00Z",
        "duration": 3_600_000,
        "elapsedDuration": 3_610_000,
        "movingDuration": 3_500_000,
        "distance": 1_000_000,
        "elevationGain": 21_713,
        "elevationLoss": 21_050,
        "avgSpeed": 2.8,
        "maxSpeed": 3.2,
        "avgHr": 155,
        "maxHr": 180,
        "minHr": 100,
        "avgRunCadence": 87,
        "maxRunCadence": 95,
        "steps": 9_000,
        "calories": 700,
        "vO2MaxValue": 55.0,
        "aerobicTrainingEffect": 4.0,
        "anaerobicTrainingEffect": 1.5,
        "trainingEffectLabel": "HIGHLY_IMPROVING",
    }


def test_running_summary_normalizes_units_and_metrics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "summaries.json"
    _write_json(
        path,
        {"summarizedActivitiesExport": [_running_record()]},
    )

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert result.findings == ()
    assert len(result.activities) == 1

    activity = result.activities[0]
    assert activity.activity_kind is ActivityKind.RUNNING
    assert activity.source.source_format is SourceFormat.JSON
    assert activity.source.source_activity_id == "1001"
    assert activity.elapsed_time_s == 3610
    assert activity.moving_time_s == 3500
    assert activity.distance_m == 10_000
    assert activity.average_cadence_spm == 174
    assert activity.maximum_cadence_spm == 190
    assert activity.provider_vo2max == 55
    assert activity.provider_aerobic_training_effect == 4
    assert activity.provider_anaerobic_training_effect == 1.5
    assert activity.elevation_gain_m == 217.13
    assert activity.elevation_loss_m == 210.5


def test_treadmill_and_non_running_types_are_staged(
    tmp_path: Path,
) -> None:
    treadmill = _running_record()
    treadmill["activityId"] = 1002
    treadmill["activityType"] = "treadmill_running"

    cycling = _running_record()
    cycling["activityId"] = 1003
    cycling["activityType"] = "indoor_cycling"

    path = tmp_path / "summaries.json"
    _write_json(
        path,
        {
            "wrapper": {
                "summarizedActivitiesExport": [
                    treadmill,
                    cycling,
                ]
            }
        },
    )

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert result.findings == ()
    assert result.activities[0].activity_kind is ActivityKind.TREADMILL_RUNNING
    assert result.activities[1].activity_kind is ActivityKind.OTHER


def test_numeric_millisecond_timestamp_is_supported(
    tmp_path: Path,
) -> None:
    record = _running_record()
    record["startTimeGmt"] = 1_775_025_000_000

    path = tmp_path / "summaries.json"
    _write_json(
        path,
        {"summarizedActivitiesExport": [record]},
    )

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert result.findings == ()
    assert result.activities[0].start_time_utc.year == 2026


def test_invalid_record_does_not_stop_valid_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "summaries.json"
    _write_json(
        path,
        {
            "summarizedActivitiesExport": [
                _running_record(),
                {"activityId": 1002},
            ]
        },
    )

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert len(result.activities) == 1
    assert len(result.findings) == 1
    assert result.findings[0].code == "GARMIN_SUMMARY_RECORD_INVALID"
    assert result.findings[0].source_row_number == 2


def test_missing_container_is_reported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "other.json"
    _write_json(path, {"unrelated": []})

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert result.activities == ()
    assert result.findings[0].code == "GARMIN_SUMMARY_CONTAINER_MISSING"


def test_invalid_json_is_reported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")

    result = parse_garmin_activity_summaries(
        path,
        ATHLETE_ID,
    )

    assert result.activities == ()
    assert result.findings[0].code == "GARMIN_JSON_INVALID"
