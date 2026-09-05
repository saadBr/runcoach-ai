"""Typed HTTP boundary between the dashboard and the RunCoach API."""

import json
from datetime import date
from json import JSONDecodeError
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


class DashboardApiError(RuntimeError):
    """Raised when the dashboard cannot obtain a valid API response."""


class RunCoachApiClient:
    """Read-only client for dashboard-facing analytics endpoints."""

    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        normalized_url = base_url.rstrip("/")
        parsed_url = urlsplit(normalized_url)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("API base URL must be an absolute HTTP or HTTPS URL.")
        if timeout_seconds <= 0:
            raise ValueError("API timeout must be greater than zero.")

        self._base_url = normalized_url
        self._timeout_seconds = timeout_seconds

    def get_overview(self) -> JsonObject:
        """Return the current analytics overview."""

        return self._get_json("/api/v1/analytics/overview")

    def get_performance(self) -> JsonObject:
        """Return verified personal bests and prediction readiness."""

        return self._get_json("/api/v1/analytics/performance")

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

    def _request_json(self, path: str, *, method: str) -> JsonObject:
        request = Request(
            f"{self._base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "runcoach-dashboard",
            },
            method=method,
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as error:
            raise DashboardApiError(f"RunCoach API returned HTTP {error.code}.") from error
        except (TimeoutError, URLError) as error:
            raise DashboardApiError(
                "RunCoach API is unavailable or did not respond in time."
            ) from error

        try:
            payload: object = json.loads(response_body.decode("utf-8"))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise DashboardApiError("RunCoach API returned an invalid JSON response.") from error

        if not isinstance(payload, dict):
            raise DashboardApiError("RunCoach API returned an unexpected response structure.")

        return cast(JsonObject, payload)
