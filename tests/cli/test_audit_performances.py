"""Tests for the read-only performance label-audit CLI."""

import argparse
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.analytics.performance import StandardDistance
from runcoach.cli import audit_performances

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@dataclass(frozen=True)
class FakeCandidate:
    """Serializable candidate returned by the fake query service."""

    activity_id: UUID
    achieved_at: datetime
    matched_distance: StandardDistance


@dataclass(frozen=True)
class FakeAudit:
    """Serializable audit returned by the fake query service."""

    audit_version: str
    distance_tolerance_pct: float
    eligible_activities: int
    candidates: tuple[FakeCandidate, ...]


def test_positive_tolerance_accepts_valid_value() -> None:
    assert audit_performances._positive_tolerance("2.5") == 2.5


@pytest.mark.parametrize("value", ("zero", "0", "10.1"))
def test_positive_tolerance_rejects_invalid_value(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        audit_performances._positive_tolerance(value)


def test_main_uses_environment_athlete_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    received: list[tuple[UUID, float]] = []

    class FakeAuditService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def audit(
            self,
            *,
            athlete_id: UUID,
            distance_tolerance_pct: float,
        ) -> FakeAudit:
            received.append((athlete_id, distance_tolerance_pct))
            return FakeAudit(
                audit_version="standard_distance_audit_v1",
                distance_tolerance_pct=distance_tolerance_pct,
                eligible_activities=130,
                candidates=(
                    FakeCandidate(
                        activity_id=ATHLETE_ID,
                        achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                        matched_distance=StandardDistance.FIVE_K,
                    ),
                ),
            )

    monkeypatch.setattr(
        audit_performances,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(
        audit_performances,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        audit_performances,
        "PerformanceAuditQueryService",
        FakeAuditService,
    )

    assert audit_performances.main(["--distance-tolerance-pct", "2.5"]) == 0

    assert received == [(ATHLETE_ID, 2.5)]
    output = json.loads(capsys.readouterr().out)
    assert output["eligible_activities"] == 130
    assert output["candidates"][0]["matched_distance"] == "5k"


def test_main_requires_an_athlete_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audit_performances,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        audit_performances.main([])

    assert error.value.code == 2
