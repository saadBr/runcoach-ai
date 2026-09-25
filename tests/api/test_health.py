"""Tests for API health endpoints."""

from fastapi.testclient import TestClient


def test_liveness_returns_service_metadata(client: TestClient) -> None:
    """The liveness endpoint should not require a database connection."""

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "PaceCraft AI",
        "environment": "test",
    }
