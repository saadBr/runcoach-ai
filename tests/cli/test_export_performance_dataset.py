"""Tests for the private performance feature-export CLI."""

import argparse
import csv
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from runcoach.analytics.performance import StandardDistance
from runcoach.cli import export_performance_dataset
from runcoach.db.performance_audit import (
    PerformanceTrainingDataset,
    PerformanceTrainingRow,
    TrainingWindowFeatures,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _dataset() -> PerformanceTrainingDataset:
    windows = tuple(
        TrainingWindowFeatures(
            days=days,
            runs=3,
            distance_km=30.0,
            moving_hours=3.0,
            longest_run_km=12.0,
            weighted_pace_seconds_per_km=360.0,
            elevation_gain_m=250.0,
            activities_with_heart_rate=2,
            duration_load_minutes=180.0,
            classified_sessions=3,
            quality_sessions=1,
            easy_sessions=2,
            long_sessions=1,
            progressive_sessions=0,
            tempo_sessions=1,
            hill_sessions=0,
            interval_sessions=0,
            race_sessions=0,
            unclassified_sessions=0,
        )
        for days in (7, 28, 42, 84, 180, 365)
    )
    row = PerformanceTrainingRow(
        activity_id=ATHLETE_ID,
        activity_name="Private Race Name",
        achieved_at=datetime(2026, 5, 15, tzinfo=UTC),
        matched_distance=StandardDistance.FIVE_K,
        measured_distance_m=5_010.0,
        recorded_elapsed_time_seconds=1_182.0,
        distance_deviation_pct=0.2,
        review_status="verified",
        review_label="verified_max_effort",
        verified_elapsed_time_seconds=1_181.0,
        review_notes=None,
        prior_history_runs=20,
        prior_history_days=120,
        prior_acute_load=42.0,
        prior_chronic_load=38.0,
        prior_form_index=-4.0,
        prior_5k_best_seconds=None,
        prior_10k_best_seconds=2_464.0,
        prior_half_marathon_best_seconds=None,
        prior_marathon_best_seconds=None,
        training_windows=windows,
    )
    return PerformanceTrainingDataset(
        dataset_version="performance_training_features_v3",
        audit_version="standard_distance_audit_v1",
        leakage_rule="Only earlier evidence is used.",
        candidate_rows=1,
        verified_rows=1,
        unreviewed_rows=0,
        model_status="evaluation_required",
        rows=(row,),
    )


def test_positive_tolerance_rejects_invalid_value() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        export_performance_dataset._positive_tolerance("0")


def test_private_output_path_rejects_public_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="private data directory"):
        export_performance_dataset._private_output_path(
            tmp_path / "public.csv",
            tmp_path / "data" / "private",
        )


def test_write_dataset_flattens_all_training_windows(tmp_path: Path) -> None:
    output = tmp_path / "data" / "private" / "audit.csv"

    export_performance_dataset._write_dataset(output, _dataset())

    with output.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert len(rows) == 1
    assert rows[0]["activity_name"] == "Private Race Name"
    assert rows[0]["review_label"] == "verified_max_effort"
    assert rows[0]["prior_7d_runs"] == "3"
    assert rows[0]["prior_84d_duration_load_minutes"] == "180.0"
    assert rows[0]["prior_365d_quality_sessions"] == "1"


def test_main_exports_under_configured_private_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "data" / "private"
    output = private_root / "ml" / "labels.csv"
    fake_session = object()
    received: list[tuple[UUID, float]] = []

    class FakeService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def training_dataset(
            self,
            *,
            athlete_id: UUID,
            distance_tolerance_pct: float,
        ) -> PerformanceTrainingDataset:
            received.append((athlete_id, distance_tolerance_pct))
            return _dataset()

    monkeypatch.setattr(
        export_performance_dataset,
        "get_settings",
        lambda: SimpleNamespace(
            athlete_id=ATHLETE_ID,
            private_data_dir=private_root,
        ),
    )
    monkeypatch.setattr(
        export_performance_dataset,
        "SessionFactory",
        lambda: nullcontext(fake_session),
    )
    monkeypatch.setattr(
        export_performance_dataset,
        "PerformanceAuditQueryService",
        FakeService,
    )

    result = export_performance_dataset.main(
        ["--output", str(output), "--distance-tolerance-pct", "2.5"]
    )

    assert result == 0
    assert received == [(ATHLETE_ID, 2.5)]
    assert output.exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary["candidate_rows"] == 1
    assert summary["verified_rows"] == 1
    assert summary["model_status"] == "evaluation_required"


def test_main_requires_athlete_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        export_performance_dataset,
        "get_settings",
        lambda: SimpleNamespace(
            athlete_id=None,
            private_data_dir=tmp_path / "data" / "private",
        ),
    )

    with pytest.raises(SystemExit) as error:
        export_performance_dataset.main([])

    assert error.value.code == 2
