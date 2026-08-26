"""Tests for raw sensor import discovery and command orchestration."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from runcoach.cli import import_sensors
from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.models import Activity, SourceActivity
from runcoach.db.sensors import (
    PersistedSensorImportSummary,
    SensorActivityInput,
)
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    NormalizedTrackpoint,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000002")
SOURCE_ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000003")
IMPORT_FILE_ID = UUID("018f0000-0000-7000-8000-000000000004")
BATCH_ID = UUID("018f0000-0000-7000-8000-000000000005")
START_TIME = datetime(2026, 4, 5, 6, 30, tzinfo=UTC)

STRAVA_HASH = "a" * 64
GARMIN_HASH = "b" * 64


def _normalized_activity(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    content_sha256: str,
    external_activity_id: str | None,
    source_file_name: str,
) -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=SourceReference(
            provider=provider,
            source_format=source_format,
            source_file_name=source_file_name,
            content_sha256=content_sha256,
            referenced_file_name=None,
            source_activity_id=external_activity_id,
            source_row_number=2,
        ),
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type=("Run" if provider == SourceProvider.STRAVA else "running"),
        start_time_utc=START_TIME,
        timezone_name="Africa/Casablanca",
        name="Test Run",
        elapsed_time_s=2_500.0,
        moving_time_s=2_480.0,
        distance_m=10_000.0,
        trackpoints=(
            NormalizedTrackpoint(
                sequence=0,
                timestamp_utc=START_TIME,
                elapsed_time_s=0,
                distance_m=0,
                latitude_deg=33.5731,
                longitude_deg=-7.5898,
                altitude_m=25,
                heart_rate_bpm=150,
                cadence_spm=174,
                speed_mps=4,
                power_watts=None,
                temperature_c=None,
            ),
        ),
    )


def _sensor_input(
    *,
    provider: SourceProvider = SourceProvider.STRAVA,
    source_format: SourceFormat = SourceFormat.FIT_GZ,
    content_sha256: str = STRAVA_HASH,
    external_activity_id: str | None = "strava-100",
    source_file_name: str = "activities/100.fit.gz",
) -> SensorActivityInput:
    activity = _normalized_activity(
        provider=provider,
        source_format=source_format,
        content_sha256=content_sha256,
        external_activity_id=external_activity_id,
        source_file_name=source_file_name,
    )
    return SensorActivityInput(
        file=ImportFileDescriptor(
            provider=provider,
            source_format=source_format,
            source_file_name=source_file_name,
            content_sha256=content_sha256,
            storage_key=f"{provider.value}/{source_file_name}",
            size_bytes=1_024,
            media_type=None,
        ),
        activity=activity,
    )


def test_format_detection_and_safe_path_resolution(
    tmp_path: Path,
) -> None:
    nested_directory = tmp_path / "activities"
    nested_directory.mkdir()
    raw_file = nested_directory / "100.fit.gz"
    raw_file.write_bytes(b"test")

    assert import_sensors._detect_format(Path("activity.FIT.GZ")) == SourceFormat.FIT_GZ
    assert import_sensors._detect_format(Path("activity.fit")) == SourceFormat.FIT
    assert import_sensors._detect_format(Path("activity.GPX")) == SourceFormat.GPX
    assert import_sensors._detect_format(Path("activity.csv")) is None

    assert (
        import_sensors._safe_referenced_path(
            tmp_path,
            "activities/100.fit.gz",
        )
        == raw_file.resolve()
    )
    assert (
        import_sensors._safe_referenced_path(
            tmp_path,
            "../outside.fit",
        )
        is None
    )
    assert (
        import_sensors._safe_referenced_path(
            tmp_path,
            "C:/private/activity.fit",
        )
        is None
    )


def test_small_metadata_helpers() -> None:
    assert import_sensors._source_row_number({"source_row_number": 12}) == 12
    assert import_sensors._source_row_number({"source_row_number": "13"}) == 13
    assert import_sensors._source_row_number({"source_row_number": "invalid"}) is None
    assert import_sensors._source_row_number({}) is None

    assert import_sensors._activity_kind("trail_running") == ActivityKind.TRAIL_RUNNING
    assert import_sensors._activity_kind("unknown-provider-value") == ActivityKind.RUNNING
    assert import_sensors._activity_kind(ActivityKind.OTHER.value) == ActivityKind.RUNNING


class _Rows:
    def __init__(
        self,
        rows: list[tuple[SourceActivity, Activity]],
    ) -> None:
        self._rows = rows

    def all(self) -> list[tuple[SourceActivity, Activity]]:
        return self._rows


class _QuerySession:
    def __init__(
        self,
        rows: list[tuple[SourceActivity, Activity]],
    ) -> None:
        self._rows = rows

    def execute(self, statement: object) -> _Rows:
        del statement
        return _Rows(self._rows)


def _catalog_records() -> tuple[SourceActivity, Activity]:
    activity = Activity(
        id=ACTIVITY_ID,
        athlete_id=ATHLETE_ID,
        sport=ActivityKind.RUNNING.value,
        activity_type="unknown",
        name="Test Run",
        start_time_utc=START_TIME,
        original_timezone="Africa/Casablanca",
        local_start_date=date(2026, 4, 5),
        distance_m=Decimal("10000.000"),
        moving_time_ms=2_480_000,
        elapsed_time_ms=2_500_000,
        verification_status="unverified",
    )
    source_activity = SourceActivity(
        id=SOURCE_ACTIVITY_ID,
        import_file_id=IMPORT_FILE_ID,
        activity_id=ACTIVITY_ID,
        provider=SourceProvider.STRAVA.value,
        external_activity_id="strava-100",
        source_start_time=START_TIME,
        source_sport="Run",
        source_distance_m=Decimal("10000.000"),
        source_duration_ms=2_500_000,
        dedupe_fingerprint="c" * 64,
        resolution_status="resolved",
        raw_metadata={
            "referenced_file_name": "activities/100.fit.gz",
            "source_row_number": 2,
        },
    )
    return source_activity, activity


def test_strava_references_are_resolved_and_parsed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity_directory = tmp_path / "activities"
    activity_directory.mkdir()
    source_path = activity_directory / "100.fit.gz"
    source_path.write_bytes(b"strava-fit")

    def fake_parse_fit(
        path: Path,
        athlete_id: UUID,
        provider: SourceProvider,
        *,
        source_activity_id: str | None = None,
        source_row_number: int | None = None,
        activity_kind_override: ActivityKind | None = None,
    ) -> ParseResult:
        assert path == source_path
        assert athlete_id == ATHLETE_ID
        assert provider == SourceProvider.STRAVA
        assert source_activity_id == "strava-100"
        assert source_row_number == 2
        assert activity_kind_override == ActivityKind.RUNNING

        return ParseResult(
            activities=(
                _normalized_activity(
                    provider=provider,
                    source_format=SourceFormat.FIT_GZ,
                    content_sha256=STRAVA_HASH,
                    external_activity_id=source_activity_id,
                    source_file_name=path.name,
                ),
            ),
            findings=(),
        )

    monkeypatch.setattr(
        import_sensors,
        "parse_fit_activity",
        fake_parse_fit,
    )

    source_activity, activity = _catalog_records()
    query_session = cast(
        Session,
        _QuerySession([(source_activity, activity)]),
    )
    statistics = import_sensors.CollectionStatistics()

    inputs = import_sensors._collect_strava_inputs(
        session=query_session,
        athlete_id=ATHLETE_ID,
        root=tmp_path,
        statistics=statistics,
    )

    assert len(inputs) == 1
    assert inputs[0].file.storage_key == ("strava/activities/100.fit.gz")
    assert statistics.strava_references == 1
    assert statistics.strava_files_parsed == 1
    assert statistics.strava_missing_files == 0
    assert statistics.strava_parse_failures == 0


def test_garmin_scan_keeps_only_running_fit_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_path = tmp_path / "running.fit"
    ignored_path = tmp_path / "monitoring.fit"
    running_path.write_bytes(b"running")
    ignored_path.write_bytes(b"monitoring")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    def fake_parse_fit(
        path: Path,
        athlete_id: UUID,
        provider: SourceProvider,
        *,
        source_activity_id: str | None = None,
        source_row_number: int | None = None,
        activity_kind_override: ActivityKind | None = None,
    ) -> ParseResult:
        del source_activity_id, source_row_number, activity_kind_override
        assert athlete_id == ATHLETE_ID
        assert provider == SourceProvider.GARMIN

        if path == running_path:
            return ParseResult(
                activities=(
                    _normalized_activity(
                        provider=provider,
                        source_format=SourceFormat.FIT,
                        content_sha256=GARMIN_HASH,
                        external_activity_id=None,
                        source_file_name=path.name,
                    ),
                ),
                findings=(),
            )

        return ParseResult(activities=(), findings=())

    monkeypatch.setattr(
        import_sensors,
        "parse_fit_activity",
        fake_parse_fit,
    )

    progress: list[tuple[int, int]] = []
    statistics = import_sensors.CollectionStatistics()
    inputs = import_sensors._collect_garmin_inputs(
        athlete_id=ATHLETE_ID,
        root=tmp_path,
        statistics=statistics,
        progress_every=1,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert len(inputs) == 1
    assert inputs[0].file.provider == SourceProvider.GARMIN
    assert statistics.garmin_fit_files_discovered == 2
    assert statistics.garmin_fit_files_scanned == 2
    assert statistics.garmin_running_files == 1
    assert statistics.garmin_ignored_files == 1
    assert statistics.garmin_parse_failures == 0
    assert progress == [(1, 2), (2, 2)]


def test_input_deduplication_is_provider_scoped() -> None:
    statistics = import_sensors.CollectionStatistics()
    strava_input = _sensor_input()
    duplicate_strava_input = _sensor_input()
    garmin_input = _sensor_input(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.FIT,
        content_sha256=STRAVA_HASH,
        external_activity_id=None,
        source_file_name="garmin/activity.fit",
    )

    result = import_sensors._deduplicate_inputs(
        [
            strava_input,
            duplicate_strava_input,
            garmin_input,
        ],
        statistics,
    )

    assert len(result) == 2
    assert statistics.duplicate_inputs_skipped == 1
    assert statistics.total_inputs == 2


class _ContextSession:
    def __init__(self) -> None:
        self.rollback_called = False

    def __enter__(self) -> "_ContextSession":
        return self

    def __exit__(
        self,
        exception_type: object | None,
        exception_value: object | None,
        traceback: object | None,
    ) -> None:
        del exception_type, exception_value, traceback

    def rollback(self) -> None:
        self.rollback_called = True


class _FakeSettings:
    athlete_id = ATHLETE_ID


class _FakeSensorService:
    received_inputs: tuple[SensorActivityInput, ...] = ()

    def __init__(self, session: object) -> None:
        assert isinstance(session, _ContextSession)

    def persist(
        self,
        *,
        athlete_id: UUID,
        parser_bundle_version: str,
        inputs: tuple[SensorActivityInput, ...],
    ) -> PersistedSensorImportSummary:
        assert athlete_id == ATHLETE_ID
        assert parser_bundle_version
        self.__class__.received_inputs = inputs

        return PersistedSensorImportSummary(
            import_batch_id=BATCH_ID,
            total_files=len(inputs),
            accepted_files=len(inputs),
            duplicate_files=0,
            matched_files=len(inputs),
            unmatched_files=0,
            ambiguous_files=0,
            source_links_created=len(inputs),
            activities_enriched=1,
            activities_unchanged=0,
            laps_written=0,
            trackpoints_written=1,
            quality_issues_created=0,
        )


def test_main_orchestrates_collection_and_prints_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context_session = _ContextSession()
    raw_input = _sensor_input()

    def fake_session_factory() -> _ContextSession:
        return context_session

    def fake_get_settings() -> _FakeSettings:
        return _FakeSettings()

    def fake_collect_strava(
        *,
        session: Session,
        athlete_id: UUID,
        root: Path,
        statistics: import_sensors.CollectionStatistics,
    ) -> list[SensorActivityInput]:
        del session
        assert athlete_id == ATHLETE_ID
        assert root == tmp_path
        statistics.strava_references = 1
        statistics.strava_files_parsed = 1
        return [raw_input]

    monkeypatch.setattr(
        import_sensors,
        "SessionFactory",
        fake_session_factory,
    )
    monkeypatch.setattr(
        import_sensors,
        "get_settings",
        fake_get_settings,
    )
    monkeypatch.setattr(
        import_sensors,
        "_collect_strava_inputs",
        fake_collect_strava,
    )
    monkeypatch.setattr(
        import_sensors,
        "SensorPersistenceService",
        _FakeSensorService,
    )

    exit_code = import_sensors.main(
        [
            "--strava-root",
            str(tmp_path),
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert context_session.rollback_called is True
    assert len(_FakeSensorService.received_inputs) == 1
    assert output["collection"]["total_inputs"] == 1
    assert output["persistence"]["matched_files"] == 1
    assert output["persistence"]["trackpoints_written"] == 1
