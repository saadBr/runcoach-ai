"""Streamlit analytical dashboard backed exclusively by the RunCoach API."""

import os
import re
from collections.abc import MutableMapping
from contextlib import suppress
from datetime import date, timedelta
from hashlib import sha256
from typing import cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from runcoach.analytics.performance import StandardDistance
from runcoach.dashboard.api_client import DashboardApiError, RunCoachApiClient
from runcoach.dashboard.schemas import (
    ActivePlanTracking,
    AnalyticsOverview,
    AnalyticsTrends,
    CoachingReply,
    CurrentAccount,
    LoginSession,
    OnboardingResult,
    PerformanceLabelAudit,
    PerformanceOverview,
    PersistedTrainingPlan,
    TrainingPlanPreview,
    UploadedRunResult,
)

DEFAULT_API_URL = "http://localhost:8000"
SESSION_TOKEN_KEY = "runcoach_access_token"
COACH_MESSAGES_KEY = "coach_messages"
COACH_SESSION_OWNER_KEY = "coach_session_owner"
CHART_CONFIG = {"displayModeBar": False, "responsive": True}
DISTANCE_LABELS = {
    StandardDistance.FIVE_K: "5K",
    StandardDistance.TEN_K: "10K",
    StandardDistance.HALF_MARATHON: "Half marathon",
    StandardDistance.MARATHON: "Marathon",
}

NEXT_MARATHON_DATE = date(2027, 1, 31)


def bind_private_state_to_session(
    state: MutableMapping[str, object],
    access_token: str,
) -> None:
    """Keep visible private state available only to the bearer session that created it."""

    owner = sha256(access_token.encode("utf-8")).hexdigest()
    if state.get(COACH_SESSION_OWNER_KEY) != owner:
        state.pop(COACH_MESSAGES_KEY, None)
    state[COACH_SESSION_OWNER_KEY] = owner


def establish_authenticated_session(access_token: str) -> None:
    """Install a new token and isolate private dashboard state from prior accounts."""

    bind_private_state_to_session(
        cast(MutableMapping[str, object], st.session_state),
        access_token,
    )
    st.session_state[SESSION_TOKEN_KEY] = access_token


def clear_authenticated_session() -> None:
    """Remove credentials and all account-scoped dashboard state."""

    st.session_state.pop(SESSION_TOKEN_KEY, None)
    st.session_state.pop(COACH_SESSION_OWNER_KEY, None)
    st.session_state.pop(COACH_MESSAGES_KEY, None)


def load_dashboard_data(
    api_url: str,
    weeks: int,
) -> tuple[AnalyticsOverview, AnalyticsTrends, PerformanceOverview]:
    """Load and validate one consistent dashboard view."""

    client = authenticated_api_client(api_url)
    overview = AnalyticsOverview.model_validate(client.get_overview())
    trends = AnalyticsTrends.model_validate(client.get_trends(weeks=weeks))
    performance = PerformanceOverview.model_validate(client.get_performance())
    return overview, trends, performance


def load_training_plan(
    api_url: str,
    distance: StandardDistance,
    race_date: date,
    target_time_seconds: float | None,
    days_per_week: int,
) -> TrainingPlanPreview:
    """Load and validate a goal-based training-plan preview."""

    payload = authenticated_api_client(api_url).get_training_plan(
        distance=distance.value,
        race_date=race_date,
        target_time_seconds=target_time_seconds,
        days_per_week=days_per_week,
    )
    return TrainingPlanPreview.model_validate(payload)


def save_training_plan(
    api_url: str,
    distance: StandardDistance,
    race_date: date,
    target_time_seconds: float | None,
    days_per_week: int,
) -> PersistedTrainingPlan:
    """Persist the selected goal and activate its generated plan."""

    payload = authenticated_api_client(api_url).save_training_plan(
        distance=distance.value,
        race_date=race_date,
        target_time_seconds=target_time_seconds,
        days_per_week=days_per_week,
    )
    return PersistedTrainingPlan.model_validate(payload)


def refresh_active_training_plan(api_url: str) -> PersistedTrainingPlan:
    """Refresh the active plan from the latest imported activity evidence."""

    payload = authenticated_api_client(api_url).refresh_active_training_plan()
    return PersistedTrainingPlan.model_validate(payload)


def load_active_plan_tracking(api_url: str) -> ActivePlanTracking:
    """Load validated adherence and version history for the active plan."""

    payload = authenticated_api_client(api_url).get_active_training_plan_tracking()
    return ActivePlanTracking.model_validate(payload)


def upload_run(
    api_url: str,
    *,
    filename: str,
    title: str,
    content: bytes,
) -> UploadedRunResult:
    """Upload one private FIT activity and validate the coaching update."""

    payload = authenticated_api_client(api_url).upload_run(
        filename=filename,
        title=title,
        content=content,
    )
    return UploadedRunResult.model_validate(payload)


def ask_coach(
    api_url: str,
    *,
    message: str,
    conversation: list[dict[str, str]],
) -> CoachingReply:
    """Submit one question and validate the evidence-grounded response."""

    payload = authenticated_api_client(api_url).ask_coach(
        message=message,
        conversation=conversation[-8:],
    )
    return CoachingReply.model_validate(payload)


def authenticated_api_client(api_url: str) -> RunCoachApiClient:
    """Build an API client from the bearer token held only in Streamlit session memory."""

    access_token = st.session_state.get(SESSION_TOKEN_KEY)
    if not isinstance(access_token, str) or not access_token:
        raise DashboardApiError("Sign in to continue.")
    return RunCoachApiClient(api_url, access_token=access_token)


def load_current_account(api_url: str) -> CurrentAccount:
    """Validate the current session and return its athlete display context."""

    return CurrentAccount.model_validate(authenticated_api_client(api_url).get_current_account())


def load_onboarding_account(api_url: str) -> CurrentAccount:
    """Validate a session that may still require its Strava history."""

    return CurrentAccount.model_validate(authenticated_api_client(api_url).get_onboarding_account())


def upload_onboarding_archive(
    api_url: str,
    *,
    filename: str,
    content: bytes,
) -> OnboardingResult:
    """Upload and validate the required Strava history ZIP."""

    payload = authenticated_api_client(api_url).upload_strava_archive(
        filename=filename,
        content=content,
    )
    return OnboardingResult.model_validate(payload)


def render_login(api_url: str) -> None:
    """Render sign-in and required-history registration without retaining passwords."""

    st.title("RunCoach AI")
    st.caption("Sign in, or create an evidence-backed plan from your Strava history.")
    sign_in_tab, signup_tab = st.tabs(("Sign in", "Create account"))

    with sign_in_tab:
        with st.form("account_login"):
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                "Sign in",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            try:
                session = LoginSession.model_validate(
                    RunCoachApiClient(api_url).login(email=email, password=password)
                )
            except (DashboardApiError, ValidationError, ValueError):
                st.error("Sign-in failed. Check your email and password.")
            else:
                establish_authenticated_session(session.access_token)
                st.rerun()

    with signup_tab:
        st.info(
            "The original Strava export ZIP is required. RunCoach imports it privately, "
            "then creates analytics and your first plan."
        )
        today = date.today()
        with st.form("account_signup"):
            display_name = st.text_input("Athlete name")
            signup_email = st.text_input("Account email", autocomplete="email")
            signup_password = st.text_input(
                "Create password",
                type="password",
                autocomplete="new-password",
                help="Use at least 12 characters.",
            )
            confirm_password = st.text_input(
                "Confirm password",
                type="password",
                autocomplete="new-password",
            )
            timezone_name = st.text_input("IANA timezone", value="Africa/Casablanca")

            st.markdown("#### Race goal")
            goal_distance = st.selectbox(
                "Goal distance",
                options=list(StandardDistance),
                format_func=distance_label,
            )
            race_date_value = st.date_input(
                "Goal race date",
                value=today + timedelta(weeks=16),
                min_value=today + timedelta(days=1),
                max_value=date(today.year + 2, 12, 31),
            )
            target_time = st.text_input(
                "Target time (optional)",
                help="Use M:SS or H:MM:SS.",
            )
            days_per_week = st.slider(
                "Planned running days per week",
                min_value=3,
                max_value=7,
                value=5,
            )

            st.markdown("#### One known Strava best effort")
            benchmark_distance = st.selectbox(
                "Benchmark distance",
                options=list(StandardDistance),
                format_func=distance_label,
            )
            benchmark_time = st.text_input(
                "Benchmark time",
                placeholder="For example 41:04 or 3:41:06",
            )
            benchmark_date_value = st.date_input(
                "Benchmark activity date",
                value=today,
                max_value=today,
            )
            benchmark_label = st.selectbox(
                "Benchmark type",
                options=(
                    "verified_race",
                    "verified_time_trial",
                    "verified_max_effort",
                ),
                format_func=lambda value: value.replace("_", " ").title(),
            )
            strava_archive = st.file_uploader(
                "Strava history ZIP (required)",
                type=["zip"],
                help="Upload the original archive from Strava's account export.",
            )
            research_consent = st.checkbox(
                "Allow de-identified features to support future model research",
                value=False,
                help="Optional. Raw activities and route coordinates are never shared.",
            )
            signup_submitted = st.form_submit_button(
                "Create account and plan",
                type="primary",
                use_container_width=True,
            )

        if not signup_submitted:
            return
        if strava_archive is None:
            st.error("A Strava history ZIP is required to create an athlete plan.")
            return
        if signup_password != confirm_password:
            st.error("Passwords do not match.")
            return

        progress = st.status(
            "Creating your athlete account...",
            expanded=True,
        )
        progress.write("Saving your profile, race goal, and benchmark effort.")
        try:
            benchmark_seconds = parse_duration(benchmark_time)
            target_seconds = parse_duration(target_time) if target_time.strip() else None
            if not isinstance(race_date_value, date) or not isinstance(benchmark_date_value, date):
                raise ValueError("Choose one goal date and one benchmark date.")
            registration = LoginSession.model_validate(
                RunCoachApiClient(api_url).register(
                    {
                        "display_name": display_name,
                        "email": signup_email,
                        "password": signup_password,
                        "timezone": timezone_name,
                        "goal_distance": goal_distance.value,
                        "race_date": race_date_value.isoformat(),
                        "target_time_seconds": target_seconds,
                        "days_per_week": days_per_week,
                        "benchmark_distance": benchmark_distance.value,
                        "benchmark_elapsed_time_seconds": benchmark_seconds,
                        "benchmark_date": benchmark_date_value.isoformat(),
                        "benchmark_label": benchmark_label,
                        "research_consent": research_consent,
                    }
                )
            )
            establish_authenticated_session(registration.access_token)
            progress.update(
                label="Processing your Strava history...",
                state="running",
            )
            progress.write(
                "Uploading and validating the private ZIP. Large histories can take "
                "several minutes; keep this page open."
            )
            progress.write(
                "Next, RunCoach will calculate your fitness evidence and create your "
                "first training plan."
            )
            upload_onboarding_archive(
                api_url,
                filename=strava_archive.name,
                content=strava_archive.getvalue(),
            )
        except (DashboardApiError, ValidationError, ValueError) as error:
            progress.update(
                label="Setup needs your attention",
                state="error",
                expanded=True,
            )
            st.error(str(error))
            if SESSION_TOKEN_KEY in st.session_state:
                st.info("Your account is saved. Reload this page to retry the Strava ZIP.")
            return

        progress.update(
            label="Your analytics and training plan are ready",
            state="complete",
            expanded=False,
        )
        st.success("Your Strava history, analytics, and first training plan are ready.")
        st.rerun()


def render_pending_onboarding(api_url: str, account: CurrentAccount) -> None:
    """Allow a pending athlete to retry the required private ZIP import."""

    athlete_name = account.athlete.display_name or "Athlete"
    st.title(f"Finish setting up {athlete_name}")
    st.warning(
        "Your account is saved, but coaching stays locked until a valid Strava history ZIP "
        "creates the initial analytics and plan."
    )
    st.caption(f"Current onboarding status: {account.athlete.onboarding_status}")
    archive = st.file_uploader(
        "Strava history ZIP",
        type=["zip"],
        help="Retry with the original Strava account export ZIP.",
    )
    if st.button("Import history and create plan", type="primary", disabled=archive is None):
        if archive is None:
            return
        progress = st.status(
            "Processing your Strava history...",
            expanded=True,
        )
        progress.write(
            "Uploading and validating the private ZIP. Large histories can take several "
            "minutes; keep this page open."
        )
        progress.write(
            "RunCoach will then calculate your fitness evidence and create your first plan."
        )
        try:
            completed = upload_onboarding_archive(
                api_url,
                filename=archive.name,
                content=archive.getvalue(),
            )
        except (DashboardApiError, ValidationError, ValueError) as error:
            progress.update(
                label="Import needs your attention",
                state="error",
                expanded=True,
            )
            st.error(str(error))
            return
        progress.update(
            label="Your analytics and training plan are ready",
            state="complete",
            expanded=False,
        )
        st.success(f"Ready: {completed.canonical_runs} runs imported and the first plan created.")
        st.rerun()

    if st.button("Sign out", key="pending_sign_out"):
        with suppress(DashboardApiError, ValueError):
            authenticated_api_client(api_url).logout()
        clear_authenticated_session()
        st.rerun()


def upload_title_from_filename(filename: str) -> str:
    """Suggest an editable Strava title without exposing a local path."""

    title = filename
    if title.casefold().endswith(".fit.gz"):
        title = title[:-7]
    elif title.casefold().endswith(".fit"):
        title = title[:-4]
    title = re.sub(r" \(\d+\)$", "", title)
    return re.sub(r"_+", " ", title).strip()


def format_pace(seconds_per_km: float | None) -> str:
    """Format seconds per kilometre as a display-only pace value."""

    if seconds_per_km is None:
        return "Unavailable"

    total_seconds = round(seconds_per_km)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d} /km"


def format_optional(value: float | None, decimals: int = 1) -> str:
    """Format an optional numeric value without inventing data."""

    if value is None:
        return "Unavailable"
    return f"{value:.{decimals}f}"


def format_duration(seconds: float) -> str:
    """Format a positive duration as MM:SS or H:MM:SS."""

    total_seconds = round(seconds)
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, remaining_seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def parse_duration(value: str) -> float:
    """Parse M:SS or H:MM:SS user input into seconds."""

    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Target time must use M:SS or H:MM:SS.")
    try:
        numbers = tuple(int(part) for part in parts)
    except ValueError as error:
        raise ValueError("Target time must contain only whole numbers.") from error
    if any(number < 0 for number in numbers) or numbers[-1] >= 60:
        raise ValueError("Target time contains an invalid value.")
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
        if minutes >= 60:
            raise ValueError("Target time contains an invalid value.")
    else:
        hours = 0
        minutes, seconds = numbers
    total_seconds = hours * 3_600 + minutes * 60 + seconds
    if total_seconds <= 0:
        raise ValueError("Target time must be greater than zero.")
    return float(total_seconds)


def distance_label(distance: StandardDistance) -> str:
    """Return the user-facing label for one supported race distance."""

    return DISTANCE_LABELS[distance]


def weekly_frame(trends: AnalyticsTrends) -> pd.DataFrame:
    """Create a presentation frame from validated weekly results."""

    records: list[dict[str, object]] = []

    for week in trends.weekly_training:
        pace_minutes = (
            week.weighted_pace_seconds_per_km / 60
            if week.weighted_pace_seconds_per_km is not None
            else None
        )
        records.append(
            {
                "week_start": week.week_start,
                "week_end": week.week_end,
                "runs": week.runs,
                "distance_km": week.distance_km,
                "moving_hours": week.moving_hours,
                "duration_load_minutes": week.duration_load_minutes,
                "pace_min_per_km": pace_minutes,
                "pace_display": format_pace(week.weighted_pace_seconds_per_km),
                "elevation_gain_m": week.elevation_gain_m,
                "heart_rate_load_activities": (week.heart_rate_load_activities),
                "edwards_trimp": week.edwards_trimp,
            }
        )

    return pd.DataFrame.from_records(records)


def daily_workload_frame(trends: AnalyticsTrends) -> pd.DataFrame:
    """Create a presentation frame from validated workload states."""

    records = [
        {
            "local_date": snapshot.local_date,
            "daily_load": snapshot.daily_load,
            "acute_load": snapshot.acute_load,
            "chronic_load": snapshot.chronic_load,
            "form_index": snapshot.form_index,
            "coverage_pct": snapshot.coverage_pct,
        }
        for snapshot in trends.daily_workload
    ]
    return pd.DataFrame.from_records(records)


def render_weekly_volume(frame: pd.DataFrame) -> None:
    """Render weekly distance and elevation charts."""

    distance_chart = px.bar(
        frame,
        x="week_start",
        y="distance_km",
        custom_data=["week_end", "runs", "moving_hours"],
        labels={
            "week_start": "Week starting",
            "distance_km": "Distance (km)",
        },
        color_discrete_sequence=["#ff5a5f"],
    )
    distance_chart.update_traces(
        hovertemplate=(
            "Week: %{x}<br>"
            "Distance: %{y:.1f} km<br>"
            "Runs: %{customdata[1]}<br>"
            "Moving time: %{customdata[2]:.1f} h"
            "<extra></extra>"
        )
    )
    distance_chart.update_layout(
        title="Weekly running distance",
        bargap=0.22,
        hovermode="x unified",
    )
    st.plotly_chart(
        distance_chart,
        width="stretch",
        config=CHART_CONFIG,
    )

    left_chart, right_chart = st.columns(2)

    with left_chart:
        pace_frame = frame.dropna(subset=["pace_min_per_km"])
        pace_chart = px.line(
            pace_frame,
            x="week_start",
            y="pace_min_per_km",
            markers=True,
            labels={
                "week_start": "Week starting",
                "pace_min_per_km": "Weighted pace (min/km)",
            },
            color_discrete_sequence=["#2f80ed"],
        )
        pace_chart.update_layout(title="Weighted average pace")
        st.plotly_chart(
            pace_chart,
            width="stretch",
            config=CHART_CONFIG,
        )

    with right_chart:
        elevation_frame = frame.dropna(subset=["elevation_gain_m"])
        elevation_chart = px.bar(
            elevation_frame,
            x="week_start",
            y="elevation_gain_m",
            labels={
                "week_start": "Week starting",
                "elevation_gain_m": "Elevation gain (m)",
            },
            color_discrete_sequence=["#27ae60"],
        )
        elevation_chart.update_layout(title="Weekly elevation gain")
        st.plotly_chart(
            elevation_chart,
            width="stretch",
            config=CHART_CONFIG,
        )


def render_workload(frame: pd.DataFrame) -> None:
    """Render deterministic acute, chronic, and form trends."""

    workload_chart = go.Figure()

    workload_chart.add_trace(
        go.Scatter(
            x=frame["local_date"],
            y=frame["acute_load"],
            mode="lines",
            name="Acute load (7-day)",
            line={"color": "#f2994a", "width": 2},
        )
    )
    workload_chart.add_trace(
        go.Scatter(
            x=frame["local_date"],
            y=frame["chronic_load"],
            mode="lines",
            name="Chronic load (42-day)",
            line={"color": "#2f80ed", "width": 3},
        )
    )
    workload_chart.add_trace(
        go.Scatter(
            x=frame["local_date"],
            y=frame["form_index"],
            mode="lines",
            name="Form index",
            line={"color": "#27ae60", "width": 2},
        )
    )
    workload_chart.add_hline(
        y=0,
        line_width=1,
        line_dash="dot",
        line_color="#828282",
    )
    workload_chart.update_layout(
        title="Fitness, fatigue, and form indicators",
        xaxis_title="Date",
        yaxis_title="Duration-load minutes",
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.12},
    )

    st.plotly_chart(
        workload_chart,
        width="stretch",
        config=CHART_CONFIG,
    )
    st.caption(
        "These are deterministic modeled indicators, not direct "
        "physiological measurements or medical assessments."
    )


def render_sensor_coverage(overview: AnalyticsOverview) -> None:
    """Render sensor availability without treating missingness as zero."""

    coverage = overview.sensor_coverage
    heart_rate, gps, cadence = st.columns(3)

    with heart_rate:
        st.metric(
            "Heart-rate coverage",
            f"{coverage.average_heart_rate_coverage_pct:.1f}%",
        )
        st.progress(coverage.average_heart_rate_coverage_pct / 100)

    with gps:
        st.metric(
            "GPS coverage",
            f"{coverage.average_gps_coverage_pct:.1f}%",
        )
        st.progress(coverage.average_gps_coverage_pct / 100)

    with cadence:
        st.metric(
            "Cadence coverage",
            f"{coverage.average_cadence_coverage_pct:.1f}%",
        )
        st.progress(coverage.average_cadence_coverage_pct / 100)

    st.info(
        f"Heart-rate load is available for "
        f"{coverage.activities_with_heart_rate_load} of "
        f"{coverage.activities_with_metrics} activities. Historical "
        f"missing sensor data remains unavailable rather than being "
        f"imputed as zero."
    )


def render_performance(performance: PerformanceOverview, api_url: str) -> None:
    """Render verified PB evidence and experimental current-fitness estimates."""

    st.subheader("Verified personal bests")
    record_columns = st.columns(len(performance.personal_bests))

    for column, personal_best in zip(
        record_columns,
        performance.personal_bests,
        strict=True,
    ):
        column.metric(
            distance_label(personal_best.distance),
            format_duration(personal_best.elapsed_time_seconds),
        )
        column.caption(
            f"{personal_best.achieved_at.date().isoformat()} · "
            f"{personal_best.verification_status.value.replace('_', ' ')}"
        )

    st.subheader("Training-informed race prediction")
    st.warning(
        "Fitness potential estimates what current ability could support on a flat course in "
        "good conditions. Race readiness also accounts for distance-specific preparation. "
        "Both remain experimental until chronological validation is complete."
    )
    fitness = performance.current_fitness
    status, anchor, evidence = st.columns(3)
    status.metric(
        "Model status",
        (
            "Experimental"
            if performance.prediction_status == "experimental_not_validated"
            else performance.prediction_status.replace("_", " ").title()
        ),
    )
    if performance.prediction_status == "experimental_not_validated":
        status.caption("Chronological validation pending")
    anchor.metric(
        "Current anchor",
        f"{distance_label(fitness.anchor.distance)} · "
        f"{format_duration(fitness.anchor.elapsed_time_seconds)}",
    )
    evidence.metric("Training history", f"{fitness.training.runs_365d} runs / 365 days")

    estimates = pd.DataFrame.from_records(
        [
            {
                "Distance": distance_label(estimate.distance),
                "Fitness potential": format_duration(estimate.fitness_potential_time_seconds),
                "Race readiness": format_duration(estimate.race_readiness_time_seconds),
                "Readiness range": (
                    f"{format_duration(estimate.optimistic_time_seconds)} to "
                    f"{format_duration(estimate.conservative_time_seconds)}"
                ),
                "Readiness pace": format_pace(estimate.race_readiness_pace_seconds_per_km),
                "Preparation": f"{estimate.preparation_score:.0%}",
                "Best available evidence": (
                    format_duration(estimate.current_pb_seconds)
                    if estimate.current_pb_seconds is not None
                    else "Unavailable"
                ),
                "Confidence": estimate.confidence.title(),
            }
            for estimate in fitness.estimates
        ]
    )
    st.dataframe(estimates, hide_index=True, width="stretch")

    st.caption(
        f"Evidence through {fitness.as_of_date.isoformat()}: "
        f"{fitness.training.distance_28d_km:.1f} km / 28 days, "
        f"{fitness.training.distance_84d_km:.1f} km / 84 days, "
        f"{fitness.training.distance_168d_km:.1f} km / 168 days, and "
        f"{fitness.training.distance_365d_km:.1f} km / 365 days. "
        f"Longest run in 84 days: "
        f"{format_optional(fitness.training.longest_run_84d_km)} km."
    )
    st.caption(
        "OpenAI's role is to explain a validated model's evidence, uncertainty, and practical "
        "meaning. Numeric race times remain the output of versioned, tested code."
    )
    st.caption(
        "Verified PB cards remain athlete-confirmed. Best available evidence may be a faster "
        "provisional effort derived from imported Strava trackpoints."
    )
    st.info(" ".join(performance.limitations))
    with st.expander("View performance calculation provenance"):
        st.code(
            "\n".join(
                [f"Prediction status: {performance.prediction_status}"]
                + [f"Algorithm: {performance.prediction_method}"]
                + [f"Evidence date: {fitness.as_of_date.isoformat()}"]
                + [f"Anchor capacity factor: {fitness.anchor_capacity_factor:.6f}"]
                + [f"Anchor improvement factor: {fitness.anchor_improvement_factor:.6f}"]
                + [f"Anchor session: {fitness.anchor.session_kind.value}"]
                + [f"Interpretation role: {performance.interpretation_role}"]
                + [
                    f"{distance_label(personal_best.distance)} PB evidence: "
                    f"{personal_best.personal_best_id} ({personal_best.algorithm_version})"
                    for personal_best in performance.personal_bests
                ]
            ),
            language="text",
        )
    render_performance_label_audit(api_url)


def render_performance_label_audit(api_url: str) -> None:
    """Render one-at-a-time private labeling with immediate validation feedback."""

    st.divider()
    st.subheader("Improve prediction accuracy")
    st.caption(
        "Review standard-distance efforts one at a time. Training runs should be excluded; "
        "only races, time trials, and genuine maximal efforts become model labels. Decisions "
        "remain in the ignored private data directory."
    )
    try:
        audit = PerformanceLabelAudit.model_validate(
            authenticated_api_client(api_url).get_performance_label_audit(limit=1)
        )
    except (DashboardApiError, ValidationError, ValueError) as error:
        st.info(
            "The private label queue is not available yet. Run "
            "`uv run python -m runcoach.cli.export_performance_dataset` once, then refresh."
        )
        st.caption(str(error))
        return

    reviewed = audit.verified_rows + audit.excluded_rows
    reviewed_column, verified_column, validation_column = st.columns(3)
    reviewed_column.metric("Reviewed", f"{reviewed} / {audit.total_rows}")
    verified_column.metric("Verified efforts", audit.verified_rows)
    validation_column.metric(
        "Chronological targets",
        audit.validation.chronological_targets,
    )

    if audit.validation.candidate_model_eligible:
        st.success("The reviewed dataset now meets the minimum evaluation sample requirements.")
    else:
        st.warning(" ".join(audit.validation.eligibility_reasons))

    if audit.validation.aggregate_metrics:
        validation_table = pd.DataFrame.from_records(
            [
                {
                    "Baseline": metric.baseline.replace("_", " ").title(),
                    "Predictions": metric.predictions,
                    "MAE": format_duration(metric.mean_absolute_error_seconds),
                    "Median error": format_duration(metric.median_absolute_error_seconds),
                    "MAPE": f"{metric.mean_absolute_percentage_error:.1f}%",
                    "Bias (seconds)": round(metric.mean_signed_error_seconds, 1),
                }
                for metric in audit.validation.aggregate_metrics
            ]
        )
        st.dataframe(validation_table, hide_index=True, width="stretch")

    if not audit.candidates:
        st.success("All candidate performances have been reviewed.")
        return

    candidate = audit.candidates[0]
    session_description = candidate.session_kind.value.replace("_", " ").title()
    st.markdown(f"#### {distance_label(candidate.matched_distance)} candidate")
    st.write(
        f"**{candidate.achieved_at.date().isoformat()} · {session_description} session**  \n"
        f"Recorded {format_duration(candidate.recorded_elapsed_time_seconds)} over "
        f"{candidate.measured_distance_m / 1_000:.3f} km "
        f"({candidate.distance_deviation_pct:.2f}% from the standard distance)."
    )

    choices = {
        "Verified race": "verified_race",
        "Verified time trial": "verified_time_trial",
        "Verified max effort": "verified_max_effort",
        "Exclude: training or non-maximal effort": None,
    }
    with st.form("performance_label_review", clear_on_submit=False):
        selected_choice = str(st.radio("Decision", tuple(choices), horizontal=True))
        verified_time = st.text_input(
            "Verified time",
            value=format_duration(candidate.recorded_elapsed_time_seconds),
            help="Use M:SS or H:MM:SS. Edit this when an official result differs from FIT time.",
        )
        notes = st.text_area(
            "Review notes (optional)",
            max_chars=500,
            placeholder="For example: official chip time, solo time trial, or training run.",
        )
        submitted = st.form_submit_button("Save decision and revalidate", type="primary")

    if not submitted:
        return

    review_label = choices[selected_choice]
    review_status = "verified" if review_label is not None else "excluded"
    try:
        elapsed_seconds = parse_duration(verified_time) if review_label is not None else None
        updated = PerformanceLabelAudit.model_validate(
            authenticated_api_client(api_url).review_performance_candidate(
                review_token=candidate.review_token,
                review_status=review_status,
                review_label=review_label,
                verified_elapsed_time_seconds=elapsed_seconds,
                review_notes=notes.strip() or None,
            )
        )
    except (DashboardApiError, ValidationError, ValueError) as error:
        st.error("The label decision could not be saved.")
        st.caption(str(error))
        return

    st.success(
        f"Decision saved. {updated.unreviewed_rows} candidate(s) remain; chronological "
        "validation has been refreshed."
    )
    st.cache_data.clear()
    st.rerun()


def render_weekly_table(frame: pd.DataFrame) -> None:
    """Render a concise auditable weekly data table."""

    table = frame[
        [
            "week_start",
            "week_end",
            "runs",
            "distance_km",
            "moving_hours",
            "pace_display",
            "elevation_gain_m",
            "heart_rate_load_activities",
            "edwards_trimp",
        ]
    ].rename(
        columns={
            "week_start": "Week start",
            "week_end": "Week end",
            "runs": "Runs",
            "distance_km": "Distance (km)",
            "moving_hours": "Moving hours",
            "pace_display": "Weighted pace",
            "elevation_gain_m": "Elevation (m)",
            "heart_rate_load_activities": "HR-load runs",
            "edwards_trimp": "Edwards TRIMP",
        }
    )

    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
    )


def render_training_plan(plan: TrainingPlanPreview) -> None:
    """Render one goal assessment, first week, and full progression outline."""

    st.subheader("Personalized training-plan preview")
    st.caption(
        "The preview is recalculated from current fitness and training evidence whenever "
        "you change the goal. Save it to retain an auditable plan that can be refreshed "
        "after new activities are imported."
    )
    status, readiness, target, horizon = st.columns(4)
    status.metric("Goal assessment", plan.goal_status.value.replace("_", " ").title())
    readiness.metric("Current readiness", format_duration(plan.current_readiness_seconds))
    target.metric("Recommended target", format_duration(plan.recommended_target_seconds))
    horizon.metric("Plan horizon", f"{plan.weeks_to_race} weeks")

    st.markdown("#### First training week")
    first_week = pd.DataFrame.from_records(
        [
            {
                "Date": session.scheduled_date,
                "Session": session.title,
                "Type": session.kind.value.title(),
                "Distance": f"{session.distance_km:.1f} km",
                "Pace": (
                    "Unavailable"
                    if session.pace is None
                    else (
                        f"{format_pace(session.pace.faster_seconds_per_km)} to "
                        f"{format_pace(session.pace.slower_seconds_per_km)}"
                    )
                ),
                "Purpose": session.purpose,
            }
            for session in plan.first_week
        ]
    )
    st.dataframe(first_week, hide_index=True, width="stretch")

    st.markdown("#### Weekly progression")
    outline = pd.DataFrame.from_records(
        [
            {
                "Week": week.week_number,
                "Start": week.start_date,
                "End": week.end_date,
                "Phase": week.phase.value.title(),
                "Target distance": f"{week.target_distance_km:.1f} km",
                "Long run": f"{week.long_run_km:.1f} km",
                "Quality focus": week.quality_focus,
            }
            for week in plan.weekly_outline
        ]
    )
    st.dataframe(outline, hide_index=True, width="stretch")

    st.info(" ".join(plan.rationale))
    st.warning("Guardrails: " + " ".join(plan.guardrails))
    with st.expander("View plan provenance"):
        st.code(
            "\n".join(
                (
                    f"Algorithm: {plan.algorithm_version}",
                    f"Evidence date: {plan.as_of_date.isoformat()}",
                    f"Plan start: {plan.plan_start_date.isoformat()}",
                    f"Recent weekly distance: {plan.recent_weekly_distance_km:.1f} km",
                    f"Preparation score: {plan.current_preparation_score:.3f}",
                    f"Preview status: {plan.status}",
                )
            ),
            language="text",
        )


def render_plan_tracking(tracking: ActivePlanTracking) -> None:
    """Render plan-to-actual progress and explain versioned adaptations."""

    st.markdown("#### Active plan tracking")
    status_column, version_column, weeks_column, adherence_column = st.columns(4)
    status_column.metric("Plan status", tracking.status.replace("_", " ").title())
    version_column.metric("Active version", f"v{tracking.active_version}")
    weeks_column.metric(
        "Completed weeks",
        f"{tracking.completed_weeks} / {tracking.total_weeks}",
    )
    adherence_column.metric(
        "Distance adherence",
        ("Not started" if tracking.adherence_pct is None else f"{tracking.adherence_pct:.0f}%"),
    )

    if tracking.status == "not_started":
        days_until_start = (tracking.plan_start_date - tracking.as_of_date).days
        st.info(
            f"The active plan starts {tracking.plan_start_date.isoformat()} "
            f"({days_until_start} day(s) after the latest calculated evidence)."
        )
    else:
        st.caption(
            f"Through {tracking.as_of_date.isoformat()}: "
            f"{tracking.actual_distance_to_date_km:.1f} km completed against "
            f"{tracking.planned_distance_to_date_km:.1f} km planned to date."
        )

    st.info(tracking.recommendation)
    st.markdown("##### Prescribed session matching")
    session_table = pd.DataFrame.from_records(
        [
            {
                "Scheduled": session.scheduled_date,
                "Prescription": session.title,
                "Type": session.kind.title(),
                "Target": f"{session.target_distance_km:.1f} km",
                "Status": session.status.title(),
                "Matched run": session.matched_activity_name or "—",
                "Actual": (
                    "—"
                    if session.actual_distance_km is None
                    else f"{session.actual_distance_km:.1f} km"
                ),
                "Average pace": format_pace(session.actual_pace_seconds_per_km),
                "Pace check": session.pace_status.replace("_", " ").title(),
            }
            for session in tracking.sessions
        ]
    )
    st.dataframe(session_table, hide_index=True, width="stretch")

    st.markdown("##### Weekly adherence")
    progress_table = pd.DataFrame.from_records(
        [
            {
                "Week": week.week_number,
                "Start": week.start_date,
                "Status": week.status.replace("_", " ").title(),
                "Phase": week.phase.title(),
                "Target": f"{week.target_distance_km:.1f} km",
                "Actual": f"{week.actual_distance_km:.1f} km",
                "Distance completion": f"{week.distance_completion_pct:.0f}%",
                "Long-run target": f"{week.target_long_run_km:.1f} km",
                "Longest run": f"{week.actual_long_run_km:.1f} km",
            }
            for week in tracking.weeks
        ]
    )
    st.dataframe(progress_table, hide_index=True, width="stretch")

    st.markdown("#### Adaptation history")
    chronological_versions = sorted(tracking.versions, key=lambda version: version.version)
    previous_weekly_km: float | None = None
    version_records: list[dict[str, object]] = []
    for version in chronological_versions:
        change = (
            None
            if previous_weekly_km is None
            else version.recent_weekly_distance_km - previous_weekly_km
        )
        version_records.append(
            {
                "Version": f"v{version.version}",
                "Status": version.status.title(),
                "Evidence through": version.evidence_as_of_date,
                "Recent weekly volume": f"{version.recent_weekly_distance_km:.1f} km",
                "Evidence change": "Initial" if change is None else f"{change:+.1f} km",
                "First week": f"{version.first_week_target_km:.1f} km",
                "Peak week": f"{version.peak_week_target_km:.1f} km",
                "Peak long run": f"{version.peak_long_run_km:.1f} km",
            }
        )
        previous_weekly_km = version.recent_weekly_distance_km
    st.dataframe(
        pd.DataFrame.from_records(reversed(version_records)),
        hide_index=True,
        width="stretch",
    )


def render_conversational_coach(api_url: str) -> None:
    """Render a session-local conversation grounded in current RunCoach evidence."""

    st.subheader("Ask RunCoach")
    st.caption(
        "Ask about current fitness, your marathon goal, workload, plan adherence, or the next "
        "session. Calculations stay in versioned RunCoach code; the language model only explains "
        "the resulting evidence."
    )
    if st.button("Clear coach conversation", key="clear_coach_conversation"):
        st.session_state[COACH_MESSAGES_KEY] = []
        st.rerun()
    history_value = st.session_state.get(COACH_MESSAGES_KEY, [])
    history: list[dict[str, object]] = history_value if isinstance(history_value, list) else []

    if not history:
        history = [
            {
                "role": "assistant",
                "content": (
                    "Ask me what to run next, whether your marathon target is supported, how your "
                    "current fitness is trending, or what the latest workload means."
                ),
                "evidence_ids": (),
                "limitations": (),
                "mode": "deterministic",
            }
        ]
        st.session_state[COACH_MESSAGES_KEY] = history

    for message in history:
        role = str(message.get("role", "assistant"))
        with st.chat_message(role):
            st.markdown(str(message.get("content", "")))
            evidence_ids = message.get("evidence_ids", ())
            if isinstance(evidence_ids, (list, tuple)) and evidence_ids:
                st.caption("Evidence: " + ", ".join(str(item) for item in evidence_ids))
                response_mode = str(message.get("mode", "deterministic"))
                mode_label = (
                    "OpenAI explanation over RunCoach evidence"
                    if response_mode == "openai"
                    else "Deterministic RunCoach fallback"
                )
                st.caption(f"Mode: {mode_label}")
            limitations = message.get("limitations", ())
            if isinstance(limitations, (list, tuple)) and limitations:
                with st.expander("Limitations"):
                    for limitation in limitations:
                        st.write(f"- {limitation}")

    question = st.chat_input("Ask about your running and active plan")
    if question:
        prior_turns = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ][-8:]
        try:
            reply = ask_coach(
                api_url,
                message=question,
                conversation=prior_turns,
            )
        except (DashboardApiError, ValidationError, ValueError) as error:
            st.error("RunCoach could not answer this question.")
            st.caption(str(error))
            return

        history.extend(
            (
                {"role": "user", "content": question},
                {
                    "role": "assistant",
                    "content": reply.answer,
                    "evidence_ids": reply.evidence_ids,
                    "limitations": reply.limitations,
                    "mode": reply.mode,
                },
            )
        )
        st.session_state[COACH_MESSAGES_KEY] = history[-17:]
        st.rerun()


def main() -> None:
    """Render the RunCoach dashboard."""

    st.set_page_config(
        page_title="RunCoach AI",
        page_icon="🏃",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    api_url = os.getenv("RUNCOACH_API_URL", DEFAULT_API_URL)
    if SESSION_TOKEN_KEY not in st.session_state:
        render_login(api_url)
        return

    try:
        onboarding_account = load_onboarding_account(api_url)
    except (DashboardApiError, ValidationError, ValueError):
        clear_authenticated_session()
        st.error("Your session expired. Sign in again.")
        render_login(api_url)
        return

    access_token = st.session_state.get(SESSION_TOKEN_KEY)
    if isinstance(access_token, str):
        bind_private_state_to_session(
            cast(MutableMapping[str, object], st.session_state),
            access_token,
        )

    if onboarding_account.athlete.onboarding_status != "ready":
        render_pending_onboarding(api_url, onboarding_account)
        return

    try:
        current_account = load_current_account(api_url)
    except (DashboardApiError, ValidationError, ValueError):
        clear_authenticated_session()
        st.error("Your session expired. Sign in again.")
        render_login(api_url)
        return

    st.title("RunCoach AI")
    st.caption(
        "Evidence-backed running analytics calculated by deterministic, versioned pipelines."
    )

    with st.sidebar:
        st.header("Dashboard controls")
        athlete_name = current_account.athlete.display_name or "Athlete"
        st.success(f"Signed in as {athlete_name}")
        if st.button("Sign out", use_container_width=True):
            with suppress(DashboardApiError, ValueError):
                authenticated_api_client(api_url).logout()
            clear_authenticated_session()
            st.rerun()
        selected_weeks = st.slider(
            "Training history",
            min_value=4,
            max_value=52,
            value=12,
            step=4,
            format="%d weeks",
        )

        if st.button("Refresh calculated data", use_container_width=True):
            st.rerun()

        st.divider()
        st.subheader("Add a Strava run")
        uploaded_run = st.file_uploader(
            "FIT activity",
            type=["fit", "gz"],
            help="Upload one Strava .fit or .fit.gz activity. The temporary file is deleted.",
        )
        if uploaded_run is None:
            st.caption("Choose a FIT file to import it and update coaching in one step.")
        else:
            run_title = st.text_input(
                "Run title",
                value=upload_title_from_filename(uploaded_run.name),
                key=f"run_title_{uploaded_run.name}",
                help="Edit this so RunCoach can recognize easy, tempo, hills, long, or race work.",
            )
            if st.button(
                "Upload and update coaching",
                type="primary",
                use_container_width=True,
            ):
                try:
                    upload_result = upload_run(
                        api_url,
                        filename=uploaded_run.name,
                        title=run_title,
                        content=uploaded_run.getvalue(),
                    )
                    if upload_result.status == "duplicate":
                        st.info("This run was already imported; coaching was refreshed.")
                    else:
                        distance = upload_result.activity.distance_km
                        distance_text = (
                            "distance unavailable" if distance is None else f"{distance:.1f} km"
                        )
                        st.success(
                            f"Added {upload_result.activity.title} ({distance_text}) "
                            "and updated coaching."
                        )
                    st.caption(upload_result.tracking.recommendation)
                except (DashboardApiError, ValidationError, ValueError) as error:
                    st.error("The run could not be imported.")
                    st.caption(str(error))

        st.divider()
        st.caption(
            "The dashboard reads calculated aggregates through FastAPI. "
            "It does not access raw activity files or PostgreSQL directly."
        )

    try:
        overview, trends, performance = load_dashboard_data(api_url, selected_weeks)
    except (DashboardApiError, ValidationError, ValueError) as error:
        st.error("Dashboard data could not be loaded.")
        st.caption(str(error))
        st.stop()

    stale_days = (overview.as_of_date - overview.data_end_date).days

    metric_columns = st.columns(5)
    metric_columns[0].metric("Total runs", f"{overview.total_runs:,}")
    metric_columns[1].metric(
        "Total distance",
        f"{overview.total_distance_km:,.1f} km",
    )
    metric_columns[2].metric(
        "Moving time",
        f"{overview.total_moving_hours:,.1f} h",
    )
    metric_columns[3].metric(
        "Last 7 days",
        f"{overview.last_7_days.distance_km:.1f} km",
        help=f"{overview.last_7_days.runs} runs",
    )
    metric_columns[4].metric(
        "Current form index",
        format_optional(overview.workload.form_index),
        help="Chronic load minus acute load.",
    )

    st.caption(
        f"Activity history: {overview.data_start_date.isoformat()} to "
        f"{overview.data_end_date.isoformat()} · Workload calculated "
        f"through {overview.as_of_date.isoformat()} · "
        f"{stale_days} recovery day(s) after the latest recorded run."
    )

    volume_tab, performance_tab, coach_tab, plan_tab, workload_tab, quality_tab = st.tabs(
        [
            "Training volume",
            "Performance",
            "Coach",
            "Training plan",
            "Workload and form",
            "Data coverage",
        ]
    )

    weekly_data = weekly_frame(trends)
    workload_data = daily_workload_frame(trends)

    with volume_tab:
        render_weekly_volume(weekly_data)
        with st.expander("View weekly evidence table"):
            render_weekly_table(weekly_data)

    with performance_tab:
        render_performance(performance, api_url)

    with coach_tab:
        render_conversational_coach(api_url)

    with plan_tab:
        st.subheader("Choose a race goal")
        goal_distance = st.selectbox(
            "Race distance",
            options=tuple(StandardDistance),
            index=3,
            format_func=distance_label,
        )
        goal_estimate = next(
            estimate
            for estimate in performance.current_fitness.estimates
            if estimate.distance is goal_distance
        )
        earliest_goal_date = performance.current_fitness.as_of_date + timedelta(days=21)
        latest_goal_date = performance.current_fitness.as_of_date + timedelta(days=364)
        default_goal_date = performance.current_fitness.as_of_date + timedelta(weeks=12)
        if (
            goal_distance is StandardDistance.MARATHON
            and earliest_goal_date <= NEXT_MARATHON_DATE <= latest_goal_date
        ):
            default_goal_date = NEXT_MARATHON_DATE
        goal_columns = st.columns(3)
        with goal_columns[0]:
            goal_date = st.date_input(
                "Race date",
                value=default_goal_date,
                min_value=earliest_goal_date,
                max_value=latest_goal_date,
                help=(
                    f"Goals can be planned through {latest_goal_date.isoformat()}. "
                    "The next marathon is preselected for 2027-01-31."
                ),
                key=f"race_date_{goal_distance.value}",
            )
        with goal_columns[1]:
            target_text = st.text_input(
                "Target time",
                value=format_duration(goal_estimate.race_readiness_time_seconds),
                help="Use M:SS or H:MM:SS.",
                key=f"target_time_{goal_distance.value}",
            )
        with goal_columns[2]:
            plan_days_per_week = st.slider(
                "Running days per week",
                min_value=3,
                max_value=7,
                value=6,
            )

        try:
            target_seconds = parse_duration(target_text)
            save_column, refresh_column = st.columns(2)
            save_selected = save_column.button(
                "Save as active plan",
                type="primary",
                use_container_width=True,
            )
            refresh_selected = refresh_column.button(
                "Refresh active plan",
                use_container_width=True,
            )
            if save_selected:
                persisted = save_training_plan(
                    api_url,
                    goal_distance,
                    goal_date,
                    target_seconds,
                    plan_days_per_week,
                )
                plan = persisted.preview
                action = "created" if persisted.created else "reused"
                st.success(f"Active plan v{persisted.version} {action} and saved.")
            elif refresh_selected:
                persisted = refresh_active_training_plan(api_url)
                plan = persisted.preview
                action = "created" if persisted.created else "already current"
                st.success(f"Active plan v{persisted.version}: {action}.")
            else:
                plan = load_training_plan(
                    api_url,
                    goal_distance,
                    goal_date,
                    target_seconds,
                    plan_days_per_week,
                )
            render_training_plan(plan)
            try:
                render_plan_tracking(load_active_plan_tracking(api_url))
            except (DashboardApiError, ValidationError) as tracking_error:
                st.caption(f"Active plan tracking is unavailable: {tracking_error}")
        except (DashboardApiError, ValidationError, ValueError) as error:
            st.error("Training plan could not be generated.")
            st.caption(str(error))

    with workload_tab:
        render_workload(workload_data)
        st.write(
            f"Latest acute load: "
            f"**{format_optional(overview.workload.acute_load)}** · "
            f"Latest chronic load: "
            f"**{format_optional(overview.workload.chronic_load)}** · "
            f"Form: **{format_optional(overview.workload.form_index)}**"
        )

    with quality_tab:
        render_sensor_coverage(overview)
        st.subheader("Calculation provenance")
        st.code(
            "\n".join(
                [
                    f"Load method: {overview.workload.load_method}",
                    (f"Daily workload algorithm: {overview.workload.algorithm_version}"),
                    (f"Workload coverage: {overview.workload.coverage_pct:.1f}%"),
                ]
            ),
            language="text",
        )

    st.divider()
    st.caption(
        "RunCoach AI supports coaching decisions but does not diagnose "
        "injury, measure fitness directly, or guarantee race outcomes."
    )


if __name__ == "__main__":
    main()
