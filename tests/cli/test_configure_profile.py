"""Tests for the physiology-profile configuration CLI."""

import argparse
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.cli import configure_profile
from runcoach.db.physiology import PhysiologyProfileInput

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
PROFILE_ID = UUID("018f0000-0000-7000-8000-000000000002")


@dataclass(frozen=True)
class FakeProfileResult:
    """Serializable result returned by the fake profile service."""

    profile_id: UUID
    created: bool


def test_iso_date_accepts_valid_date() -> None:
    assert configure_profile._iso_date("2026-04-01") == date(2026, 4, 1)


def test_iso_date_rejects_invalid_date() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        configure_profile._iso_date("01-04-2026")


def test_main_configures_profile_from_environment_athlete_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    captured: list[PhysiologyProfileInput] = []

    class FakeProfileService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def configure(
            self,
            profile_input: PhysiologyProfileInput,
        ) -> FakeProfileResult:
            captured.append(profile_input)
            return FakeProfileResult(
                profile_id=PROFILE_ID,
                created=True,
            )

    monkeypatch.setattr(
        configure_profile,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(
        configure_profile,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        configure_profile,
        "PhysiologyProfileService",
        FakeProfileService,
    )

    exit_code = configure_profile.main(
        [
            "--valid-from",
            "2026-04-01",
            "--valid-to",
            "2027-01-01",
            "--observed-max-hr",
            "190",
            "--resting-hr",
            "50",
            "--lactate-threshold-hr",
            "170",
            "--threshold-pace-seconds-per-km",
            "240",
            "--notes",
            "Synthetic CLI test profile.",
        ]
    )

    assert exit_code == 0
    assert len(captured) == 1

    profile_input = captured[0]
    assert profile_input.athlete_id == ATHLETE_ID
    assert profile_input.valid_from == date(2026, 4, 1)
    assert profile_input.valid_to == date(2027, 1, 1)
    assert profile_input.observed_max_hr_bpm == 190
    assert profile_input.resting_hr_bpm == 50
    assert profile_input.lactate_threshold_hr_bpm == 170
    assert profile_input.threshold_pace_seconds_per_km == 240
    assert profile_input.notes == "Synthetic CLI test profile."

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "created": True,
        "profile_id": str(PROFILE_ID),
    }


def test_main_requires_an_athlete_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        configure_profile,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        configure_profile.main(
            [
                "--valid-from",
                "2026-04-01",
            ]
        )

    assert error.value.code == 2
