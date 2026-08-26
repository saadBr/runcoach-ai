"""Database tests for transactional reconciliation persistence."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.db.base import Base
from runcoach.db.ingestion import (
    ImportFileDescriptor,
    IngestionPersistenceError,
    ReconciliationPersistenceService,
    _local_start_date,
)
from runcoach.db.models import (
    Activity,
    ActivityFieldSource,
    Athlete,
    DataQualityIssue,
    ImportBatch,
    ImportFile,
    SourceActivity,
    SourceActivityFile,
)
from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    SourceFormat,
    SourceProvider,
    SourceReference,
    ValidationFinding,
)
from runcoach.ingestion.reconciliation import (
    FieldProvenance,
    MatchMethod,
    ReconciledActivity,
    ReconciliationResult,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
SOURCE_HASH = "a" * 64


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


def _source_reference() -> SourceReference:
    return SourceReference(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_file_name="activities.csv",
        content_sha256=SOURCE_HASH,
        referenced_file_name="activities/100.fit.gz",
        source_activity_id="100",
        source_row_number=2,
    )


def _normalized_activity() -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=_source_reference(),
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type="Run",
        start_time_utc=datetime(2026, 4, 5, 6, 30, tzinfo=UTC),
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


def _reconciliation_result(
    *,
    findings: tuple[ValidationFinding, ...] = (),
) -> ReconciliationResult:
    activity = _normalized_activity()
    reconciled = ReconciledActivity(
        canonical=activity,
        representations=(activity,),
        match_method=MatchMethod.SINGLE_SOURCE,
        field_provenance=(
            FieldProvenance(
                field_name="distance_m",
                source=activity.source,
            ),
            FieldProvenance(
                field_name="elapsed_time_s",
                source=activity.source,
            ),
        ),
    )
    return ReconciliationResult(
        activities=(reconciled,),
        findings=findings,
        excluded_strava_representations=0,
        excluded_garmin_representations=0,
    )


def _file_descriptor(
    *,
    content_sha256: str = SOURCE_HASH,
) -> ImportFileDescriptor:
    return ImportFileDescriptor(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_file_name="activities.csv",
        content_sha256=content_sha256,
        storage_key="strava/activities.csv",
        size_bytes=12_345,
        media_type="text/csv",
    )


def test_file_descriptor_rejects_absolute_storage_path() -> None:
    with pytest.raises(ValueError, match="safe relative logical path"):
        ImportFileDescriptor(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.CSV,
            source_file_name="activities.csv",
            content_sha256=SOURCE_HASH,
            storage_key="C:/Users/example/private/activities.csv",
            size_bytes=100,
        )


def test_file_descriptor_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="64-character hexadecimal"):
        ImportFileDescriptor(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.CSV,
            source_file_name="activities.csv",
            content_sha256="not-a-valid-hash",
            storage_key="strava/activities.csv",
            size_bytes=100,
        )


def test_local_start_date_uses_athlete_timezone_when_source_is_missing() -> None:
    activity = _normalized_activity().model_copy(
        update={
            "start_time_utc": datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
            "timezone_name": None,
        }
    )

    assert _local_start_date(activity, "Asia/Tokyo") == date(2026, 1, 2)


def test_reconciliation_is_persisted_with_provenance(
    db_session: Session,
) -> None:
    service = ReconciliationPersistenceService(db_session)

    summary = service.persist(
        athlete_id=ATHLETE_ID,
        athlete_timezone="Africa/Casablanca",
        parser_bundle_version="test-1",
        files=(_file_descriptor(),),
        result=_reconciliation_result(),
    )

    assert summary.accepted_files == 1
    assert summary.duplicate_files == 0
    assert summary.activities_created == 1
    assert summary.activities_reused == 0
    assert summary.source_activities_created == 1
    assert summary.quality_issues_created == 0

    activity = db_session.scalar(select(Activity))
    assert activity is not None
    assert activity.athlete_id == ATHLETE_ID
    assert activity.sport == "running"
    assert activity.distance_m == Decimal("10000.250")
    assert activity.moving_time_ms == 2_480_500
    assert activity.elapsed_time_ms == 2_500_125
    assert activity.max_hr_bpm == 183

    source_activity = db_session.scalar(select(SourceActivity))
    assert source_activity is not None
    assert source_activity.activity_id == activity.id
    assert source_activity.external_activity_id == "100"
    assert source_activity.raw_metadata["referenced_file_name"] == "activities/100.fit.gz"
    source_file_link = db_session.scalar(select(SourceActivityFile))
    assert source_file_link is not None
    assert source_file_link.source_activity_id == source_activity.id
    assert source_file_link.file_role == "summary"
    assert db_session.scalar(select(func.count()).select_from(ActivityFieldSource)) == 2


def test_reimport_is_idempotent(
    db_session: Session,
) -> None:
    service = ReconciliationPersistenceService(db_session)
    files = (_file_descriptor(),)
    result = _reconciliation_result()

    first = service.persist(
        athlete_id=ATHLETE_ID,
        athlete_timezone="Africa/Casablanca",
        parser_bundle_version="test-1",
        files=files,
        result=result,
    )
    second = service.persist(
        athlete_id=ATHLETE_ID,
        athlete_timezone="Africa/Casablanca",
        parser_bundle_version="test-1",
        files=files,
        result=result,
    )

    assert first.activities_created == 1
    assert second.accepted_files == 0
    assert second.duplicate_files == 1
    assert second.activities_created == 0
    assert second.activities_reused == 1
    assert second.source_activities_created == 0

    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    assert db_session.scalar(select(func.count()).select_from(SourceActivity)) == 1
    assert db_session.scalar(select(func.count()).select_from(ImportFile)) == 2
    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 2
    assert db_session.scalar(select(func.count()).select_from(SourceActivityFile)) == 1


def test_warning_is_persisted_and_updates_batch_status(
    db_session: Session,
) -> None:
    warning = ValidationFinding(
        severity=FindingSeverity.WARNING,
        code="TEST_WARNING",
        message="A reviewable test warning.",
        source_row_number=2,
        field_name="distance_m",
    )
    service = ReconciliationPersistenceService(db_session)

    summary = service.persist(
        athlete_id=ATHLETE_ID,
        athlete_timezone="Africa/Casablanca",
        parser_bundle_version="test-1",
        files=(_file_descriptor(),),
        result=_reconciliation_result(findings=(warning,)),
    )

    assert summary.quality_issues_created == 1

    batch = db_session.get(ImportBatch, summary.import_batch_id)
    assert batch is not None
    assert batch.status == "completed_with_warnings"
    assert batch.warning_count == 1

    issue = db_session.scalar(select(DataQualityIssue))
    assert issue is not None
    assert issue.code == "TEST_WARNING"
    assert issue.observed_value == {"source_row_number": 2}


def test_missing_file_descriptor_rolls_back_transaction(
    db_session: Session,
) -> None:
    service = ReconciliationPersistenceService(db_session)

    with pytest.raises(
        IngestionPersistenceError,
        match="no matching import file descriptor",
    ):
        service.persist(
            athlete_id=ATHLETE_ID,
            athlete_timezone="Africa/Casablanca",
            parser_bundle_version="test-1",
            files=(_file_descriptor(content_sha256="b" * 64),),
            result=_reconciliation_result(),
        )

    assert db_session.scalar(select(func.count()).select_from(Athlete)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0
