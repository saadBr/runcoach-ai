"""Tests for the personalized goal-assessment CLI."""

import argparse
import json
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.analytics.goal_assessment import TrainingBlock, assess_goal
from runcoach.analytics.performance import StandardDistance
from runcoach.cli import assess_goals
from runcoach.db.goal_assessments import GoalAssessmentReport

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _report() -> GoalAssessmentReport:
    block = TrainingBlock(
        end_date=date(2026, 8, 27),
        runs=20,
        distance_km=200,
        moving_hours=20,
        longest_run_km=25,
        form_index=5,
        last_run_date=date(2026, 8, 23),
    )
    assessments = tuple(
        assess_goal(
            distance=distance,
            reference_pb_seconds=seconds,
            reference_pb_date=date(2026, 5, 15),
            current_block=block,
            reference_block=block,
        )
        for distance, seconds in (
            (StandardDistance.FIVE_K, 1_181),
            (StandardDistance.TEN_K, 2_464),
        )
    )
    return GoalAssessmentReport(
        as_of_date=date(2026, 8, 27),
        data_through_date=date(2026, 8, 23),
        algorithm_version="same_distance_training_support_v1",
        method_status="experimental_not_validated",
        assessments=assessments,
        unavailable_distances=(
            StandardDistance.HALF_MARATHON,
            StandardDistance.MARATHON,
        ),
    )


def test_iso_date_accepts_valid_date() -> None:
    assert assess_goals._iso_date("2026-08-27") == date(2026, 8, 27)


def test_iso_date_rejects_invalid_date() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        assess_goals._iso_date("27/08/2026")


def test_main_prints_all_assessments_from_environment_athlete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    received: list[tuple[UUID, date | None]] = []

    class FakeService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def assess(self, *, athlete_id: UUID, as_of_date: date | None) -> GoalAssessmentReport:
            received.append((athlete_id, as_of_date))
            return _report()

    monkeypatch.setattr(
        assess_goals,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(assess_goals, "SessionFactory", lambda: nullcontext(fake_session))
    monkeypatch.setattr(assess_goals, "GoalAssessmentQueryService", FakeService)

    assert assess_goals.main(["--as-of-date", "2026-08-27"]) == 0

    assert received == [(ATHLETE_ID, date(2026, 8, 27))]
    payload = json.loads(capsys.readouterr().out)
    assert payload["method_status"] == "experimental_not_validated"
    assert [item["distance"] for item in payload["assessments"]] == ["5k", "10k"]


def test_main_filters_one_distance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeService:
        def __init__(self, session: object) -> None:
            pass

        def assess(self, *, athlete_id: UUID, as_of_date: date | None) -> GoalAssessmentReport:
            return _report()

    monkeypatch.setattr(
        assess_goals,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(assess_goals, "SessionFactory", lambda: nullcontext(object()))
    monkeypatch.setattr(assess_goals, "GoalAssessmentQueryService", FakeService)

    assert assess_goals.main(["--distance", "10k"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["distance"] for item in payload["assessments"]] == ["10k"]


def test_main_requires_athlete_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assess_goals,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        assess_goals.main([])

    assert error.value.code == 2
