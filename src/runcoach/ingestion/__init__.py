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
    "parse_strava_activities_csv",
]
