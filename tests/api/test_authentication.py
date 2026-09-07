"""Tests for account login and revocable bearer-session endpoints."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import authentication as authentication_routes
from runcoach.db.identity import (
    AuthenticatedAthlete,
    AuthenticationRejectedError,
    IdentityError,
    IssuedAuthSession,
)
from runcoach.db.session import get_db_session
from runcoach.main import app

SESSION_ID = UUID("018f0000-0000-7000-8000-000000000001")
ACCOUNT_ID = UUID("018f0000-0000-7000-8000-000000000002")
ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000003")
EXPIRES_AT = datetime(2026, 10, 7, 12, tzinfo=UTC)
ACCESS_TOKEN = "opaque-test-token-that-is-never-persisted"


def _identity() -> AuthenticatedAthlete:
    return AuthenticatedAthlete(
        session_id=SESSION_ID,
        account_id=ACCOUNT_ID,
        athlete_id=ATHLETE_ID,
        display_name="Synthetic Athlete",
        timezone="Africa/Casablanca",
        onboarding_status="ready",
        expires_at=EXPIRES_AT,
    )


@pytest.fixture
def authentication_client(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides.pop(authentication_routes.authenticated_athlete, None)
    app.dependency_overrides[get_db_session] = lambda: object()
    yield client
    app.dependency_overrides.clear()


def test_login_returns_token_and_display_context_without_credentials(
    authentication_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str]] = []

    class FakeAuthenticationService:
        def __init__(self, session: object) -> None:
            assert session is not None

        def login(self, *, email: str, password: str) -> IssuedAuthSession:
            captured.append((email, password))
            return IssuedAuthSession(access_token=ACCESS_TOKEN, identity=_identity())

    monkeypatch.setattr(
        authentication_routes,
        "AuthenticationService",
        FakeAuthenticationService,
    )

    response = authentication_client.post(
        "/api/v1/auth/login",
        json={"email": "athlete@example.com", "password": "private test password"},
    )

    assert response.status_code == 200
    assert captured == [("athlete@example.com", "private test password")]
    assert response.json() == {
        "access_token": ACCESS_TOKEN,
        "token_type": "bearer",
        "expires_at": EXPIRES_AT.isoformat().replace("+00:00", "Z"),
        "athlete": {
            "display_name": "Synthetic Athlete",
            "timezone": "Africa/Casablanca",
            "onboarding_status": "ready",
        },
    }
    assert "private test password" not in response.text
    assert "athlete@example.com" not in response.text


def test_login_rejects_invalid_credentials_with_one_generic_message(
    authentication_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingAuthenticationService:
        def __init__(self, session: object) -> None:
            del session

        def login(self, *, email: str, password: str) -> IssuedAuthSession:
            del email, password
            raise AuthenticationRejectedError("Internal rejection detail.")

    monkeypatch.setattr(
        authentication_routes,
        "AuthenticationService",
        RejectingAuthenticationService,
    )

    response = authentication_client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "private test password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "Internal rejection detail" not in response.text


def test_current_account_requires_and_resolves_bearer_session(
    authentication_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_tokens: list[str] = []

    class FakeAuthenticationService:
        def __init__(self, session: object) -> None:
            del session

        def authenticate(self, access_token: str) -> AuthenticatedAthlete:
            received_tokens.append(access_token)
            return _identity()

    monkeypatch.setattr(
        authentication_routes,
        "AuthenticationService",
        FakeAuthenticationService,
    )

    missing = authentication_client.get("/api/v1/auth/me")
    response = authentication_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )

    assert missing.status_code == 401
    assert response.status_code == 200
    assert received_tokens == [ACCESS_TOKEN]
    assert response.json()["athlete"]["display_name"] == "Synthetic Athlete"
    assert response.json()["session_expires_at"] == EXPIRES_AT.isoformat().replace("+00:00", "Z")


def test_private_analytics_rejects_a_missing_bearer_session(
    authentication_client: TestClient,
) -> None:
    response = authentication_client.get("/api/v1/analytics/overview")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication is required."}
    assert response.headers["www-authenticate"] == "Bearer"


def test_logout_revokes_the_current_session(
    authentication_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revoked_tokens: list[str] = []

    class FakeAuthenticationService:
        def __init__(self, session: object) -> None:
            del session

        def authenticate(self, access_token: str) -> AuthenticatedAthlete:
            assert access_token == ACCESS_TOKEN
            return _identity()

        def logout(self, access_token: str) -> None:
            revoked_tokens.append(access_token)

    monkeypatch.setattr(
        authentication_routes,
        "AuthenticationService",
        FakeAuthenticationService,
    )

    response = authentication_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert revoked_tokens == [ACCESS_TOKEN]


def test_authentication_storage_failure_is_sanitized(
    authentication_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAuthenticationService:
        def __init__(self, session: object) -> None:
            del session

        def login(self, *, email: str, password: str) -> IssuedAuthSession:
            del email, password
            raise IdentityError("private database detail")

    monkeypatch.setattr(
        authentication_routes,
        "AuthenticationService",
        FailingAuthenticationService,
    )

    response = authentication_client.post(
        "/api/v1/auth/login",
        json={"email": "athlete@example.com", "password": "private test password"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service is unavailable."}
    assert "private database detail" not in response.text
