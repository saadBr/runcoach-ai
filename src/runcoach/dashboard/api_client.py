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
        request = Request(
            f"{self._base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "runcoach-dashboard",
            },
            method="GET",
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
