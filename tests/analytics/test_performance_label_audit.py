"""Tests for private performance label-review persistence."""

import csv
import json
from pathlib import Path
from uuid import UUID

import pytest

from runcoach.analytics.performance import PerformanceLabel
from runcoach.analytics.performance_label_audit import (
    LabelAuditError,
    LabelReviewDecision,
    LabelReviewStatus,
    candidate_for_review_token,
    evaluate_label_audit,
    label_audit_path,
    load_label_audit,
    review_token,
    update_and_validate,
    update_label_review,
    validation_artifact_path,
)

FIRST_ID = UUID("018f0000-0000-7000-8000-000000000001")
SECOND_ID = UUID("018f0000-0000-7000-8000-000000000002")
FIELDNAMES = (
    "dataset_version",
    "activity_id",
    "activity_name",
    "achieved_at",
    "matched_distance",
    "measured_distance_m",
    "recorded_elapsed_time_seconds",
    "distance_deviation_pct",
    "review_status",
    "review_label",
    "verified_elapsed_time_seconds",
    "review_notes",
    "prior_28d_distance_km",
)


def _write_audit(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            (
                {
                    "dataset_version": "performance_training_features_v3",
                    "activity_id": str(FIRST_ID),
                    "activity_name": "Spring 5K",
                    "achieved_at": "2026-03-01T08:00:00+00:00",
                    "matched_distance": "5k",
                    "measured_distance_m": "5001",
                    "recorded_elapsed_time_seconds": "1200",
                    "distance_deviation_pct": "0.02",
                    "review_status": "verified",
                    "review_label": "verified_race",
                    "verified_elapsed_time_seconds": "1198",
                    "review_notes": "Official result",
                    "prior_28d_distance_km": "250",
                },
                {
                    "dataset_version": "performance_training_features_v3",
                    "activity_id": str(SECOND_ID),
                    "activity_name": "Autumn 5K",
                    "achieved_at": "2026-09-01T08:00:00+00:00",
                    "matched_distance": "5k",
                    "measured_distance_m": "5000",
                    "recorded_elapsed_time_seconds": "1130",
                    "distance_deviation_pct": "0",
                    "review_status": "unreviewed",
                    "review_label": "",
                    "verified_elapsed_time_seconds": "",
                    "review_notes": "",
                    "prior_28d_distance_km": "300",
                },
            )
        )


def test_load_label_audit_returns_minimized_candidates(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    _write_audit(path)

    audit = load_label_audit(path)

    assert audit.dataset_version == "performance_training_features_v3"
    assert audit.total_rows == 2
    assert audit.verified_rows == 1
    assert audit.excluded_rows == 0
    assert audit.unreviewed_rows == 1
    assert audit.candidates[1].activity_name == "Autumn 5K"
    assert audit.candidates[1].matched_distance.value == "5k"

    token = review_token(dataset_version=audit.dataset_version, activity_id=SECOND_ID)
    assert len(token) == 64
    assert str(SECOND_ID) not in token
    assert candidate_for_review_token(audit, token).activity_id == SECOND_ID


def test_update_label_review_is_atomic_and_preserves_features(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    _write_audit(path)

    audit = update_label_review(
        path,
        activity_id=SECOND_ID,
        decision=LabelReviewDecision(
            review_status=LabelReviewStatus.VERIFIED,
            review_label=PerformanceLabel.VERIFIED_MAX_EFFORT,
            verified_elapsed_time_seconds=1_128.0,
            review_notes="  Track time  ",
        ),
    )

    assert audit.verified_rows == 2
    assert audit.unreviewed_rows == 0
    assert audit.candidates[1].verified_elapsed_time_seconds == 1_128.0
    assert audit.candidates[1].review_notes == "Track time"
    with path.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert rows[1]["prior_28d_distance_km"] == "300"


def test_excluded_review_clears_performance_fields(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    _write_audit(path)

    audit = update_label_review(
        path,
        activity_id=FIRST_ID,
        decision=LabelReviewDecision(
            review_status=LabelReviewStatus.EXCLUDED,
            review_notes="Training run",
        ),
    )

    candidate = audit.candidates[0]
    assert candidate.review_status is LabelReviewStatus.EXCLUDED
    assert candidate.review_label is None
    assert candidate.verified_elapsed_time_seconds is None
    assert candidate.review_notes == "Training run"


def test_update_and_validate_writes_private_artifact(tmp_path: Path) -> None:
    private_root = tmp_path / "private"
    _write_audit(label_audit_path(private_root))

    audit, report = update_and_validate(
        private_data_dir=private_root,
        activity_id=SECOND_ID,
        decision=LabelReviewDecision(
            review_status=LabelReviewStatus.VERIFIED,
            review_label=PerformanceLabel.VERIFIED_MAX_EFFORT,
            verified_elapsed_time_seconds=1_128,
        ),
    )

    assert audit.verified_rows == 2
    assert report.verified_labels == 2
    artifact = json.loads(validation_artifact_path(private_root).read_text(encoding="utf-8"))
    assert artifact["dataset_version"] == "performance_training_features_v3"
    assert artifact["report"]["verified_labels"] == 2


def test_decision_rejects_inconsistent_fields() -> None:
    with pytest.raises(ValueError, match="requires a performance label"):
        LabelReviewDecision(
            review_status=LabelReviewStatus.VERIFIED,
            verified_elapsed_time_seconds=1_200,
        )
    with pytest.raises(ValueError, match="Only verified"):
        LabelReviewDecision(
            review_status=LabelReviewStatus.EXCLUDED,
            review_label=PerformanceLabel.VERIFIED_RACE,
        )


def test_loader_rejects_missing_columns_and_unknown_activity(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.csv"
    invalid_path.write_text("activity_id\nvalue\n", encoding="utf-8")
    with pytest.raises(LabelAuditError, match="missing required columns"):
        load_label_audit(invalid_path)

    path = tmp_path / "audit.csv"
    _write_audit(path)
    with pytest.raises(LabelAuditError, match="not found exactly once"):
        update_label_review(
            path,
            activity_id=UUID("018f0000-0000-7000-8000-000000000099"),
            decision=LabelReviewDecision(review_status=LabelReviewStatus.EXCLUDED),
        )


def test_evaluate_label_audit_uses_only_verified_rows(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    _write_audit(path)

    report = evaluate_label_audit(load_label_audit(path))

    assert report.verified_labels == 1
    assert report.chronological_targets == 0
