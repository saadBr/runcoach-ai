"""Tests for the dashboard HTTP client."""

import json
from datetime import date
from email.message import Message
from types import TracebackType
from typing import Never, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from runcoach.dashboard import api_client
from runcoach.dashboard.api_client import DashboardApiError, RunCoachApiClient


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


def test_client_translates_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, timeout: float) -> Never:
        del request, timeout
        raise URLError("connection refused")

    monkeypatch.setattr(api_client, "urlopen", fake_urlopen)

    with pytest.raises(DashboardApiError, match="unavailable"):
        RunCoachApiClient("http://localhost:8000").get_overview()
