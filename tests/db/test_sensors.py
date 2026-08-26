"""Tests for transactional raw sensor persistence."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.db.base import Base
from runcoach.db.ingestion import (
    ImportFileDescriptor,
    ReconciliationPersistenceService,
)
from runcoach.db.models import (
    Activity,
    DataQualityIssue,
    ImportBatch,
    ImportFile,
    Lap,
    SourceActivity,
    SourceActivityFile,
    Trackpoint,
)
from runcoach.db.sensors import (
    PersistedSensorImportSummary,
    SensorActivityInput,
    SensorPersistenceError,
    SensorPersistenceService,
)
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    NormalizedLap,
    NormalizedTrackpoint,
    SourceFormat,
    SourceProvider,
    SourceReference,
)
from runcoach.ingestion.reconciliation import (
    FieldProvenance,
    MatchMethod,
    ReconciledActivity,
    ReconciliationResult,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
START_TIME = datetime(2026, 4, 5, 6, 30, tzinfo=UTC)

STRAVA_SUMMARY_HASH = "a" * 64
GARMIN_SUMMARY_HASH = "b" * 64
STRAVA_RAW_HASH = "c" * 64
GARMIN_RAW_HASH = "d" * 64
UNMATCHED_RAW_HASH = "e" * 64


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:
        yield session

    engine.dispose()


def _summary_source(provider: SourceProvider) -> SourceReference:
    if provider == SourceProvider.STRAVA:
        return SourceReference(
            provider=provider,
            source_format=SourceFormat.CSV,
            source_file_name="activities.csv",
            content_sha256=STRAVA_SUMMARY_HASH,
            referenced_file_name="activities/100.fit.gz",
            source_activity_id="strava-100",
            source_row_number=2,
        )

    return SourceReference(
        provider=provider,
        source_format=SourceFormat.JSON,
        source_file_name="summarizedActivities.json",
        content_sha256=GARMIN_SUMMARY_HASH,
        referenced_file_name=None,
        source_activity_id="garmin-200",
        source_row_number=1,
    )


def _summary_activity(provider: SourceProvider) -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=_summary_source(provider),
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type=("Run" if provider == SourceProvider.STRAVA else "running"),
        start_time_utc=START_TIME,
        timezone_name="Africa/Casablanca",
        name="Morning Run",
        elapsed_time_s=2_500.125,
        moving_time_s=2_480.5,
        distance_m=10_000.25,
        elevation_gain_m=75.4,
        average_heart_rate_bpm=165,
        maximum_heart_rate_bpm=183,
        average_cadence_spm=176.2,
        calories_kcal=650,
    )


def _summary_descriptor(
    provider: SourceProvider,
) -> ImportFileDescriptor:
    if provider == SourceProvider.STRAVA:
        return ImportFileDescriptor(
            provider=provider,
            source_format=SourceFormat.CSV,
            source_file_name="activities.csv",
            content_sha256=STRAVA_SUMMARY_HASH,
            storage_key="strava/activities.csv",
            size_bytes=12_345,
            media_type="text/csv",
        )

    return ImportFileDescriptor(
        provider=provider,
        source_format=SourceFormat.JSON,
        source_file_name="summarizedActivities.json",
        content_sha256=GARMIN_SUMMARY_HASH,
        storage_key="garmin/summarizedActivities.json",
        size_bytes=23_456,
        media_type="application/json",
    )


def _seed_summary_data(db_session: Session) -> None:
    strava_activity = _summary_activity(SourceProvider.STRAVA)
    garmin_activity = _summary_activity(SourceProvider.GARMIN)

    result = ReconciliationResult(
        activities=(
            ReconciledActivity(
                canonical=strava_activity,
                representations=(
                    strava_activity,
                    garmin_activity,
                ),
                match_method=MatchMethod.CROSS_SOURCE_STRONG,
                field_provenance=(
                    FieldProvenance(
                        field_name="distance_m",
                        source=garmin_activity.source,
                    ),
                    FieldProvenance(
                        field_name="elapsed_time_s",
                        source=garmin_activity.source,
                    ),
                ),
            ),
        ),
        findings=(),
        excluded_strava_representations=0,
        excluded_garmin_representations=0,
    )

    ReconciliationPersistenceService(db_session).persist(
        athlete_id=ATHLETE_ID,
        athlete_timezone="Africa/Casablanca",
        parser_bundle_version="summary-test-1",
        files=(
            _summary_descriptor(SourceProvider.STRAVA),
            _summary_descriptor(SourceProvider.GARMIN),
        ),
        result=result,
        athlete_display_name="Test Athlete",
    )


def _raw_source(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    content_sha256: str,
    external_activity_id: str | None,
) -> SourceReference:
    source_file_name = (
        "garmin/raw-activity.fit" if provider == SourceProvider.GARMIN else "activities/100.fit.gz"
    )
    return SourceReference(
        provider=provider,
        source_format=source_format,
        source_file_name=source_file_name,
        content_sha256=content_sha256,
        referenced_file_name=None,
        source_activity_id=external_activity_id,
        source_row_number=None,
    )


def _raw_activity(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    content_sha256: str,
    external_activity_id: str | None,
    trackpoint_count: int,
    start_time: datetime = START_TIME,
) -> NormalizedActivity:
    trackpoints = tuple(
        NormalizedTrackpoint(
            sequence=index,
            timestamp_utc=start_time + timedelta(seconds=index * 10),
            elapsed_time_s=float(index * 10),
            distance_m=float(index * 100),
            latitude_deg=33.5731 + index * 0.0001,
            longitude_deg=-7.5898 + index * 0.0001,
            altitude_m=25.0 + index,
            heart_rate_bpm=150 + index,
            cadence_spm=174.0 + index,
            speed_mps=4.0,
            power_watts=None,
            temperature_c=None,
        )
        for index in range(trackpoint_count)
    )

    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=_raw_source(
            provider=provider,
            source_format=source_format,
            content_sha256=content_sha256,
            external_activity_id=external_activity_id,
        ),
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type=("Run" if provider == SourceProvider.STRAVA else "running"),
        start_time_utc=start_time,
        timezone_name="Africa/Casablanca",
        name="Morning Run",
        elapsed_time_s=2_500.125,
        moving_time_s=2_480.5,
        distance_m=10_000.25,
        elevation_gain_m=75.4,
        average_heart_rate_bpm=165,
        maximum_heart_rate_bpm=183,
        average_cadence_spm=176.2,
        laps=(
            NormalizedLap(
                sequence=0,
                start_time_utc=start_time,
                elapsed_time_s=2_500.125,
                moving_time_s=2_480.5,
                distance_m=10_000.25,
                elevation_gain_m=75.4,
                elevation_loss_m=70.2,
                average_heart_rate_bpm=165,
                maximum_heart_rate_bpm=183,
                average_cadence_spm=176.2,
                maximum_cadence_spm=188,
            ),
        ),
        trackpoints=trackpoints,
    )


def _raw_input(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    content_sha256: str,
    external_activity_id: str | None,
    trackpoint_count: int = 3,
    start_time: datetime = START_TIME,
) -> SensorActivityInput:
    activity = _raw_activity(
        provider=provider,
        source_format=source_format,
        content_sha256=content_sha256,
        external_activity_id=external_activity_id,
        trackpoint_count=trackpoint_count,
        start_time=start_time,
    )
    return SensorActivityInput(
        file=ImportFileDescriptor(
            provider=provider,
            source_format=source_format,
            source_file_name=activity.source.source_file_name,
            content_sha256=content_sha256,
            storage_key=activity.source.source_file_name,
            size_bytes=45_678,
            media_type=None,
        ),
        activity=activity,
    )


def _persist(
    db_session: Session,
    *inputs: SensorActivityInput,
) -> PersistedSensorImportSummary:
    return SensorPersistenceService(db_session).persist(
        athlete_id=ATHLETE_ID,
        parser_bundle_version="sensor-test-1",
        inputs=tuple(inputs),
    )


def test_strava_fit_detail_is_persisted(
    db_session: Session,
) -> None:
    _seed_summary_data(db_session)

    summary = _persist(
        db_session,
        _raw_input(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT_GZ,
            content_sha256=STRAVA_RAW_HASH,
            external_activity_id="strava-100",
        ),
    )

    assert summary.accepted_files == 1
    assert summary.duplicate_files == 0
    assert summary.matched_files == 1
    assert summary.activities_enriched == 1
    assert summary.laps_written == 1
    assert summary.trackpoints_written == 3

    activity = db_session.scalar(select(Activity))
    assert activity is not None
    assert activity.canonical_sensor_source_id is not None

    selected_source = db_session.get(
        SourceActivity,
        activity.canonical_sensor_source_id,
    )
    assert selected_source is not None
    assert selected_source.provider == SourceProvider.STRAVA.value
    assert selected_source.raw_metadata["canonical_sensor_sha256"] == STRAVA_RAW_HASH
    assert selected_source.raw_metadata["canonical_sensor_format"] == SourceFormat.FIT_GZ.value

    assert db_session.scalar(select(func.count()).select_from(Lap)) == 1
    assert db_session.scalar(select(func.count()).select_from(Trackpoint)) == 3
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SourceActivityFile)
            .where(SourceActivityFile.file_role == "sensor")
        )
        == 1
    )


def test_garmin_fit_is_preferred_over_strava_fit(
    db_session: Session,
) -> None:
    _seed_summary_data(db_session)

    summary = _persist(
        db_session,
        _raw_input(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT_GZ,
            content_sha256=STRAVA_RAW_HASH,
            external_activity_id="strava-100",
            trackpoint_count=4,
        ),
        _raw_input(
            provider=SourceProvider.GARMIN,
            source_format=SourceFormat.FIT,
            content_sha256=GARMIN_RAW_HASH,
            external_activity_id="garmin-200",
            trackpoint_count=2,
        ),
    )

    assert summary.matched_files == 2
    assert summary.source_links_created == 2
    assert summary.activities_enriched == 1
    assert summary.trackpoints_written == 2

    activity = db_session.scalar(select(Activity))
    assert activity is not None
    assert activity.canonical_sensor_source_id is not None

    selected_source = db_session.get(
        SourceActivity,
        activity.canonical_sensor_source_id,
    )
    assert selected_source is not None
    assert selected_source.provider == SourceProvider.GARMIN.value
    assert selected_source.raw_metadata["canonical_sensor_sha256"] == GARMIN_RAW_HASH
    assert db_session.scalar(select(func.count()).select_from(Trackpoint)) == 2


def test_raw_sensor_reimport_is_idempotent(
    db_session: Session,
) -> None:
    _seed_summary_data(db_session)
    raw_input = _raw_input(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.FIT,
        content_sha256=GARMIN_RAW_HASH,
        external_activity_id="garmin-200",
    )

    first = _persist(db_session, raw_input)
    second = _persist(db_session, raw_input)

    assert first.accepted_files == 1
    assert first.activities_enriched == 1

    assert second.accepted_files == 0
    assert second.duplicate_files == 1
    assert second.activities_enriched == 0
    assert second.activities_unchanged == 1
    assert second.laps_written == 0
    assert second.trackpoints_written == 0
    assert second.source_links_created == 0

    assert db_session.scalar(select(func.count()).select_from(Lap)) == 1
    assert db_session.scalar(select(func.count()).select_from(Trackpoint)) == 3
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SourceActivityFile)
            .where(SourceActivityFile.file_role == "sensor")
        )
        == 1
    )


def test_unmatched_raw_activity_creates_warning(
    db_session: Session,
) -> None:
    _seed_summary_data(db_session)

    summary = _persist(
        db_session,
        _raw_input(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT_GZ,
            content_sha256=UNMATCHED_RAW_HASH,
            external_activity_id=None,
            start_time=START_TIME + timedelta(days=1),
        ),
    )

    assert summary.matched_files == 0
    assert summary.unmatched_files == 1
    assert summary.quality_issues_created == 1
    assert summary.activities_enriched == 0

    batch = db_session.get(ImportBatch, summary.import_batch_id)
    assert batch is not None
    assert batch.status == "completed_with_warnings"
    assert batch.warning_count == 1

    issue = db_session.scalar(select(DataQualityIssue))
    assert issue is not None
    assert issue.code == "RAW_ACTIVITY_UNMATCHED"
    assert issue.severity == "warning"

    activity = db_session.scalar(select(Activity))
    assert activity is not None
    assert activity.canonical_sensor_source_id is None


def test_sensor_failure_rolls_back_the_complete_batch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_summary_data(db_session)

    def fail_selection(
        self: SensorPersistenceService,
        *,
        selected: object,
        selected_at: datetime,
    ) -> tuple[bool, int, int]:
        del self, selected, selected_at
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(
        SensorPersistenceService,
        "_persist_selection",
        fail_selection,
    )

    with pytest.raises(
        SensorPersistenceError,
        match="rolled back",
    ):
        _persist(
            db_session,
            _raw_input(
                provider=SourceProvider.GARMIN,
                source_format=SourceFormat.FIT,
                content_sha256=GARMIN_RAW_HASH,
                external_activity_id="garmin-200",
            ),
        )

    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert db_session.scalar(select(func.count()).select_from(ImportFile)) == 2
    assert db_session.scalar(select(func.count()).select_from(Lap)) == 0
    assert db_session.scalar(select(func.count()).select_from(Trackpoint)) == 0
