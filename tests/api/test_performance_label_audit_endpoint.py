"""Tests for the private performance label-review API."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.analytics.performance_label_audit import (
    LabelAuditError,
    LabelReviewDecision,
    LabelReviewStatus,
    PerformanceLabelAudit,
    PerformanceLabelCandidate,
    evaluate_label_audit,
    review_token,
)
from runcoach.api.routes import analytics as analytics_routes
from runcoach.config import Settings, get_settings
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
FIRST_ID = UUID("018f0000-0000-7000-8000-000000000011")
SECOND_ID = UUID("018f0000-0000-7000-8000-000000000012")


def _candidate(
    activity_id: UUID,
    *,
    review_status: LabelReviewStatus,
) -> PerformanceLabelCandidate:
    verified = review_status is LabelReviewStatus.VERIFIED
    return PerformanceLabelCandidate(
        activity_id=activity_id,
        activity_name="Private activity title",
        achieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        matched_distance=StandardDistance.FIVE_K,
        measured_distance_m=5_001,
        recorded_elapsed_time_seconds=1_130,
        distance_deviation_pct=0.02,
        review_status=review_status,
        review_label=PerformanceLabel.VERIFIED_RACE if verified else None,
        verified_elapsed_time_seconds=1_128 if verified else None,
        review_notes=None,
    )


def _audit() -> PerformanceLabelAudit:
    return PerformanceLabelAudit(
        dataset_version="performance_training_features_v3",
        total_rows=2,
        verified_rows=1,
        excluded_rows=0,
        unreviewed_rows=1,
        candidates=(
            _candidate(FIRST_ID, review_status=LabelReviewStatus.VERIFIED),
            _candidate(SECOND_ID, review_status=LabelReviewStatus.UNREVIEWED),
        ),
    )


@pytest.fixture
def configured_client(client: TestClient, tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
        private_data_dir=tmp_path / "private",
    )
    yield client
    app.dependency_overrides.clear()


def test_get_label_audit_returns_filtered_private_queue(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _audit()
    monkeypatch.setattr(analytics_routes, "load_label_audit", lambda path: audit)
    monkeypatch.setattr(
        analytics_routes,
        "evaluate_label_audit",
        lambda received: evaluate_label_audit(received),
    )

    response = configured_client.get("/api/v1/analytics/performance/label-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 2
    assert body["verified_rows"] == 1
    assert body["unreviewed_rows"] == 1
    assert body["returned_rows"] == 1
    candidate = body["candidates"][0]
    assert candidate["review_token"] == review_token(
        dataset_version=audit.dataset_version,
        activity_id=SECOND_ID,
    )
    assert candidate["session_kind"] == "unclassified"
    assert "activity_id" not in candidate
    assert "activity_name" not in candidate
    assert body["validation"]["verified_labels"] == 1
    assert body["validation"]["candidate_model_eligible"] is False


def test_put_label_review_updates_and_revalidates(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = PerformanceLabelAudit(
        dataset_version="performance_training_features_v3",
        total_rows=2,
        verified_rows=2,
        excluded_rows=0,
        unreviewed_rows=0,
        candidates=(
            _candidate(FIRST_ID, review_status=LabelReviewStatus.VERIFIED),
            _candidate(SECOND_ID, review_status=LabelReviewStatus.VERIFIED),
        ),
    )
    received: list[tuple[UUID, LabelReviewDecision]] = []

    def fake_update(**kwargs: object) -> tuple[PerformanceLabelAudit, object]:
        activity_id = kwargs["activity_id"]
        decision = kwargs["decision"]
        assert isinstance(activity_id, UUID)
        assert isinstance(decision, LabelReviewDecision)
        received.append((activity_id, decision))
        return audit, evaluate_label_audit(audit)

    monkeypatch.setattr(analytics_routes, "update_and_validate", fake_update)
    monkeypatch.setattr(analytics_routes, "load_label_audit", lambda path: _audit())
    token = review_token(
        dataset_version=audit.dataset_version,
        activity_id=SECOND_ID,
    )

    response = configured_client.put(
        f"/api/v1/analytics/performance/label-audit/{token}",
        json={
            "review_status": "verified",
            "review_label": "verified_max_effort",
            "verified_elapsed_time_seconds": 1128,
            "review_notes": "Track result",
        },
    )

    assert response.status_code == 200
    assert received[0][0] == SECOND_ID
    assert received[0][1].review_label is PerformanceLabel.VERIFIED_MAX_EFFORT
    assert response.json()["verified_rows"] == 2
    assert response.json()["candidates"][0]["review_status"] == "verified"


def test_put_rejects_incomplete_verified_decision(
    configured_client: TestClient,
) -> None:
    token = review_token(
        dataset_version="performance_training_features_v3",
        activity_id=SECOND_ID,
    )
    response = configured_client.put(
        f"/api/v1/analytics/performance/label-audit/{token}",
        json={
            "review_status": "verified",
            "verified_elapsed_time_seconds": 1128,
        },
    )

    assert response.status_code == 422
    assert "requires a performance label" in response.json()["detail"]


def test_get_reports_missing_private_export_without_path_disclosure(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(path: Path) -> PerformanceLabelAudit:
        del path
        raise LabelAuditError(r"Could not read C:\private\performance-label-audit.csv")

    monkeypatch.setattr(analytics_routes, "load_label_audit", fail)

    response = configured_client.get("/api/v1/analytics/performance/label-audit")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "Export the private performance dataset first" in detail
    assert "C:\\" not in detail


def test_put_rejects_unknown_opaque_token_without_disclosing_identity(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analytics_routes, "load_label_audit", lambda path: _audit())

    response = configured_client.put(
        f"/api/v1/analytics/performance/label-audit/{'f' * 64}",
        json={"review_status": "excluded"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Performance label audit or candidate is unavailable."}
    assert str(FIRST_ID) not in response.text
    assert str(SECOND_ID) not in response.text


def test_label_audit_is_not_exposed_in_production(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="production",
        athlete_id=ATHLETE_ID,
    )
    try:
        response = client.get("/api/v1/analytics/performance/label-audit")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Performance label audit is unavailable."}
