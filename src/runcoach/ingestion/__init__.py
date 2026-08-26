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
from runcoach.ingestion.garmin_json import parse_garmin_activity_summaries
from runcoach.ingestion.gpx import parse_gpx_activity
from runcoach.ingestion.reconciliation import (
    FieldProvenance,
    MatchMethod,
    ReconciledActivity,
    ReconciliationResult,
    reconcile_activity_summaries,
)
from runcoach.ingestion.strava_csv import parse_strava_activities_csv

__all__ = [
    "ActivityKind",
    "FieldProvenance",
    "FindingSeverity",
    "MatchMethod",
    "NormalizedActivity",
    "NormalizedLap",
    "NormalizedTrackpoint",
    "ParseResult",
    "ReconciledActivity",
    "ReconciliationResult",
    "SourceFormat",
    "SourceProvider",
    "SourceReference",
    "ValidationFinding",
    "parse_fit_activity",
    "parse_garmin_activity_summaries",
    "parse_gpx_activity",
    "parse_strava_activities_csv",
    "reconcile_activity_summaries",
]
