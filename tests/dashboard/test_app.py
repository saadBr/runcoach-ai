"""Headless integration tests for the Streamlit dashboard."""

import json
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from streamlit.testing.v1 import AppTest

from runcoach.dashboard.app import (
    daily_workload_frame,
    format_optional,
    format_pace,
    weekly_frame,
)
from runcoach.dashboard.schemas import AnalyticsTrends

APP_PATH = Path(__file__).resolve().parents[2] / "src" / "runcoach" / "dashboard" / "app.py"

WORKLOAD_PAYLOAD = {
    "local_date": "2026-08-27",
    "load_method": "duration_minutes_v1",
    "algorithm_version": "daily_load_v1",
    "daily_load": 0.0,
    "acute_load": 38.5717,
    "chronic_load": 44.8069,
    "fitness_index": 44.8069,
    "fatigue_index": 38.5717,
    "form_index": 6.2352,
    "coverage_pct": 100.0,
}

OVERVIEW_PAYLOAD = {
    "as_of_date": "2026-08-27",
    "data_start_date": "2024-05-21",
    "data_end_date": "2026-08-23",
    "total_runs": 130,
    "total_distance_km": 1376.081,
    "total_moving_hours": 123.432,
    "last_7_days": {
        "days": 7,
        "start_date": "2026-08-21",
        "end_date": "2026-08-27",
        "runs": 3,
        "distance_km": 44.024,
        "moving_hours": 4.458,
    },
    "last_28_days": {
        "days": 28,
        "start_date": "2026-07-31",
        "end_date": "2026-08-27",
        "runs": 21,
        "distance_km": 257.349,
        "moving_hours": 25.003,
    },
    "sensor_coverage": {
        "activities_with_metrics": 130,
        "activities_with_heart_rate_load": 85,
        "average_heart_rate_coverage_pct": 65.081,
        "average_gps_coverage_pct": 96.86,
        "average_cadence_coverage_pct": 65.081,
    },
    "workload": WORKLOAD_PAYLOAD,
}

WEEKLY_PAYLOAD = {
    "week_start": "2026-08-17",
    "week_end": "2026-08-23",
    "runs": 6,
    "distance_km": 76.037,
    "moving_hours": 7.682,
    "duration_load_minutes": 460.916,
    "weighted_pace_seconds_per_km": 363.703,
    "elevation_gain_m": 608.5,
    "heart_rate_load_activities": 6,
    "edwards_trimp": 1155.033,
}


class StubAnalyticsHandler(BaseHTTPRequestHandler):
    """Serve deterministic aggregate responses to the dashboard test."""

    def do_GET(self) -> None:
        request_url = urlsplit(self.path)

        if request_url.path == "/api/v1/analytics/overview":
            self._respond(OVERVIEW_PAYLOAD)
            return

        if request_url.path == "/api/v1/analytics/trends":
            parameters = parse_qs(request_url.query)
            requested_weeks = int(parameters.get("weeks", ["12"])[0])
            self._respond(
                {
                    "start_date": "2026-08-17",
                    "end_date": "2026-08-27",
                    "requested_weeks": requested_weeks,
                    "weekly_training": [WEEKLY_PAYLOAD],
                    "daily_workload": [WORKLOAD_PAYLOAD],
                }
            )
            return

        self._respond({"detail": "Not found"}, status=404)

    def _respond(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def dashboard_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Run an isolated local aggregate API for one dashboard test."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), StubAnalyticsHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    monkeypatch.setenv(
        "RUNCOACH_API_URL",
        f"http://127.0.0.1:{server.server_port}",
    )

    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_dashboard_renders_validated_analytics(
    dashboard_api: None,
) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()

    assert dashboard_api is None
    assert not app.exception
    assert app.title[0].value == "RunCoach AI"
    assert [metric.label for metric in app.metric[:5]] == [
        "Total runs",
        "Total distance",
        "Moving time",
        "Last 7 days",
        "Current form index",
    ]
    assert app.metric[0].value == "130"
    assert len(app.tabs) == 3
    assert [tab.label for tab in app.tabs] == [
        "Training volume",
        "Workload and form",
        "Data coverage",
    ]
    assert app.slider[0].value == 12


def test_history_slider_reruns_dashboard(
    dashboard_api: None,
) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()

    app.slider[0].set_value(4).run()

    assert dashboard_api is None
    assert not app.exception
    assert app.slider[0].value == 4
    assert app.metric[1].value == "1,376.1 km"


def test_presentation_helpers_preserve_missing_evidence() -> None:
    empty_week = {
        **WEEKLY_PAYLOAD,
        "week_start": "2026-08-24",
        "week_end": "2026-08-27",
        "runs": 0,
        "distance_km": 0.0,
        "moving_hours": 0.0,
        "duration_load_minutes": 0.0,
        "weighted_pace_seconds_per_km": None,
        "elevation_gain_m": None,
        "heart_rate_load_activities": 0,
        "edwards_trimp": None,
    }
    trends = AnalyticsTrends.model_validate(
        {
            "start_date": "2026-08-17",
            "end_date": "2026-08-27",
            "requested_weeks": 2,
            "weekly_training": [WEEKLY_PAYLOAD, empty_week],
            "daily_workload": [WORKLOAD_PAYLOAD],
        }
    )

    weekly = weekly_frame(trends)
    workload = daily_workload_frame(trends)

    assert format_pace(341.709) == "5:42 /km"
    assert format_pace(None) == "Unavailable"
    assert format_optional(6.2352, decimals=2) == "6.24"
    assert format_optional(None) == "Unavailable"
    assert weekly.loc[1, "pace_display"] == "Unavailable"
    assert weekly["distance_km"].sum() == pytest.approx(76.037)
    assert workload.loc[0, "acute_load"] == pytest.approx(38.5717)
