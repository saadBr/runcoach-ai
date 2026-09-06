"""Tests for the private Strava run upload and coaching refresh endpoint."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import coaching as coaching_routes
from runcoach.coaching.update import CoachingPipelineResult
from runcoach.coaching.uploads import PreparedRunUpload
from runcoach.config import Settings, get_settings
from runcoach.db.analytics import AnalyticsCalculationSummary
from runcoach.db.ingestion import ImportFileDescriptor
from runcoach.db.sensors import (
    PersistedSensorImportSummary,
    SensorActivityInput,
)
from runcoach.db.session import get_db_session
from runcoach.db.training_plan_tracking import (
    ActivePlanTracking,
    PlanSessionProgress,
    PlanVersionSummary,
    PlanWeekProgress,
)
from runcoach.ingestion.contracts import (
    ActivityKind,
    NormalizedActivity,
    SourceFormat,
    SourceProvider,
    SourceReference,
)
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
BATCH_ID = UUID("018f0000-0000-7000-8000-000000000002")
GOAL_ID = UUID("018f0000-0000-7000-8000-000000000003")
PLAN_ID = UUID("018f0000-0000-7000-8000-000000000004")
CONTENT_SHA256 = "a" * 64


class FakeSession:
    """Minimal configured-athlete lookup used by endpoint tests."""

    def get(self, model: object, identity: UUID) -> object:
        del model
        assert identity == ATHLETE_ID
        return SimpleNamespace(timezone="Africa/Casablanca")


@pytest.fixture
def configured_client(client: TestClient, tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
        private_data_dir=tmp_path,
    )
    app.dependency_overrides[get_db_session] = FakeSession
    yield client
    app.dependency_overrides.clear()


def _prepared_upload() -> PreparedRunUpload:
    source = SourceReference(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.FIT,
        source_file_name="uploads/Tempo_Run.fit",
        content_sha256=CONTENT_SHA256,
    )
    activity = NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=source,
        activity_kind=ActivityKind.RUNNING,
        provider_activity_type="running",
        start_time_utc=datetime(2026, 9, 6, 17, 30, tzinfo=UTC),
        timezone_name="Africa/Casablanca",
        name="Tempo Run",
        elapsed_time_s=2_400.0,
        distance_m=10_000.0,
    )
    sensor_input = SensorActivityInput(
        file=ImportFileDescriptor(
            provider=SourceProvider.STRAVA,
            source_format=SourceFormat.FIT,
            source_file_name="uploads/Tempo_Run.fit",
            content_sha256=CONTENT_SHA256,
            storage_key=f"strava/uploads/{CONTENT_SHA256}",
            size_bytes=7,
            media_type="application/octet-stream",
        ),
        activity=activity,
        activity_type="workout",
    )
    return PreparedRunUpload(input=sensor_input, activity=activity, parser_findings=0)


def _tracking() -> ActivePlanTracking:
    return ActivePlanTracking(
        goal_id=GOAL_ID,
        plan_id=PLAN_ID,
        active_version=2,
        as_of_date=date(2026, 9, 6),
        plan_start_date=date(2026, 9, 7),
        race_date=date(2027, 1, 31),
        status="not_started",
        completed_weeks=0,
        total_weeks=21,
        current_week_number=None,
        planned_distance_to_date_km=0.0,
        actual_distance_to_date_km=0.0,
        adherence_pct=None,
        weeks=(
            PlanWeekProgress(
                week_number=1,
                start_date=date(2026, 9, 7),
                end_date=date(2026, 9, 13),
                phase="base",
                status="upcoming",
                target_distance_km=70.0,
                target_long_run_km=24.0,
                actual_runs=0,
                actual_distance_km=0.0,
                actual_long_run_km=0.0,
                distance_completion_pct=0.0,
                long_run_completion_pct=0.0,
            ),
        ),
        sessions=(
            PlanSessionProgress(
                scheduled_date=date(2026, 9, 7),
                kind="easy",
                title="Easy aerobic run",
                target_distance_km=8.5,
                status="upcoming",
                matched_activity_date=None,
                matched_activity_name=None,
                actual_distance_km=None,
                actual_pace_seconds_per_km=None,
                classified_as=None,
                distance_completion_pct=None,
                pace_status="unavailable",
            ),
        ),
        recommendation_code="plan_not_started",
        recommendation="Begin with the scheduled easy aerobic run.",
        versions=(
            PlanVersionSummary(
                plan_id=PLAN_ID,
                version=2,
                status="active",
                evidence_as_of_date=date(2026, 9, 6),
                created_at=datetime(2026, 9, 6, tzinfo=UTC),
                superseded_at=None,
                recent_weekly_distance_km=77.0,
                first_week_target_km=70.0,
                peak_week_target_km=85.0,
                peak_long_run_km=32.0,
            ),
        ),
    )


def _pipeline(*, imported: bool) -> CoachingPipelineResult:
    sensor_import = None
    if imported:
        sensor_import = PersistedSensorImportSummary(
            import_batch_id=BATCH_ID,
            total_files=1,
            accepted_files=1,
            duplicate_files=0,
            matched_files=1,
            unmatched_files=0,
            ambiguous_files=0,
            source_links_created=1,
            activities_enriched=1,
            activities_unchanged=0,
            laps_written=1,
            trackpoints_written=2,
            quality_issues_created=0,
            activities_created=1,
        )
    return CoachingPipelineResult(
        sensor_import=sensor_import,
        analytics=AnalyticsCalculationSummary(
            as_of_date=date(2026, 9, 6),
            activities_processed=143,
            activities_with_profile=103,
            activities_with_heart_rate_load=98,
            activity_metrics_created=1 if imported else 0,
            activity_metrics_reused=142 if imported else 143,
            daily_loads_created=1 if imported else 0,
            daily_loads_updated=0,
            daily_loads_reused=839,
        ),
        plan_refresh_status="deferred_active_week",
        plan_version_created=False,
        previous_tracking=None,
        tracking=_tracking(),
    )


def test_upload_imports_run_and_returns_updated_coaching(
    configured_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared_upload()
    pipeline_calls: list[tuple[SensorActivityInput, ...]] = []

    def fake_prepare(**kwargs: object) -> PreparedRunUpload:
        path = kwargs["path"]
        assert isinstance(path, Path)
        assert path.read_bytes() == b"FITDATA"
        assert kwargs["filename"] == "Tempo_Run.fit"
        assert kwargs["title"] == "Tempo Run"
        return prepared

    def fake_update(**kwargs: object) -> CoachingPipelineResult:
        inputs = kwargs["inputs"]
        assert isinstance(inputs, tuple)
        pipeline_calls.append(inputs)
        return _pipeline(imported=True)

    monkeypatch.setattr(coaching_routes, "prepare_strava_fit_upload", fake_prepare)
    monkeypatch.setattr(coaching_routes, "known_strava_hashes", lambda *_: frozenset())
    monkeypatch.setattr(coaching_routes, "update_coaching_from_inputs", fake_update)

    response = configured_client.post(
        "/api/v1/coaching/runs",
        content=b"FITDATA",
        headers={
            "Content-Type": "application/octet-stream",
            "X-RunCoach-Filename": "Tempo_Run.fit",
            "X-RunCoach-Title": quote(" Tempo Run ", safe=""),
        },
    )

    assert response.status_code == 200
    assert pipeline_calls == [(prepared.input,)]
    body = response.json()
    assert body["status"] == "updated"
    assert body["activity"]["title"] == "Tempo Run"
    assert body["activity"]["distance_km"] == pytest.approx(10.0)
    assert body["import_summary"]["activities_created"] == 1
    assert body["analytics"]["activities_processed"] == 143
    assert body["tracking"]["recommendation_code"] == "plan_not_started"
    assert list(tmp_path.iterdir()) == []


def test_upload_is_idempotent_for_known_content(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared_upload()
    captured_inputs: list[tuple[SensorActivityInput, ...]] = []
    monkeypatch.setattr(
        coaching_routes,
        "prepare_strava_fit_upload",
        lambda **_: prepared,
    )
    monkeypatch.setattr(
        coaching_routes,
        "known_strava_hashes",
        lambda *_: frozenset({CONTENT_SHA256}),
    )

    def fake_update(**kwargs: object) -> CoachingPipelineResult:
        inputs = kwargs["inputs"]
        assert isinstance(inputs, tuple)
        captured_inputs.append(inputs)
        return _pipeline(imported=False)

    monkeypatch.setattr(coaching_routes, "update_coaching_from_inputs", fake_update)

    response = configured_client.post(
        "/api/v1/coaching/runs",
        content=b"FITDATA",
        headers={
            "X-RunCoach-Filename": "Tempo_Run.fit",
            "X-RunCoach-Title": "Tempo%20Run",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert response.json()["import_summary"] is None
    assert captured_inputs == [()]


@pytest.mark.parametrize(
    ("filename", "title", "expected_detail"),
    (
        ("../run.fit", "Easy run", "safe basename"),
        ("run.gpx", "Easy run", "Only .fit and .fit.gz"),
        ("run.fit", "   ", "title"),
    ),
)
def test_upload_rejects_invalid_metadata(
    configured_client: TestClient,
    filename: str,
    title: str,
    expected_detail: str,
) -> None:
    response = configured_client.post(
        "/api/v1/coaching/runs",
        content=b"FITDATA",
        headers={
            "X-RunCoach-Filename": quote(filename, safe=""),
            "X-RunCoach-Title": quote(title, safe=""),
        },
    )

    assert response.status_code == 422
    assert expected_detail in str(response.json())


def test_upload_enforces_streaming_size_limit(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coaching_routes, "MAX_RUN_UPLOAD_BYTES", 3)

    response = configured_client.post(
        "/api/v1/coaching/runs",
        content=b"1234",
        headers={
            "X-RunCoach-Filename": "run.fit",
            "X-RunCoach-Title": "Easy%20run",
        },
    )

    assert response.status_code == 413
    assert "limit" in response.json()["detail"]
