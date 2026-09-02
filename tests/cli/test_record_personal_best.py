"""Tests for the verified personal-best CLI."""

import argparse
import json
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.cli import record_personal_best
from runcoach.db.personal_bests import PersonalBestInput

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000010")


@dataclass(frozen=True)
class FakeResult:
    """Serializable result returned by the fake persistence service."""

    personal_best_id: UUID
    created: bool
    superseded_personal_best_id: UUID | None


def test_elapsed_time_parser_accepts_minute_and_hour_formats() -> None:
    assert record_personal_best._elapsed_time_ms("19:41") == 1_181_000
    assert record_personal_best._elapsed_time_ms("1:33:26") == 5_606_000


@pytest.mark.parametrize("value", ("0:00", "1:60", "1:60:00", "abc", "1"))
def test_elapsed_time_parser_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        record_personal_best._elapsed_time_ms(value)


def test_main_records_environment_athlete_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    received: list[tuple[UUID, UUID, StandardDistance, int, PerformanceLabel]] = []

    class FakePersonalBestService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def record(self, personal_best_input: PersonalBestInput) -> FakeResult:
            received.append(
                (
                    personal_best_input.athlete_id,
                    personal_best_input.activity_id,
                    personal_best_input.distance,
                    personal_best_input.elapsed_time_ms,
                    personal_best_input.label,
                )
            )
            return FakeResult(
                personal_best_id=ACTIVITY_ID,
                created=True,
                superseded_personal_best_id=None,
            )

    monkeypatch.setattr(
        record_personal_best,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(
        record_personal_best,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        record_personal_best,
        "PersonalBestService",
        FakePersonalBestService,
    )

    exit_code = record_personal_best.main(
        [
            "--activity-id",
            str(ACTIVITY_ID),
            "--distance",
            "5k",
            "--time",
            "19:41",
            "--label",
            "verified_max_effort",
        ]
    )

    assert exit_code == 0
    assert received == [
        (
            ATHLETE_ID,
            ACTIVITY_ID,
            StandardDistance.FIVE_K,
            1_181_000,
            PerformanceLabel.VERIFIED_MAX_EFFORT,
        )
    ]
    assert json.loads(capsys.readouterr().out)["created"] is True


def test_main_requires_an_athlete_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        record_personal_best,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        record_personal_best.main(
            [
                "--activity-id",
                str(ACTIVITY_ID),
                "--distance",
                "5k",
                "--time",
                "19:41",
                "--label",
                "verified_max_effort",
            ]
        )

    assert error.value.code == 2
