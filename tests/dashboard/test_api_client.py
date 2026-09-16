"""Tests for the dashboard HTTP client."""

import json
from datetime import date
from email.message import Message
from io import BytesIO
from types import TracebackType
from typing import Never, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from runcoach.dashboard import api_client
from runcoach.dashboard.api_client import (
    DashboardApiError,
    DashboardAuthenticationError,
    DashboardNotFoundError,
    RunCoachApiClient,
)


class FakeResponse:
    """Minimal context-managed HTTP response used by client tests."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback

    def read(self) -> bytes:
        return self._body


def test_authentication_calls_use_credentials_and_bearer_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, str | None, bytes | None]] = []
    responses = iter(
        (
            b'{"access_token":"opaque-token","token_type":"bearer"}',
            b'{"athlete":{"display_name":"Synthetic Athlete"}}',
            b"",
        )
    )

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured.append(
            (
                request.full_url,
                request.get_method(),
                request.get_header("Authorization"),
                cast(bytes | None, request.data),
            )
        )
        return FakeResponse(next(responses))

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)
    anonymous = RunCoachApiClient("http://localhost:8000")
    login = anonymous.login(email="athlete@example.com", password="private test password")
    authenticated = RunCoachApiClient(
        "http://localhost:8000",
        access_token="opaque-token",
    )
    current = authenticated.get_current_account()
    authenticated.logout()

    assert login["token_type"] == "bearer"
    assert current["athlete"] == {"display_name": "Synthetic Athlete"}
    assert captured[0][:3] == (
        "http://localhost:8000/api/v1/auth/login",
        "POST",
        None,
    )
    assert json.loads((captured[0][3] or b"").decode()) == {
        "email": "athlete@example.com",
        "password": "private test password",
    }
    assert captured[1][:3] == (
        "http://localhost:8000/api/v1/auth/me",
        "GET",
        "Bearer opaque-token",
    )
    assert captured[2][:3] == (
        "http://localhost:8000/api/v1/auth/logout",
        "POST",
        "Bearer opaque-token",
    )


def test_logout_requires_a_nonempty_access_token() -> None:
    with pytest.raises(ValueError, match="Logout requires"):
        RunCoachApiClient("http://localhost:8000").logout()
    with pytest.raises(ValueError, match="cannot be empty"):
        RunCoachApiClient("http://localhost:8000", access_token=" ")


def test_registration_and_required_archive_use_separate_safe_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, str | None, bytes | None, float]] = []
    responses = iter((b'{"access_token":"pending-token"}', b'{"status":"ready"}'))

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured.append(
            (
                request.full_url,
                request.get_method(),
                request.get_header("Authorization"),
                cast(bytes | None, request.data),
                timeout,
            )
        )
        return FakeResponse(next(responses))

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)
    registration = {"email": "new@example.com", "password": "private password"}
    anonymous = RunCoachApiClient("http://localhost:8000")
    registered = anonymous.register(registration)
    pending = RunCoachApiClient(
        "http://localhost:8000",
        timeout_seconds=5,
        access_token="pending-token",
    )
    completed = pending.upload_strava_archive(
        filename="export.zip",
        content=b"private zip bytes",
    )

    assert registered["access_token"] == "pending-token"
    assert completed["status"] == "ready"
    assert captured[0][:3] == (
        "http://localhost:8000/api/v1/auth/register",
        "POST",
        None,
    )
    assert json.loads((captured[0][3] or b"").decode()) == registration
    assert captured[1][:3] == (
        "http://localhost:8000/api/v1/onboarding/strava-archive",
        "POST",
        "Bearer pending-token",
    )
    assert captured[1][3] == b"private zip bytes"
    assert captured[1][4] == 300


def test_overview_uses_normalized_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[tuple[str, float]] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured_requests.append((request.full_url, timeout))
        return FakeResponse(b'{"total_runs": 130}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    client = RunCoachApiClient("http://localhost:8000/", timeout_seconds=3.5)

    result = client.get_overview()

    assert result["total_runs"] == 130
    assert captured_requests == [("http://localhost:8000/api/v1/analytics/overview", 3.5)]


def test_performance_uses_read_only_analytics_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_urls: list[str] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured_urls.append(request.full_url)
        return FakeResponse(b'{"personal_bests": [], "prediction_status": "audit"}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    result = RunCoachApiClient("http://localhost:8000").get_performance()

    assert result["personal_bests"] == []
    assert captured_urls == ["http://localhost:8000/api/v1/analytics/performance"]


def test_label_audit_client_reads_and_updates_private_review_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, bytes | None]] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured.append((request.full_url, request.get_method(), cast(bytes | None, request.data)))
        return FakeResponse(b'{"verified_rows":6}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)
    client = RunCoachApiClient("http://localhost:8000")
    review_token = "a" * 64

    queue = client.get_performance_label_audit(limit=1)
    updated = client.review_performance_candidate(
        review_token=review_token,
        review_status="verified",
        review_label="verified_race",
        verified_elapsed_time_seconds=1_128,
        review_notes="Official result",
    )

    assert queue["verified_rows"] == 6
    assert updated["verified_rows"] == 6
    assert captured[0] == (
        "http://localhost:8000/api/v1/analytics/performance/label-audit?"
        "offset=0&limit=1&review_status=unreviewed",
        "GET",
        None,
    )
    assert captured[1][:2] == (
        f"http://localhost:8000/api/v1/analytics/performance/label-audit/{review_token}",
        "PUT",
    )
    assert json.loads((captured[1][2] or b"").decode()) == {
        "review_status": "verified",
        "review_label": "verified_race",
        "verified_elapsed_time_seconds": 1_128,
        "review_notes": "Official result",
    }


def test_label_audit_client_rejects_invalid_pagination() -> None:
    client = RunCoachApiClient("http://localhost:8000")

    with pytest.raises(ValueError, match="offset"):
        client.get_performance_label_audit(offset=-1)
    with pytest.raises(ValueError, match="limit"):
        client.get_performance_label_audit(limit=101)

    with pytest.raises(ValueError, match="review token"):
        client.review_performance_candidate(
            review_token="not-a-token",
            review_status="excluded",
        )


def test_training_plan_encodes_goal_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_urls: list[str] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured_urls.append(request.full_url)
        return FakeResponse(b'{"algorithm_version": "goal_plan_preview_v1"}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    result = RunCoachApiClient("http://localhost:8000").get_training_plan(
        distance="marathon",
        race_date=date(2026, 11, 29),
        target_time_seconds=11_400,
        days_per_week=6,
    )

    assert result["algorithm_version"] == "goal_plan_preview_v1"
    assert captured_urls == [
        "http://localhost:8000/api/v1/coaching/plan-preview?"
        "distance=marathon&race_date=2026-11-29&days_per_week=6&"
        "target_time_seconds=11400"
    ]


def test_training_plan_mutations_use_versioned_coaching_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[tuple[str, str]] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured_requests.append((request.full_url, request.get_method()))
        return FakeResponse(b'{"version": 1}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)
    client = RunCoachApiClient("http://localhost:8000")

    saved = client.save_training_plan(
        distance="marathon",
        race_date=date(2027, 1, 31),
        target_time_seconds=11_400,
        days_per_week=6,
    )
    active = client.get_active_training_plan()
    refreshed = client.refresh_active_training_plan()
    tracking = client.get_active_training_plan_tracking(as_of_date=date(2026, 9, 13))

    assert saved["version"] == 1
    assert active["version"] == 1
    assert refreshed["version"] == 1
    assert tracking["version"] == 1
    assert captured_requests == [
        (
            "http://localhost:8000/api/v1/coaching/plans/active?"
            "distance=marathon&race_date=2027-01-31&days_per_week=6&"
            "target_time_seconds=11400",
            "POST",
        ),
        ("http://localhost:8000/api/v1/coaching/plans/active", "GET"),
        ("http://localhost:8000/api/v1/coaching/plans/active/refresh", "POST"),
        (
            "http://localhost:8000/api/v1/coaching/plans/active/tracking?as_of_date=2026-09-13",
            "GET",
        ),
    ]


def test_run_upload_sends_private_metadata_headers_and_extended_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, bytes | None, str | None, str | None, str | None, float]] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured.append(
            (
                request.full_url,
                request.get_method(),
                cast(bytes | None, request.data),
                request.get_header("Content-type"),
                request.get_header("X-runcoach-filename"),
                request.get_header("X-runcoach-title"),
                timeout,
            )
        )
        return FakeResponse(b'{"status": "updated"}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    result = RunCoachApiClient(
        "http://localhost:8000",
        timeout_seconds=4.0,
    ).upload_run(
        filename="Tempo Run.fit",
        title="3K WU + tempo",
        content=b"FITDATA",
    )

    assert result["status"] == "updated"
    assert captured == [
        (
            "http://localhost:8000/api/v1/coaching/runs",
            "POST",
            b"FITDATA",
            "application/octet-stream",
            "Tempo%20Run.fit",
            "3K%20WU%20%2B%20tempo",
            60.0,
        )
    ]


def test_chat_posts_bounded_json_without_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, bytes | None, str | None, float]] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured.append(
            (
                request.full_url,
                request.get_method(),
                cast(bytes | None, request.data),
                request.get_header("Content-type"),
                timeout,
            )
        )
        return FakeResponse(b'{"answer":"Use the plan."}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    result = RunCoachApiClient("http://localhost:8000", timeout_seconds=2).ask_coach(
        message=" What should I run tomorrow? ",
        conversation=[{"role": "assistant", "content": "Ask me about your plan."}],
    )

    assert result["answer"] == "Use the plan."
    assert captured[0][:2] == ("http://localhost:8000/api/v1/coaching/chat", "POST")
    assert captured[0][3:] == ("application/json", 30.0)
    assert json.loads((captured[0][2] or b"").decode()) == {
        "message": "What should I run tomorrow?",
        "conversation": [{"role": "assistant", "content": "Ask me about your plan."}],
    }


@pytest.mark.parametrize(
    ("filename", "title", "content", "message"),
    (
        ("", "Easy run", b"FIT", "filename"),
        ("run.fit", "", b"FIT", "title"),
        ("run.fit", "Easy run", b"", "empty"),
    ),
)
def test_run_upload_rejects_missing_client_input(
    filename: str,
    title: str,
    content: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RunCoachApiClient("http://localhost:8000").upload_run(
            filename=filename,
            title=title,
            content=content,
        )


def test_chat_client_rejects_invalid_input() -> None:
    client = RunCoachApiClient("http://localhost:8000")

    with pytest.raises(ValueError, match="blank"):
        client.ask_coach(message=" ")
    with pytest.raises(ValueError, match="at most eight"):
        client.ask_coach(
            message="Question",
            conversation=[{"role": "user", "content": "prior"}] * 9,
        )


@pytest.mark.parametrize(
    ("target_time_seconds", "days_per_week", "message"),
    ((0.0, 5, "greater than zero"), (None, 2, "between three and seven")),
)
def test_training_plan_rejects_invalid_controls(
    target_time_seconds: float | None,
    days_per_week: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RunCoachApiClient("http://localhost:8000").get_training_plan(
            distance="5k",
            race_date=date(2026, 11, 29),
            target_time_seconds=target_time_seconds,
            days_per_week=days_per_week,
        )


def test_trends_encodes_weeks_and_end_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_urls: list[str] = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        captured_urls.append(request.full_url)
        return FakeResponse(b'{"weekly_training": [], "daily_workload": []}')

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    client = RunCoachApiClient("http://localhost:8000")

    client.get_trends(weeks=8, end_date=date(2026, 8, 27))

    assert captured_urls == [
        "http://localhost:8000/api/v1/analytics/trends?weeks=8&end_date=2026-08-27"
    ]


@pytest.mark.parametrize("weeks", [0, 53])
def test_trends_rejects_invalid_week_count(weeks: int) -> None:
    client = RunCoachApiClient("http://localhost:8000")

    with pytest.raises(ValueError, match="between 1 and 52"):
        client.get_trends(weeks=weeks)


@pytest.mark.parametrize(
    ("base_url", "timeout_seconds", "message"),
    [
        ("localhost:8000", 5.0, "absolute HTTP or HTTPS"),
        ("http://localhost:8000", 0.0, "greater than zero"),
    ],
)
def test_client_rejects_invalid_configuration(
    base_url: str,
    timeout_seconds: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RunCoachApiClient(base_url, timeout_seconds=timeout_seconds)


def test_client_rejects_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del request, timeout
        return FakeResponse(b"[]")

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardApiError, match="unexpected response structure"):
        RunCoachApiClient("http://localhost:8000").get_overview()


def test_client_translates_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del timeout
        raise HTTPError(
            request.full_url,
            503,
            "Service unavailable",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardApiError, match="HTTP 503"):
        RunCoachApiClient("http://localhost:8000").get_overview()


def test_client_distinguishes_rejected_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del timeout
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=Message(),
            fp=BytesIO(b'{"detail":"Authentication is required."}'),
        )

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardAuthenticationError, match="Authentication is required"):
        RunCoachApiClient(
            "http://localhost:8000",
            access_token="opaque-session-token-with-sufficient-length",
        ).get_current_account()


def test_client_distinguishes_missing_optional_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del timeout
        raise HTTPError(
            request.full_url,
            404,
            "Not found",
            hdrs=Message(),
            fp=BytesIO(b'{"detail":"No active persisted training plan exists."}'),
        )

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardNotFoundError, match="No active persisted training plan"):
        RunCoachApiClient(
            "http://localhost:8000",
            access_token="opaque-session-token-with-sufficient-length",
        ).get_active_training_plan()


@pytest.mark.parametrize(
    ("body", "expected_message"),
    (
        (b'{"detail":"Upload the original Strava export as a ZIP file."}', "original"),
        (
            b'{"detail":{"code":"ARCHIVE_EXPANSION_TOO_LARGE",'
            b'"message":"The expanded Strava archive is too large."}}',
            "expanded Strava archive.*ARCHIVE_EXPANSION_TOO_LARGE",
        ),
    ),
)
def test_client_surfaces_sanitized_api_error_detail(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    expected_message: str,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del timeout
        raise HTTPError(
            request.full_url,
            422,
            "Unprocessable Content",
            hdrs=Message(),
            fp=BytesIO(body),
        )

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardApiError, match=expected_message):
        RunCoachApiClient("http://localhost:8000").get_overview()


def test_client_translates_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del request, timeout
        raise URLError("connection refused")

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardApiError, match="unavailable"):
        RunCoachApiClient("http://localhost:8000").get_overview()
