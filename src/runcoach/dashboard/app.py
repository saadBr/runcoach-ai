"""Streamlit analytical dashboard backed exclusively by the RunCoach API."""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

from runcoach.dashboard.api_client import DashboardApiError, RunCoachApiClient
from runcoach.dashboard.schemas import AnalyticsOverview, AnalyticsTrends

DEFAULT_API_URL = "http://localhost:8000"
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


@st.cache_data(ttl=60, show_spinner=False)
def load_dashboard_data(
    api_url: str,
    weeks: int,
) -> tuple[AnalyticsOverview, AnalyticsTrends]:
    """Load and validate one consistent dashboard view."""

    client = RunCoachApiClient(api_url)
    overview = AnalyticsOverview.model_validate(client.get_overview())
    trends = AnalyticsTrends.model_validate(client.get_trends(weeks=weeks))
    return overview, trends


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


def main() -> None:
    """Render the RunCoach dashboard."""

    st.set_page_config(
        page_title="RunCoach AI",
        page_icon="🏃",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("RunCoach AI")
    st.caption(
        "Evidence-backed running analytics calculated by deterministic, versioned pipelines."
    )

    api_url = os.getenv("RUNCOACH_API_URL", DEFAULT_API_URL)

    with st.sidebar:
        st.header("Dashboard controls")
        selected_weeks = st.slider(
            "Training history",
            min_value=4,
            max_value=52,
            value=12,
            step=4,
            format="%d weeks",
        )

        if st.button("Refresh calculated data", use_container_width=True):
            load_dashboard_data.clear()

        st.divider()
        st.caption(
            "The dashboard reads calculated aggregates through FastAPI. "
            "It does not access raw activity files or PostgreSQL directly."
        )

    try:
        overview, trends = load_dashboard_data(api_url, selected_weeks)
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

    volume_tab, workload_tab, quality_tab = st.tabs(
        ["Training volume", "Workload and form", "Data coverage"]
    )

    weekly_data = weekly_frame(trends)
    workload_data = daily_workload_frame(trends)

    with volume_tab:
        render_weekly_volume(weekly_data)
        with st.expander("View weekly evidence table"):
            render_weekly_table(weekly_data)

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
