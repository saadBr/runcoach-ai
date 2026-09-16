"""Typed HTTP boundary between the dashboard and the RunCoach API."""

import json
from collections.abc import Mapping
from datetime import date
from json import JSONDecodeError
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


class DashboardApiError(RuntimeError):
    """Raised when the dashboard cannot obtain a valid API response."""


class DashboardAuthenticationError(DashboardApiError):
    """Raised when the API rejects the current bearer session."""


class DashboardNotFoundError(DashboardApiError):
    """Raised when an optional dashboard resource does not exist."""


def _http_error_message(error: HTTPError) -> str:
    """Return an API's sanitized error detail when one is available."""

    fallback = f"RunCoach API returned HTTP {error.code}."
    try:
        payload: object = json.loads(error.read(64 * 1024).decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
        return fallback
    if not isinstance(payload, dict):
        return fallback

    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if not isinstance(detail, dict):
        return fallback

    message = detail.get("message")
    code = detail.get("code")
    if not isinstance(message, str) or not message.strip():
        return fallback
    if isinstance(code, str) and code.strip():
        return f"{message.strip()} [{code.strip()}]"
    return message.strip()


class RunCoachApiClient:
    """Typed client for authenticated dashboard-facing API endpoints."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        *,
        access_token: str | None = None,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed_url = urlsplit(normalized_url)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("API base URL must be an absolute HTTP or HTTPS URL.")
        if timeout_seconds <= 0:
            raise ValueError("API timeout must be greater than zero.")
        if access_token is not None and not access_token.strip():
            raise ValueError("API access token cannot be empty.")

        self._base_url = normalized_url
        self._timeout_seconds = timeout_seconds
        self._access_token = access_token

    def login(self, *, email: str, password: str) -> JsonObject:
        """Open a revocable account session without retaining the password."""

        body = json.dumps(
            {"email": email, "password": password},
            separators=(",", ":"),
        ).encode("utf-8")
        return self._request_json(
            "/api/v1/auth/login",
            method="POST",
            data=body,
            content_type="application/json",
        )

    def register(self, registration: Mapping[str, JsonValue]) -> JsonObject:
        """Create a pending athlete account with goal and benchmark metadata."""

        body = json.dumps(registration, separators=(",", ":")).encode("utf-8")
        return self._request_json(
            "/api/v1/auth/register",
            method="POST",
            data=body,
            content_type="application/json",
        )

    def get_current_account(self) -> JsonObject:
        """Return the athlete display context for the current bearer session."""

        return self._get_json("/api/v1/auth/me")

    def get_onboarding_account(self) -> JsonObject:
        """Return account state for a pending or completed onboarding session."""

        return self._get_json("/api/v1/auth/onboarding")

    def upload_strava_archive(self, *, filename: str, content: bytes) -> JsonObject:
        """Upload the required private Strava ZIP and build the initial plan."""

        if not filename.casefold().endswith(".zip"):
            raise ValueError("Strava history must be uploaded as a ZIP file.")
        if not content:
            raise ValueError("Strava history ZIP cannot be empty.")
        return self._request_json(
            "/api/v1/onboarding/strava-archive",
            method="POST",
            data=content,
            content_type="application/zip",
            extra_headers={"X-RunCoach-Filename": quote(filename, safe="")},
            timeout_seconds=max(self._timeout_seconds, 300.0),
        )

    def logout(self) -> None:
        """Revoke the current bearer session."""

        if self._access_token is None:
            raise ValueError("Logout requires an API access token.")
        response_body = self._request_bytes("/api/v1/auth/logout", method="POST")
        if response_body:
            raise DashboardApiError("RunCoach API returned unexpected logout content.")

    def get_overview(self) -> JsonObject:
        """Return the current analytics overview."""

        return self._get_json("/api/v1/analytics/overview")

    def get_performance(self) -> JsonObject:
        """Return verified personal bests and prediction readiness."""

        return self._get_json("/api/v1/analytics/performance")

    def get_performance_label_audit(
        self,
        *,
        review_status: str | None = "unreviewed",
        offset: int = 0,
        limit: int = 20,
    ) -> JsonObject:
        """Return a bounded private performance-review queue."""

        if offset < 0:
            raise ValueError("Label-audit offset cannot be negative.")
        if not 1 <= limit <= 100:
            raise ValueError("Label-audit limit must be between one and 100.")
        parameters = {"offset": str(offset), "limit": str(limit)}
        if review_status is not None:
            parameters["review_status"] = review_status
        return self._get_json(f"/api/v1/analytics/performance/label-audit?{urlencode(parameters)}")

    def review_performance_candidate(
        self,
        *,
        review_token: str,
        review_status: str,
        review_label: str | None = None,
        verified_elapsed_time_seconds: float | None = None,
        review_notes: str | None = None,
    ) -> JsonObject:
        """Persist one explicit label decision and return refreshed validation state."""

        if len(review_token) != 64 or any(
            character not in "0123456789abcdef" for character in review_token
        ):
            raise ValueError(
                "Performance review token must be 64 lowercase hexadecimal characters."
            )

        body = json.dumps(
            {
                "review_status": review_status,
                "review_label": review_label,
                "verified_elapsed_time_seconds": verified_elapsed_time_seconds,
                "review_notes": review_notes,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return self._request_json(
            f"/api/v1/analytics/performance/label-audit/{review_token}",
            method="PUT",
            data=body,
            content_type="application/json",
        )

    def get_training_plan(
        self,
        *,
        distance: str,
        race_date: date,
        target_time_seconds: float | None,
        days_per_week: int,
    ) -> JsonObject:
        """Return a goal-based training-plan preview."""

        if not 3 <= days_per_week <= 7:
            raise ValueError("Training days per week must be between three and seven.")
        query = self._training_plan_query(
            distance=distance,
            race_date=race_date,
            target_time_seconds=target_time_seconds,
            days_per_week=days_per_week,
        )
        return self._get_json(f"/api/v1/coaching/plan-preview?{query}")

    def save_training_plan(
        self,
        *,
        distance: str,
        race_date: date,
        target_time_seconds: float | None,
        days_per_week: int,
    ) -> JsonObject:
        """Persist and activate a goal-based training plan."""

        query = self._training_plan_query(
            distance=distance,
            race_date=race_date,
            target_time_seconds=target_time_seconds,
            days_per_week=days_per_week,
        )
        return self._request_json(f"/api/v1/coaching/plans/active?{query}", method="POST")

    def get_active_training_plan(self) -> JsonObject:
        """Return the currently active persisted training plan."""

        return self._get_json("/api/v1/coaching/plans/active")

    def refresh_active_training_plan(self) -> JsonObject:
        """Refresh the active plan against the latest imported evidence."""

        return self._request_json("/api/v1/coaching/plans/active/refresh", method="POST")

    def get_active_training_plan_tracking(
        self,
        *,
        as_of_date: date | None = None,
    ) -> JsonObject:
        """Return plan adherence and immutable revision history."""

        path = "/api/v1/coaching/plans/active/tracking"
        if as_of_date is not None:
            path = f"{path}?{urlencode({'as_of_date': as_of_date.isoformat()})}"
        return self._get_json(path)

    def upload_run(self, *, filename: str, title: str, content: bytes) -> JsonObject:
        """Upload one Strava FIT payload and return refreshed coaching state."""

        if not filename.strip():
            raise ValueError("Run filename cannot be blank.")
        if not title.strip():
            raise ValueError("Run title cannot be blank.")
        if not content:
            raise ValueError("Run file cannot be empty.")
        return self._request_json(
            "/api/v1/coaching/runs",
            method="POST",
            data=content,
            content_type="application/octet-stream",
            extra_headers={
                "X-RunCoach-Filename": quote(filename, safe=""),
                "X-RunCoach-Title": quote(title, safe=""),
            },
            timeout_seconds=max(self._timeout_seconds, 60.0),
        )

    def ask_coach(
        self,
        *,
        message: str,
        conversation: list[dict[str, str]] | None = None,
    ) -> JsonObject:
        """Ask the evidence-grounded coach with bounded dashboard-local history."""

        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("Coaching question cannot be blank.")
        turns = conversation or []
        if len(turns) > 8:
            raise ValueError("Coaching conversation can contain at most eight prior turns.")
        body = json.dumps(
            {"message": normalized_message, "conversation": turns},
            separators=(",", ":"),
        ).encode("utf-8")
        return self._request_json(
            "/api/v1/coaching/chat",
            method="POST",
            data=body,
            content_type="application/json",
            timeout_seconds=max(self._timeout_seconds, 30.0),
        )

    @staticmethod
    def _training_plan_query(
        *,
        distance: str,
        race_date: date,
        target_time_seconds: float | None,
        days_per_week: int,
    ) -> str:
        if not 3 <= days_per_week <= 7:
            raise ValueError("Training days per week must be between three and seven.")
        parameters = {
            "distance": distance,
            "race_date": race_date.isoformat(),
            "days_per_week": str(days_per_week),
        }
        if target_time_seconds is not None:
            if target_time_seconds <= 0:
                raise ValueError("Target time must be greater than zero.")
            parameters["target_time_seconds"] = str(target_time_seconds)
        return urlencode(parameters)

    def get_trends(
        self,
        *,
        weeks: int = 12,
        end_date: date | None = None,
    ) -> JsonObject:
        """Return weekly training and daily workload trends."""

        if not 1 <= weeks <= 52:
            raise ValueError("Trend history must contain between 1 and 52 weeks.")

        parameters = {"weeks": str(weeks)}
        if end_date is not None:
            parameters["end_date"] = end_date.isoformat()

        query = urlencode(parameters)
        return self._get_json(f"/api/v1/analytics/trends?{query}")

    def _get_json(self, path: str) -> JsonObject:
        return self._request_json(path, method="GET")

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        data: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> JsonObject:
        response_body = self._request_bytes(
            path,
            method=method,
            data=data,
            content_type=content_type,
            extra_headers=extra_headers,
            timeout_seconds=timeout_seconds,
        )

        try:
            payload: object = json.loads(response_body.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise DashboardApiError("RunCoach API returned an invalid JSON response.") from error

        if not isinstance(payload, dict):
            raise DashboardApiError("RunCoach API returned an unexpected response structure.")

        return cast(JsonObject, payload)

    def _request_bytes(
        self,
        path: str,
        *,
        method: str,
        data: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        headers = {
            "Accept": "application/json",
            "User-Agent": "runcoach-dashboard",
        }
        if self._access_token is not None:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if content_type is not None:
            headers["Content-Type"] = content_type
        if extra_headers is not None:
            headers.update(extra_headers)
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=(self._timeout_seconds if timeout_seconds is None else timeout_seconds),
            ) as response:
                response_body = response.read()
        except HTTPError as error:
            if error.code == 401:
                raise DashboardAuthenticationError(_http_error_message(error)) from error
            if error.code == 404:
                raise DashboardNotFoundError(_http_error_message(error)) from error
            raise DashboardApiError(_http_error_message(error)) from error
        except (TimeoutError, URLError) as error:
            raise DashboardApiError(
                "RunCoach API is unavailable or did not respond in time."
            ) from error
        return cast(bytes, response_body)
