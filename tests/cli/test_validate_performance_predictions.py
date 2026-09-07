"""Tests for the chronological performance-validation CLI."""

import csv
import json
from pathlib import Path

import pytest

from runcoach.cli import validate_performance_predictions


def _write_audit(path: Path, *, invalid_label: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "dataset_version",
        "activity_id",
        "achieved_at",
        "matched_distance",
        "review_status",
        "review_label",
        "verified_elapsed_time_seconds",
    )
    rows = (
        {
            "dataset_version": "performance_training_features_v3",
            "activity_id": "00000000-0000-0000-0000-000000000001",
            "achieved_at": "2026-01-01T08:00:00+00:00",
            "matched_distance": "10k",
            "review_status": "verified",
            "review_label": "not_a_label" if invalid_label else "verified_race",
            "verified_elapsed_time_seconds": "2400",
        },
        {
            "dataset_version": "performance_training_features_v3",
            "activity_id": "00000000-0000-0000-0000-000000000002",
            "achieved_at": "2026-02-01T08:00:00+00:00",
            "matched_distance": "5k",
            "review_status": "verified",
            "review_label": "verified_max_effort",
            "verified_elapsed_time_seconds": "1140",
        },
        {
            "dataset_version": "performance_training_features_v3",
            "activity_id": "00000000-0000-0000-0000-000000000003",
            "achieved_at": "2026-03-01T08:00:00+00:00",
            "matched_distance": "5k",
            "review_status": "verified",
            "review_label": "verified_race",
            "verified_elapsed_time_seconds": "1110",
        },
        {
            "dataset_version": "performance_training_features_v3",
            "activity_id": "00000000-0000-0000-0000-000000000004",
            "achieved_at": "2026-04-01T08:00:00+00:00",
            "matched_distance": "half_marathon",
            "review_status": "unreviewed",
            "review_label": "",
            "verified_elapsed_time_seconds": "",
        },
    )
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_private_path_rejects_public_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="private data"):
        validate_performance_predictions._private_path(
            tmp_path / "public.json",
            tmp_path / "data" / "private",
        )


def test_read_observations_excludes_unreviewed_rows(tmp_path: Path) -> None:
    audit = tmp_path / "audit.csv"
    _write_audit(audit)

    version, observations = validate_performance_predictions._read_observations(audit)

    assert version == "performance_training_features_v3"
    assert len(observations) == 3
    assert all(item.performance.elapsed_time_seconds > 0 for item in observations)


def test_read_observations_rejects_invalid_verified_row(tmp_path: Path) -> None:
    audit = tmp_path / "audit.csv"
    _write_audit(audit, invalid_label=True)

    with pytest.raises(ValueError, match="Invalid verified"):
        validate_performance_predictions._read_observations(audit)


def test_read_observations_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Could not read"):
        validate_performance_predictions._read_observations(tmp_path / "missing.csv")


def test_main_writes_private_report_and_prints_aggregate_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root = tmp_path / "data" / "private"
    audit = private_root / "ml" / "audit.csv"
    output = private_root / "ml" / "validation.json"
    _write_audit(audit)
    monkeypatch.setattr(
        validate_performance_predictions,
        "get_settings",
        lambda: type("Settings", (), {"private_data_dir": private_root})(),
    )

    result = validate_performance_predictions.main(["--input", str(audit), "--output", str(output)])

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "descriptive_only"
    assert summary["verified_labels"] == 3
    assert not summary["candidate_model_eligible"]
    assert len(summary["aggregate_metrics"]) == 3
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["dataset_version"] == "performance_training_features_v3"
    assert len(artifact["report"]["predictions"]) == 4


def test_main_rejects_input_outside_private_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = tmp_path / "private"
    public_input = tmp_path / "audit.csv"
    _write_audit(public_input)
    monkeypatch.setattr(
        validate_performance_predictions,
        "get_settings",
        lambda: type("Settings", (), {"private_data_dir": private_root})(),
    )

    with pytest.raises(SystemExit) as error:
        validate_performance_predictions.main(["--input", str(public_input)])

    assert error.value.code == 2
