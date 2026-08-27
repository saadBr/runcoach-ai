"""Tests for the deterministic analytics CLI."""

import argparse
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.cli import calculate_analytics

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@dataclass(frozen=True)
class FakeAnalyticsSummary:
    """Serializable result returned by the fake analytics service."""

    as_of_date: date
    activities_processed: int
    activities_with_profile: int
    activities_with_heart_rate_load: int
    activity_metrics_created: int
    activity_metrics_reused: int
    daily_loads_created: int
    daily_loads_updated: int
    daily_loads_reused: int


def test_iso_date_accepts_valid_date() -> None:
    assert calculate_analytics._iso_date("2026-08-27") == date(
        2026,
        8,
        27,
    )


def test_iso_date_rejects_invalid_date() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        calculate_analytics._iso_date("27-08-2026")


def test_main_calculates_analytics_for_environment_athlete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    received: list[tuple[UUID, date]] = []

    class FakeAnalyticsService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def calculate(
            self,
            *,
            athlete_id: UUID,
            as_of_date: date,
        ) -> FakeAnalyticsSummary:
            received.append((athlete_id, as_of_date))
            return FakeAnalyticsSummary(
                as_of_date=as_of_date,
                activities_processed=130,
                activities_with_profile=85,
                activities_with_heart_rate_load=84,
                activity_metrics_created=130,
                activity_metrics_reused=0,
                daily_loads_created=829,
                daily_loads_updated=0,
                daily_loads_reused=0,
            )

    monkeypatch.setattr(
        calculate_analytics,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(
        calculate_analytics,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        calculate_analytics,
        "DeterministicAnalyticsService",
        FakeAnalyticsService,
    )

    exit_code = calculate_analytics.main(
        [
            "--as-of-date",
            "2026-08-27",
        ]
    )

    assert exit_code == 0
    assert received == [
        (
            ATHLETE_ID,
            date(2026, 8, 27),
        )
    ]

    output = json.loads(capsys.readouterr().out)
    assert output["as_of_date"] == "2026-08-27"
    assert output["activities_processed"] == 130
    assert output["activity_metrics_created"] == 130
    assert output["daily_loads_created"] == 829


def test_main_requires_an_athlete_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        calculate_analytics,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        calculate_analytics.main(
            [
                "--as-of-date",
                "2026-08-27",
            ]
        )

    assert error.value.code == 2
