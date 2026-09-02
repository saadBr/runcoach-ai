"""Tests for the standard-distance evidence CLI."""

import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.analytics.performance import StandardDistance
from runcoach.cli import inspect_performance_effort

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000010")


@dataclass(frozen=True)
class FakeEvidence:
    """Serializable result returned by the fake query service."""

    activity_id: UUID
    achieved_at: datetime
    target_distance: StandardDistance
    elapsed_time_seconds: float


def test_main_reads_environment_athlete_and_prints_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_session = object()
    received: list[tuple[UUID, UUID, StandardDistance]] = []

    class FakeAuditService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def evidence(
            self,
            *,
            athlete_id: UUID,
            activity_id: UUID,
            target_distance: StandardDistance,
        ) -> FakeEvidence:
            received.append((athlete_id, activity_id, target_distance))
            return FakeEvidence(
                activity_id=activity_id,
                achieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                target_distance=target_distance,
                elapsed_time_seconds=1_200,
            )

    monkeypatch.setattr(
        inspect_performance_effort,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=ATHLETE_ID),
    )
    monkeypatch.setattr(
        inspect_performance_effort,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        inspect_performance_effort,
        "PerformanceAuditQueryService",
        FakeAuditService,
    )

    exit_code = inspect_performance_effort.main(
        [
            "--activity-id",
            str(ACTIVITY_ID),
            "--distance",
            "5k",
        ]
    )

    assert exit_code == 0
    assert received == [(ATHLETE_ID, ACTIVITY_ID, StandardDistance.FIVE_K)]
    output = json.loads(capsys.readouterr().out)
    assert output["activity_id"] == str(ACTIVITY_ID)
    assert output["target_distance"] == "5k"


def test_main_requires_an_athlete_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inspect_performance_effort,
        "get_settings",
        lambda: SimpleNamespace(athlete_id=None),
    )

    with pytest.raises(SystemExit) as error:
        inspect_performance_effort.main(
            [
                "--activity-id",
                str(ACTIVITY_ID),
                "--distance",
                "5k",
            ]
        )

    assert error.value.code == 2
