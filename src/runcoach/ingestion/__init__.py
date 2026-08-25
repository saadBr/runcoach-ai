"""Activity ingestion contracts and adapters."""

from runcoach.ingestion.contracts import (
    ActivityKind,
    FindingSeverity,
    NormalizedActivity,
    NormalizedLap,
    NormalizedTrackpoint,
    ParseResult,
    SourceFormat,
    SourceProvider,
    SourceReference,
    ValidationFinding,
)
from runcoach.ingestion.fit import parse_fit_activity
from runcoach.ingestion.gpx import parse_gpx_activity
from runcoach.ingestion.strava_csv import parse_strava_activities_csv

__all__ = [
    "ActivityKind",
    "FindingSeverity",
    "NormalizedActivity",
    "NormalizedLap",
    "NormalizedTrackpoint",
    "ParseResult",
    "SourceFormat",
    "SourceProvider",
    "SourceReference",
    "ValidationFinding",
    "parse_fit_activity",
    "parse_gpx_activity",
    "parse_strava_activities_csv",
]
