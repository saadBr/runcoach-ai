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
]
