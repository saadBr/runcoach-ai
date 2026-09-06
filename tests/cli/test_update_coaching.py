"""Tests for the one-command coaching-data update workflow."""

import argparse
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from runcoach.cli import update_coaching
from runcoach.cli.import_strava_activities import CollectionStatistics
from runcoach.coaching import update as coaching_update
from runcoach.db.analytics import AnalyticsCalculationSummary
from runcoach.db.sensors import PersistedSensorImportSummary, SensorActivityInput
from runcoach.db.training_plan_tracking import (
    ActivePlanTracking,
    PlanSessionProgress,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
GOAL_ID = UUID("018f0000-0000-7000-8000-000000000002")
PLAN_ID = UUID("018f0000-0000-7000-8000-000000000003")
BATCH_ID = UUID("018f0000-0000-7000-8000-000000000004")


class FakeSession:
    """Minimal session behavior used by the orchestration tests."""

    def __init__(self) -> None:
        self.rollbacks = 0

    def get(self, model: object, identity: UUID) -> object:
        del model
        assert identity == ATHLETE_ID
        return SimpleNamespace(timezone="Africa/Casablanca")

    def rollback(self) -> None:
        self.rollbacks += 1


def _tracking(*, as_of_date: date, final_session_date: date) -> ActivePlanTracking:
    return ActivePlanTracking(
        goal_id=GOAL_ID,
        plan_id=PLAN_ID,
        active_version=2,
        as_of_date=as_of_date,
        plan_start_date=date(2026, 9, 7),
        race_date=date(2026, 10, 25),
        status="in_progress",
        completed_weeks=0,
        total_weeks=7,
        current_week_number=1,
        planned_distance_to_date_km=20.0,
        actual_distance_to_date_km=10.0,
        adherence_pct=50.0,
        weeks=(),
        sessions=(
            PlanSessionProgress(
                scheduled_date=final_session_date,
                kind="long",
                title="Long aerobic run",
                target_distance_km=19.1,
                status="upcoming" if as_of_date < final_session_date else "completed",
                matched_activity_date=None,
                matched_activity_name=None,
                actual_distance_km=None,
                actual_pace_seconds_per_km=None,
                classified_as=None,
                distance_completion_pct=None,
                pace_status="unavailable",
            ),
        ),
        recommendation_code="continue_as_planned",
        recommendation="Continue with the scheduled week.",
        versions=(),
    )


def _analytics_summary(as_of_date: date) -> AnalyticsCalculationSummary:
    return AnalyticsCalculationSummary(
        as_of_date=as_of_date,
        activities_processed=143,
        activities_with_profile=103,
        activities_with_heart_rate_load=98,
        activity_metrics_created=1,
        activity_metrics_reused=142,
        daily_loads_created=1,
        daily_loads_updated=0,
        daily_loads_reused=839,
    )


def _sensor_summary() -> PersistedSensorImportSummary:
    return PersistedSensorImportSummary(
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
        laps_written=10,
        trackpoints_written=1_000,
        quality_issues_created=0,
        activities_created=1,
    )


def test_iso_date_rejects_invalid_date() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        update_coaching._iso_date("07-09-2026")


@pytest.mark.parametrize(
    ("as_of_date", "expected"),
    (
        (date(2026, 9, 12), False),
        (date(2026, 9, 13), True),
    ),
)
def test_plan_refresh_waits_for_final_detailed_session(
    as_of_date: date,
    expected: bool,
) -> None:
    tracking = _tracking(
        as_of_date=as_of_date,
        final_session_date=date(2026, 9, 13),
    )

    assert update_coaching._should_refresh_plan(tracking) is expected


def test_update_imports_unseen_file_and_defers_plan_refresh_midweek(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = FakeSession()
    tracking = _tracking(
        as_of_date=date(2026, 9, 8),
        final_session_date=date(2026, 9, 13),
    )
    sensor_summary = _sensor_summary()
    analytics_summary = _analytics_summary(date(2026, 9, 8))
    calls: list[str] = []

    monkeypatch.setattr(update_coaching, "_known_strava_hashes", lambda *_: frozenset())
    monkeypatch.setattr(
        update_coaching,
        "_collect_inputs",
        lambda **_: (
            cast(tuple[SensorActivityInput, ...], (object(),)),
            CollectionStatistics(files_discovered=1, files_selected=1),
        ),
    )
    monkeypatch.setattr(
        coaching_update,
        "latest_running_date",
        lambda *_: date(2026, 9, 8),
    )

    class FakeSensorService:
        def __init__(self, session: Session) -> None:
            del session

        def persist(self, **kwargs: object) -> PersistedSensorImportSummary:
            del kwargs
            calls.append("import")
            return sensor_summary

    class FakeAnalyticsService:
        def __init__(self, session: Session) -> None:
            del session

        def calculate(self, **kwargs: object) -> AnalyticsCalculationSummary:
            del kwargs
            calls.append("analytics")
            return analytics_summary

    class FakeTrackingService:
        def __init__(self, session: Session) -> None:
            del session

        def overview(self, **kwargs: object) -> ActivePlanTracking:
            del kwargs
            calls.append("tracking")
            return tracking

    class UnexpectedPlanService:
        def __init__(self, session: Session) -> None:
            del session
            pytest.fail("The active plan must remain stable during its detailed week.")

    monkeypatch.setattr(coaching_update, "SensorPersistenceService", FakeSensorService)
    monkeypatch.setattr(coaching_update, "DeterministicAnalyticsService", FakeAnalyticsService)
    monkeypatch.setattr(coaching_update, "TrainingPlanTrackingService", FakeTrackingService)
    monkeypatch.setattr(
        coaching_update,
        "TrainingPlanPersistenceService",
        UnexpectedPlanService,
    )

    result = update_coaching.run_coaching_update(
        session=cast(Session, fake_session),
        athlete_id=ATHLETE_ID,
        activity_dir=tmp_path,
        since=None,
    )

    assert calls == ["import", "analytics", "tracking"]
    assert result.sensor_import is sensor_summary
    assert result.plan_refresh_status == "deferred_active_week"
    assert result.plan_version_created is False
    assert result.tracking is tracking
    assert fake_session.rollbacks == 3


def test_update_skips_import_and_rolls_plan_after_detailed_week(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = FakeSession()
    prior = _tracking(
        as_of_date=date(2026, 9, 13),
        final_session_date=date(2026, 9, 13),
    )
    current = _tracking(
        as_of_date=date(2026, 9, 13),
        final_session_date=date(2026, 9, 20),
    )
    analytics_summary = _analytics_summary(date(2026, 9, 13))
    tracking_results = iter((prior, current))

    monkeypatch.setattr(update_coaching, "_known_strava_hashes", lambda *_: frozenset())
    monkeypatch.setattr(
        update_coaching,
        "_collect_inputs",
        lambda **_: ((), CollectionStatistics(known_files_skipped=12)),
    )
    monkeypatch.setattr(
        coaching_update,
        "latest_running_date",
        lambda *_: date(2026, 9, 13),
    )

    class FakeAnalyticsService:
        def __init__(self, session: Session) -> None:
            del session

        def calculate(self, **kwargs: object) -> AnalyticsCalculationSummary:
            del kwargs
            return analytics_summary

    class FakeTrackingService:
        def __init__(self, session: Session) -> None:
            del session

        def overview(self, **kwargs: object) -> ActivePlanTracking:
            del kwargs
            return next(tracking_results)

    class FakePlanService:
        def __init__(self, session: Session) -> None:
            del session

        def refresh_active(self, **kwargs: object) -> object:
            del kwargs
            return SimpleNamespace(created=True)

    monkeypatch.setattr(coaching_update, "DeterministicAnalyticsService", FakeAnalyticsService)
    monkeypatch.setattr(coaching_update, "TrainingPlanTrackingService", FakeTrackingService)
    monkeypatch.setattr(coaching_update, "TrainingPlanPersistenceService", FakePlanService)

    result = update_coaching.run_coaching_update(
        session=cast(Session, fake_session),
        athlete_id=ATHLETE_ID,
        activity_dir=tmp_path,
        since=None,
    )

    assert result.sensor_import is None
    assert result.plan_refresh_status == "refreshed"
    assert result.plan_version_created is True
    assert result.previous_tracking is prior
    assert result.tracking is current
    assert fake_session.rollbacks == 4


def test_result_output_is_compact_and_serializable() -> None:
    tracking = _tracking(
        as_of_date=date(2026, 9, 8),
        final_session_date=date(2026, 9, 13),
    )
    result = update_coaching.CoachingUpdateResult(
        collection=CollectionStatistics(known_files_skipped=12),
        sensor_import=None,
        analytics=_analytics_summary(date(2026, 9, 8)),
        plan_refresh_status="deferred_active_week",
        plan_version_created=False,
        previous_tracking=None,
        tracking=tracking,
    )

    output = update_coaching._result_output(result)

    assert output["import"] == {"status": "no_new_files", "summary": None}
    assert cast(dict[str, object], output["plan_refresh"])["status"] == ("deferred_active_week")
    assert cast(dict[str, object], output["tracking"])["recommendation"] == (
        "Continue with the scheduled week."
    )
