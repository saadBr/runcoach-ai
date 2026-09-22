"""Headless integration tests for the Streamlit dashboard."""

import json
from collections.abc import Generator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, ClassVar, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from streamlit.testing.v1 import AppTest

from runcoach.dashboard.app import (
    COACH_MESSAGES_KEY,
    COACH_SESSION_OWNER_KEY,
    DEFAULT_HISTORY_WEEKS,
    HISTORY_WEEKS_KEY,
    RUN_UPLOAD_FEEDBACK_KEY,
    SESSION_TOKEN_KEY,
    bind_private_state_to_session,
    daily_workload_frame,
    dashboard_history_weeks,
    format_duration,
    format_optional,
    format_pace,
    format_performance_evidence_effort,
    upload_title_from_filename,
    weekly_frame,
)
from runcoach.dashboard.schemas import AnalyticsTrends, SelectedPerformanceEvidence

APP_PATH = Path(__file__).resolve().parents[2] / "src" / "runcoach" / "dashboard" / "app.py"
TEST_ACCESS_TOKEN = "opaque-dashboard-test-token-with-sufficient-length"


@pytest.mark.parametrize(
    ("kind", "target", "distance_km", "seconds", "expected"),
    (
        ("strong_training", None, 10.0, 2_570.0, "10.0 km in 42:50"),
        ("strong_training", None, 5.0, 1_315.0, "5.0 km in 21:55"),
        ("standard_distance_performance", "half_marathon", 21.3, 5_900.0, "21.3 km in 1:38:20"),
        ("observed_training_best", "10k", 20.0, 2_391.0, "10K in 39:51"),
    ),
)
def test_performance_evidence_effort_uses_timed_distance(
    kind: str,
    target: str | None,
    distance_km: float,
    seconds: float,
    expected: str,
) -> None:
    item = SelectedPerformanceEvidence.model_validate(
        {
            "activity_id": "018f0000-0000-7000-8000-000000000040",
            "activity_name": "Training run",
            "achieved_on": "2026-09-20",
            "evidence_kind": kind,
            "target_distance": target,
            "activity_distance_km": distance_km,
            "elapsed_time_seconds": seconds,
            "pace_seconds_per_km": seconds / distance_km,
            "session_kind": "easy",
            "reason": "Representative training evidence.",
        }
    )

    assert format_performance_evidence_effort(item) == expected


def test_private_chat_state_is_preserved_only_for_the_same_session() -> None:
    state: dict[str, object] = {}

    bind_private_state_to_session(state, "first-session-token")
    state[COACH_MESSAGES_KEY] = [{"role": "user", "content": "Private question"}]
    state[RUN_UPLOAD_FEEDBACK_KEY] = "Private upload result"
    original_owner = state[COACH_SESSION_OWNER_KEY]

    bind_private_state_to_session(state, "first-session-token")
    assert COACH_MESSAGES_KEY in state
    assert RUN_UPLOAD_FEEDBACK_KEY in state
    assert state[COACH_SESSION_OWNER_KEY] == original_owner

    bind_private_state_to_session(state, "different-account-session-token")
    assert COACH_MESSAGES_KEY not in state
    assert RUN_UPLOAD_FEEDBACK_KEY not in state
    assert state[COACH_SESSION_OWNER_KEY] != original_owner


CURRENT_ACCOUNT_PAYLOAD = {
    "athlete": {
        "display_name": "Synthetic Athlete",
        "timezone": "Africa/Casablanca",
        "onboarding_status": "ready",
    },
    "session_expires_at": "2026-10-07T12:00:00Z",
}

LOGIN_PAYLOAD = {
    "access_token": TEST_ACCESS_TOKEN,
    "token_type": "bearer",
    "expires_at": "2026-10-07T12:00:00Z",
    "athlete": CURRENT_ACCOUNT_PAYLOAD["athlete"],
}

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

PERSONAL_BESTS = [
    {
        "personal_best_id": "018f0000-0000-7000-8000-000000000020",
        "activity_id": "018f0000-0000-7000-8000-000000000010",
        "distance": "5k",
        "distance_m": 5000.0,
        "elapsed_time_seconds": 1181.0,
        "pace_seconds_per_km": 236.2,
        "achieved_at": "2026-05-15T09:00:00Z",
        "verification_status": "verified_max_effort",
        "effort_type": "provider_best_effort",
        "verification_source": "strava_best_effort",
        "algorithm_version": "strava_best_effort_import_v1",
    },
    {
        "personal_best_id": "018f0000-0000-7000-8000-000000000021",
        "activity_id": "018f0000-0000-7000-8000-000000000011",
        "distance": "10k",
        "distance_m": 10000.0,
        "elapsed_time_seconds": 2464.0,
        "pace_seconds_per_km": 246.4,
        "achieved_at": "2026-03-29T09:00:00Z",
        "verification_status": "verified_race",
        "effort_type": "provider_best_effort",
        "verification_source": "strava_best_effort",
        "algorithm_version": "strava_best_effort_import_v1",
    },
    {
        "personal_best_id": "018f0000-0000-7000-8000-000000000022",
        "activity_id": "018f0000-0000-7000-8000-000000000012",
        "distance": "half_marathon",
        "distance_m": 21097.5,
        "elapsed_time_seconds": 5606.0,
        "pace_seconds_per_km": 265.715,
        "achieved_at": "2026-06-28T09:00:00Z",
        "verification_status": "verified_race",
        "effort_type": "provider_best_effort",
        "verification_source": "strava_best_effort",
        "algorithm_version": "strava_best_effort_import_v1",
    },
    {
        "personal_best_id": "018f0000-0000-7000-8000-000000000023",
        "activity_id": "018f0000-0000-7000-8000-000000000013",
        "distance": "marathon",
        "distance_m": 42195.0,
        "elapsed_time_seconds": 13266.0,
        "pace_seconds_per_km": 314.402,
        "achieved_at": "2026-04-12T09:00:00Z",
        "verification_status": "verified_race",
        "effort_type": "provider_best_effort",
        "verification_source": "strava_best_effort",
        "algorithm_version": "strava_best_effort_import_v1",
    },
]

PERFORMANCE_PAYLOAD = {
    "personal_bests": PERSONAL_BESTS,
    "current_bests": [
        {
            "distance": best["distance"],
            "elapsed_time_seconds": best["elapsed_time_seconds"],
            "pace_seconds_per_km": best["pace_seconds_per_km"],
            "achieved_on": str(best["achieved_at"])[:10],
            "activity_id": best["activity_id"],
            "activity_name": "Synthetic Run",
            "activity_distance_km": cast(float, best["distance_m"]) / 1_000,
            "source": "verified_result",
        }
        for best in PERSONAL_BESTS
    ],
    "current_fitness": {
        "algorithm_version": "training_context_fitness_v2",
        "status": "experimental_not_validated",
        "as_of_date": "2026-08-27",
        "anchor": {
            "distance": "5k",
            "elapsed_time_seconds": 1181.0,
            "achieved_on": "2026-05-15",
            "verification_status": "verified_max_effort",
            "effort_type": "provider_best_effort",
            "activity_distance_km": 11.0,
            "session_kind": "tempo",
        },
        "prior_anchor": None,
        "anchor_capacity_factor": 0.96,
        "anchor_improvement_factor": 0.96,
        "training": {
            "as_of_date": "2026-08-27",
            "runs_28d": 21,
            "distance_28d_km": 257.349,
            "runs_84d": 60,
            "distance_84d_km": 650.0,
            "longest_run_84d_km": 28.0,
            "classified_sessions_84d": 8,
            "quality_sessions_84d": 5,
            "runs_168d": 100,
            "distance_168d_km": 1000.0,
            "runs_365d": 125,
            "distance_365d_km": 1320.0,
        },
        "estimates": [
            {
                "distance": record["distance"],
                "fitness_potential_time_seconds": record["elapsed_time_seconds"],
                "race_readiness_time_seconds": record["elapsed_time_seconds"],
                "optimistic_time_seconds": cast(float, record["elapsed_time_seconds"]) * 0.98,
                "conservative_time_seconds": cast(float, record["elapsed_time_seconds"]) * 1.02,
                "fitness_potential_pace_seconds_per_km": record["pace_seconds_per_km"],
                "race_readiness_pace_seconds_per_km": record["pace_seconds_per_km"],
                "preparation_score": 1.0,
                "confidence": "medium",
                "current_pb_seconds": record["elapsed_time_seconds"],
                "improvement_from_pb_seconds": 0.0,
                "basis": "Verified personal performance.",
            }
            for record in PERSONAL_BESTS
        ],
        "limitations": ["Experimental estimate; chronological validation is pending."],
    },
    "prediction_status": "experimental_not_validated",
    "prediction_method": "training_context_fitness_v2",
    "verified_labels": 4,
    "interpretation_role": "openai_explains_validated_outputs_only",
    "limitations": ["Experimental estimate; chronological validation is pending."],
}

LABEL_AUDIT_PAYLOAD = {
    "dataset_version": "performance_training_features_v3",
    "total_rows": 70,
    "verified_rows": 5,
    "excluded_rows": 0,
    "unreviewed_rows": 65,
    "offset": 0,
    "returned_rows": 1,
    "candidates": [
        {
            "review_token": "a" * 64,
            "achieved_at": "2026-07-01T08:00:00Z",
            "matched_distance": "5k",
            "measured_distance_m": 5005.0,
            "recorded_elapsed_time_seconds": 1260.0,
            "distance_deviation_pct": 0.1,
            "session_kind": "unclassified",
            "review_status": "unreviewed",
            "review_label": None,
            "verified_elapsed_time_seconds": None,
            "review_notes": None,
        }
    ],
    "validation": {
        "status": "descriptive_only",
        "verified_labels": 5,
        "chronological_targets": 4,
        "candidate_model_eligible": False,
        "eligibility_reasons": ["Only 5 verified labels are available; at least 30 are required."],
        "aggregate_metrics": [
            {
                "baseline": "riegel_best_prior",
                "predictions": 4,
                "mean_absolute_error_seconds": 539.5,
                "median_absolute_error_seconds": 113.1,
                "mean_absolute_percentage_error": 5.6,
                "mean_signed_error_seconds": -512.6,
            }
        ],
    },
}

TRAINING_PLAN_PAYLOAD = {
    "algorithm_version": "goal_plan_preview_v1",
    "status": "preview_not_persisted",
    "as_of_date": "2026-08-27",
    "plan_start_date": "2026-08-31",
    "goal": {
        "distance": "marathon",
        "race_date": "2026-11-19",
        "target_time_seconds": 13_266.0,
        "days_per_week": 6,
    },
    "goal_status": "achievable",
    "weeks_to_race": 12,
    "fitness_potential_seconds": 12_900.0,
    "current_readiness_seconds": 13_266.0,
    "recommended_target_seconds": 13_266.0,
    "target_gap_seconds": 0.0,
    "current_preparation_score": 0.92,
    "recent_weekly_distance_km": 64.337,
    "first_week": [
        {
            "scheduled_date": "2026-08-31",
            "kind": "easy",
            "title": "Easy aerobic run",
            "distance_km": 9.0,
            "pace": {
                "faster_seconds_per_km": 306.0,
                "slower_seconds_per_km": 346.0,
            },
            "purpose": "Maintain aerobic frequency.",
        },
        {
            "scheduled_date": "2026-09-01",
            "kind": "quality",
            "title": "3 x 4 km at controlled marathon effort",
            "distance_km": 10.0,
            "pace": {
                "faster_seconds_per_km": 309.0,
                "slower_seconds_per_km": 319.0,
            },
            "purpose": "Develop marathon durability.",
        },
        {
            "scheduled_date": "2026-09-06",
            "kind": "long",
            "title": "Long aerobic run",
            "distance_km": 19.0,
            "pace": {
                "faster_seconds_per_km": 291.0,
                "slower_seconds_per_km": 331.0,
            },
            "purpose": "Build aerobic durability.",
        },
    ],
    "weekly_outline": [
        {
            "week_number": 1,
            "start_date": "2026-08-31",
            "end_date": "2026-09-06",
            "phase": "base",
            "target_distance_km": 59.2,
            "long_run_km": 19.0,
            "quality_focus": "marathon pace and fueling durability",
        },
        {
            "week_number": 2,
            "start_date": "2026-09-07",
            "end_date": "2026-09-13",
            "phase": "base",
            "target_distance_km": 61.3,
            "long_run_km": 19.6,
            "quality_focus": "marathon pace and fueling durability",
        },
    ],
    "rationale": ["The plan uses current fitness and recent volume."],
    "guardrails": ["Keep easy days conversational."],
}

PERSISTED_TRAINING_PLAN_PAYLOAD = {
    "goal_id": "018f0000-0000-7000-8000-000000000030",
    "plan_id": "018f0000-0000-7000-8000-000000000031",
    "version": 1,
    "created": True,
    "preview": TRAINING_PLAN_PAYLOAD,
}

ACTIVE_TRAINING_PLAN_PAYLOAD = {
    **PERSISTED_TRAINING_PLAN_PAYLOAD,
    "created": False,
    "preview": {
        **TRAINING_PLAN_PAYLOAD,
        "goal": {
            "distance": "10k",
            "race_date": "2026-12-01",
            "target_time_seconds": 2_460,
            "days_per_week": 5,
        },
    },
}

PLAN_TRACKING_PAYLOAD = {
    "goal_id": "018f0000-0000-7000-8000-000000000030",
    "plan_id": "018f0000-0000-7000-8000-000000000031",
    "active_version": 1,
    "as_of_date": "2026-08-27",
    "plan_start_date": "2026-08-31",
    "race_date": "2027-01-31",
    "status": "not_started",
    "completed_weeks": 0,
    "total_weeks": 2,
    "current_week_number": None,
    "planned_distance_to_date_km": 0.0,
    "actual_distance_to_date_km": 0.0,
    "adherence_pct": None,
    "weeks": [
        {
            "week_number": week["week_number"],
            "start_date": week["start_date"],
            "end_date": week["end_date"],
            "phase": week["phase"],
            "status": "upcoming",
            "target_distance_km": week["target_distance_km"],
            "target_long_run_km": week["long_run_km"],
            "actual_runs": 0,
            "actual_distance_km": 0.0,
            "actual_long_run_km": 0.0,
            "distance_completion_pct": 0.0,
            "long_run_completion_pct": 0.0,
        }
        for week in cast(
            list[dict[str, object]],
            TRAINING_PLAN_PAYLOAD["weekly_outline"],
        )
    ],
    "sessions": [
        {
            "scheduled_date": session["scheduled_date"],
            "kind": session["kind"],
            "title": session["title"],
            "target_distance_km": session["distance_km"],
            "status": "upcoming",
            "matched_activity_date": None,
            "matched_activity_name": None,
            "actual_distance_km": None,
            "actual_pace_seconds_per_km": None,
            "classified_as": None,
            "distance_completion_pct": None,
            "pace_status": "unavailable",
        }
        for session in cast(
            list[dict[str, object]],
            TRAINING_PLAN_PAYLOAD["first_week"],
        )
    ],
    "recommendation_code": "plan_not_started",
    "recommendation": "The plan begins with an easy aerobic run.",
    "versions": [
        {
            "plan_id": "018f0000-0000-7000-8000-000000000031",
            "version": 1,
            "status": "active",
            "evidence_as_of_date": "2026-08-27",
            "created_at": "2026-08-27T10:00:00Z",
            "superseded_at": None,
            "recent_weekly_distance_km": 64.337,
            "first_week_target_km": 59.2,
            "peak_week_target_km": 61.3,
            "peak_long_run_km": 19.6,
        }
    ],
}

COACH_REPLY_PAYLOAD = {
    "answer": (
        "Keep tomorrow easy. Your recent workload is already high, so another hard session "
        "would add fatigue without much benefit before the next quality workout."
    ),
    "evidence_ids": ["workload:2026-08-27", "plan:next-session:1"],
    "limitations": ["Sleep and soreness are not available."],
    "mode": "openai",
    "model": "gpt-test",
    "context_version": "coaching_context_v2",
    "prompt_version": "evidence_coach_v4",
}


class StubAnalyticsHandler(BaseHTTPRequestHandler):
    """Serve deterministic aggregate responses to the dashboard test."""

    chat_status = 200
    active_plan_status = 200
    plan_mutations: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        request_url = urlsplit(self.path)

        if request_url.path in {"/api/v1/auth/me", "/api/v1/auth/onboarding"}:
            if not self._authorized():
                return
            self._respond(CURRENT_ACCOUNT_PAYLOAD)
            return

        if not self._authorized():
            return

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

        if request_url.path == "/api/v1/analytics/performance":
            self._respond(PERFORMANCE_PAYLOAD)
            return

        if request_url.path == "/api/v1/analytics/performance/label-audit":
            self._respond(LABEL_AUDIT_PAYLOAD)
            return

        if request_url.path == "/api/v1/coaching/plans/active":
            if self.active_plan_status == 200:
                self._respond(ACTIVE_TRAINING_PLAN_PAYLOAD)
            else:
                self._respond(
                    {"detail": "No active persisted training plan exists."},
                    status=self.active_plan_status,
                )
            return

        if request_url.path == "/api/v1/coaching/plan-preview":
            self._respond(TRAINING_PLAN_PAYLOAD)
            return

        if request_url.path == "/api/v1/coaching/plans/active/tracking":
            self._respond(PLAN_TRACKING_PAYLOAD)
            return

        self._respond({"detail": "Not found"}, status=404)

    def do_POST(self) -> None:
        request_url = urlsplit(self.path)
        if request_url.path == "/api/v1/auth/login":
            self._respond(LOGIN_PAYLOAD)
            return
        if request_url.path == "/api/v1/auth/logout":
            if not self._authorized():
                return
            self.send_response(204)
            self.end_headers()
            return
        if not self._authorized():
            return
        if request_url.path in {
            "/api/v1/coaching/plans/active",
            "/api/v1/coaching/plans/active/refresh",
        }:
            self.plan_mutations.append(request_url.path)
            self._respond(PERSISTED_TRAINING_PLAN_PAYLOAD)
            return
        if request_url.path == "/api/v1/coaching/chat":
            if self.chat_status == 200:
                self._respond(COACH_REPLY_PAYLOAD)
            else:
                self._respond({"detail": "Temporary provider failure."}, status=self.chat_status)
            return
        self._respond({"detail": "Not found"}, status=404)

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {TEST_ACCESS_TOKEN}":
            return True
        self._respond({"detail": "Authentication is required."}, status=401)
        return False

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

    StubAnalyticsHandler.chat_status = 200
    StubAnalyticsHandler.active_plan_status = 200
    StubAnalyticsHandler.plan_mutations = []
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


def _authenticated_dashboard() -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.session_state[SESSION_TOKEN_KEY] = TEST_ACCESS_TOKEN
    return app.run()


def test_dashboard_requires_login_before_loading_private_data(
    dashboard_api: None,
) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()

    assert dashboard_api is None
    assert not app.exception
    assert app.title[0].value == "RunCoach AI"
    text_labels = [field.label for field in app.text_input]
    assert {"Email", "Password", "Athlete name", "Account email"} <= set(text_labels)
    assert "Sign in" in [button.label for button in app.button]
    assert "Create account and plan" in [button.label for button in app.button]
    assert [tab.label for tab in app.tabs] == ["Sign in", "Create account"]
    assert "Strava history ZIP (required)" in [upload.label for upload in app.file_uploader]
    assert not app.metric


def test_successful_login_replaces_authentication_ui_with_ready_dashboard(
    dashboard_api: None,
) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    email = next(field for field in app.text_input if field.label == "Email")
    password = next(field for field in app.text_input if field.label == "Password")
    email.set_value("athlete@example.test")
    password.set_value("correct horse battery staple")
    sign_in = next(button for button in app.button if button.label == "Sign in")

    app = sign_in.click().run()

    assert dashboard_api is None
    assert not app.exception
    assert app.session_state[SESSION_TOKEN_KEY] == TEST_ACCESS_TOKEN
    assert [tab.label for tab in app.tabs] == [
        "Training volume",
        "Performance",
        "Coach",
        "Training plan",
        "Workload and form",
        "Data coverage",
    ]
    assert "Email" not in [field.label for field in app.text_input]
    assert "Signed in as Synthetic Athlete" in [message.value for message in app.success]
    assert "Loading your dashboard..." not in str(app)


def test_invalid_session_returns_to_login_without_private_controls(
    dashboard_api: None,
) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.session_state[SESSION_TOKEN_KEY] = "invalid-session-token-with-sufficient-length"

    app = app.run()

    assert dashboard_api is None
    assert SESSION_TOKEN_KEY not in app.session_state
    assert [tab.label for tab in app.tabs] == ["Sign in", "Create account"]
    assert "Your session expired. Sign in again." in [message.value for message in app.error]
    assert "Dashboard controls" not in [header.value for header in app.header]


def test_dashboard_load_failure_shows_retry_without_private_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNCOACH_API_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.session_state[SESSION_TOKEN_KEY] = TEST_ACCESS_TOKEN

    app = app.run()

    assert not app.exception
    assert "We couldn't load your dashboard. Check the service and try again." in [
        message.value for message in app.error
    ]
    assert "Try again" in [button.label for button in app.button]
    assert "Dashboard controls" not in [header.value for header in app.header]
    assert not app.metric


def test_dashboard_renders_validated_analytics(
    dashboard_api: None,
) -> None:
    app = _authenticated_dashboard()

    assert dashboard_api is None
    assert not app.exception
    assert app.title[0].value == "RunCoach AI"
    assert "Signed in as Synthetic Athlete" in [message.value for message in app.success]
    assert [metric.label for metric in app.metric[:5]] == [
        "Total runs",
        "Total distance",
        "Moving time",
        "Last 7 days",
        "Current form index",
    ]
    assert app.metric[0].value == "130"
    assert len(app.tabs) == 6
    assert [tab.label for tab in app.tabs] == [
        "Training volume",
        "Performance",
        "Coach",
        "Training plan",
        "Workload and form",
        "Data coverage",
    ]
    assert "5K" in [metric.label for metric in app.metric]
    assert "Model status" not in [metric.label for metric in app.metric]
    assert "Latest performance marker" in [metric.label for metric in app.metric]
    assert "Training history" in [metric.label for metric in app.metric]
    assert "Training considered through" in [metric.label for metric in app.metric]
    assert "Reviewed" not in [metric.label for metric in app.metric]
    assert "Verified efforts" not in [metric.label for metric in app.metric]
    assert "Chronological targets" not in [metric.label for metric in app.metric]
    assert "Goal assessment" in [metric.label for metric in app.metric]
    assert "Active version" not in [metric.label for metric in app.metric]
    assert "Distance adherence" in [metric.label for metric in app.metric]
    assert app.selectbox[0].value == "10k"
    race_date_input = next(widget for widget in app.date_input if widget.label == "Race date")
    assert race_date_input.value == date(2026, 12, 1)
    assert race_date_input.max == date(2027, 8, 26)
    sliders = {slider.label: slider.value for slider in app.slider}
    assert sliders["Training history"] == 12
    assert sliders["Running days per week"] == 5
    assert "Active training plan" in [heading.value for heading in app.subheader]
    assert "View plan provenance" not in [expander.label for expander in app.expander]
    assert "View performance calculation provenance" not in [
        expander.label for expander in app.expander
    ]
    assert "See how your plan has adapted" in [expander.label for expander in app.expander]
    assert "Calculation provenance" not in [heading.value for heading in app.subheader]
    assert "Refresh dashboard" in [button.label for button in app.button]
    assert "Refresh calculated data" not in [button.label for button in app.button]


def test_dashboard_shows_training_split_as_current_personal_best(
    dashboard_api: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        PERFORMANCE_PAYLOAD,
        "current_bests",
        [
            {
                **best,
                "elapsed_time_seconds": 2_400.0,
                "pace_seconds_per_km": 240.0,
                "achieved_on": "2026-10-01",
                "activity_id": "018f0000-0000-7000-8000-000000000040",
                "activity_name": "8K Easy + 10K HM Pace + 2K CD",
                "activity_distance_km": 20.0,
                "source": "training_split",
            }
            if best["distance"] == "10k"
            else best
            for best in cast(list[dict[str, object]], PERFORMANCE_PAYLOAD["current_bests"])
        ],
    )

    app = _authenticated_dashboard()

    assert dashboard_api is None
    assert not app.exception
    assert "Personal bests" in [heading.value for heading in app.subheader]
    assert "Faster splits found in training" not in [heading.value for heading in app.subheader]
    assert any(metric.label == "10K" and metric.value == "40:00" for metric in app.metric)
    assert any(caption.value == "2026-10-01" for caption in app.caption)
    assert not any("training split" in caption.value for caption in app.caption)


def test_sign_out_clears_token_and_private_coach_history(
    dashboard_api: None,
) -> None:
    app = _authenticated_dashboard()
    app.session_state[COACH_MESSAGES_KEY] = [
        {"role": "user", "content": "Private account-specific question"}
    ]

    sign_out = next(button for button in app.button if button.label == "Sign out")
    app = sign_out.click().run()

    assert dashboard_api is None
    assert SESSION_TOKEN_KEY not in app.session_state
    assert COACH_MESSAGES_KEY not in app.session_state
    assert COACH_SESSION_OWNER_KEY not in app.session_state
    assert [tab.label for tab in app.tabs] == ["Sign in", "Create account"]


def test_history_slider_reruns_dashboard(
    dashboard_api: None,
) -> None:
    app = _authenticated_dashboard()

    history_slider = next(slider for slider in app.slider if slider.label == "Training history")
    history_slider.set_value(4).run()

    assert dashboard_api is None
    assert not app.exception
    sliders = {slider.label: slider.value for slider in app.slider}
    assert sliders["Training history"] == 4
    assert app.metric[1].value == "1,376.1 km"


def test_history_window_is_initialized_before_sidebar_rendering() -> None:
    state: dict[str, object] = {}

    assert dashboard_history_weeks(state) == DEFAULT_HISTORY_WEEKS
    assert state[HISTORY_WEEKS_KEY] == DEFAULT_HISTORY_WEEKS

    state[HISTORY_WEEKS_KEY] = 20
    assert dashboard_history_weeks(state) == 20

    state[HISTORY_WEEKS_KEY] = "invalid"
    assert dashboard_history_weeks(state) == DEFAULT_HISTORY_WEEKS
    assert state[HISTORY_WEEKS_KEY] == DEFAULT_HISTORY_WEEKS


def test_coach_keeps_question_visible_and_hides_internal_metadata(
    dashboard_api: None,
) -> None:
    app = _authenticated_dashboard()

    app = app.chat_input[0].set_value("Should I run hard tomorrow?").run()

    assert dashboard_api is None
    assert not app.exception
    history = app.session_state[COACH_MESSAGES_KEY]
    assert history[-2] == {"role": "user", "content": "Should I run hard tomorrow?"}
    assert history[-1] == {
        "role": "assistant",
        "content": COACH_REPLY_PAYLOAD["answer"],
    }
    rendered_markdown = [element.value for element in app.markdown]
    assert "Should I run hard tomorrow?" in rendered_markdown
    assert COACH_REPLY_PAYLOAD["answer"] in rendered_markdown
    rendered_captions = [element.value for element in app.caption]
    assert not any(value.startswith("Evidence:") for value in rendered_captions)
    assert not any(value.startswith("Mode:") for value in rendered_captions)
    assert "plan:next-session:1" not in str(history)


def test_coach_retains_question_when_api_fails(dashboard_api: None) -> None:
    StubAnalyticsHandler.chat_status = 503
    app = _authenticated_dashboard()

    app = app.chat_input[0].set_value("Can you review today's run?").run()

    assert dashboard_api is None
    assert not app.exception
    history = app.session_state[COACH_MESSAGES_KEY]
    assert history[-2] == {"role": "user", "content": "Can you review today's run?"}
    assert history[-1]["role"] == "assistant"
    assert "please try again" in str(history[-1]["content"])
    assert "Temporary provider failure" not in str(app)


def test_training_plan_can_be_persisted_from_dashboard(dashboard_api: None) -> None:
    app = _authenticated_dashboard()

    save_button = next(button for button in app.button if button.label == "Save goal changes")
    save_button.click().run()

    assert dashboard_api is None
    assert not app.exception
    assert "Your active plan was created and saved." in [message.value for message in app.success]


def test_browser_refresh_only_reads_existing_plan(dashboard_api: None) -> None:
    app = _authenticated_dashboard()

    assert StubAnalyticsHandler.plan_mutations == []
    app = app.run()

    assert dashboard_api is None
    assert not app.exception
    assert StubAnalyticsHandler.plan_mutations == []
    assert app.selectbox[0].value == "10k"


def test_no_active_plan_shows_explicit_creation_state(dashboard_api: None) -> None:
    StubAnalyticsHandler.active_plan_status = 404

    app = _authenticated_dashboard()

    assert dashboard_api is None
    assert not app.exception
    assert "Create active plan" in [button.label for button in app.button]
    assert StubAnalyticsHandler.plan_mutations == []
    assert any("do not have an active training plan" in message.value for message in app.info)


def test_active_plan_updates_only_after_explicit_action(dashboard_api: None) -> None:
    app = _authenticated_dashboard()

    refresh = next(
        button for button in app.button if button.label == "Update plan from latest training"
    )
    app = refresh.click().run()

    assert dashboard_api is None
    assert not app.exception
    assert StubAnalyticsHandler.plan_mutations == ["/api/v1/coaching/plans/active/refresh"]


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
    assert format_duration(1_181) == "19:41"
    assert format_duration(13_266) == "3:41:06"
    assert format_optional(6.2352, decimals=2) == "6.24"
    assert format_optional(None) == "Unavailable"
    assert weekly.loc[1, "pace_display"] == "Unavailable"
    assert weekly["distance_km"].sum() == pytest.approx(76.037)
    assert workload.loc[0, "acute_load"] == pytest.approx(38.5717)


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        ("Progressive_long_run (1).fit", "Progressive long run"),
        ("Tempo_Run.fit.gz", "Tempo Run"),
    ),
)
def test_upload_title_is_derived_from_strava_filename(
    filename: str,
    expected: str,
) -> None:
    assert upload_title_from_filename(filename) == expected
