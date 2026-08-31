"""Streamlit dashboard support for RunCoach AI."""

from runcoach.dashboard.api_client import DashboardApiError, RunCoachApiClient
from runcoach.dashboard.schemas import AnalyticsOverview, AnalyticsTrends

__all__ = [
    "AnalyticsOverview",
    "AnalyticsTrends",
    "DashboardApiError",
    "RunCoachApiClient",
]
