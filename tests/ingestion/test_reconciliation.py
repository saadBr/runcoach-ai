"""Tests for deterministic cross-source reconciliation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from runcoach.ingestion import (
    ActivityKind,
    MatchMethod,
    NormalizedActivity,
    SourceFormat,
    SourceProvider,
    SourceReference,
    reconcile_activity_summaries,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
START_TIME = datetime(2026, 4, 1, 6, 30, tzinfo=UTC)


def _activity(
    *,
    provider: SourceProvider,
    source_format: SourceFormat,
    source_id: str,
    activity_kind: ActivityKind,
    start_offset_s: float = 0,
    elapsed_time_s: float = 3600,
    distance_m: float = 10_000,
    name: str | None = None,
    average_heart_rate_bpm: int | None = None,
) -> NormalizedActivity:
    return NormalizedActivity(
        athlete_id=ATHLETE_ID,
        source=SourceReference(
            provider=provider,
            source_format=source_format,
            source_file_name=f"{provider.value}.{source_format.value}",
            content_sha256=("a" if provider is SourceProvider.GARMIN else "b") * 64,
            source_activity_id=source_id,
        ),
        activity_kind=activity_kind,
        provider_activity_type=activity_kind.value,
        name=name,
        start_time_utc=(START_TIME + timedelta(seconds=start_offset_s)),
        elapsed_time_s=elapsed_time_s,
        distance_m=distance_m,
        average_heart_rate_bpm=(average_heart_rate_bpm),
    )


def test_strong_match_uses_garmin_classification_and_metrics() -> None:
    strava = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="strava-1",
        activity_kind=ActivityKind.OTHER,
        name="Synthetic treadmill session",
        elapsed_time_s=3575,
    )
    garmin = _activity(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        source_id="garmin-1",
        activity_kind=ActivityKind.TREADMILL_RUNNING,
        average_heart_rate_bpm=155,
    )

    result = reconcile_activity_summaries(
        strava_activities=(strava,),
        garmin_activities=(garmin,),
    )

    assert result.findings == ()
    assert len(result.activities) == 1

    reconciled = result.activities[0]
    assert reconciled.match_method is MatchMethod.CROSS_SOURCE_STRONG
    assert reconciled.canonical.activity_kind is ActivityKind.TREADMILL_RUNNING
    assert reconciled.canonical.average_heart_rate_bpm == 155
    assert reconciled.canonical.name == "Synthetic treadmill session"
    assert len(reconciled.representations) == 2


def test_historical_strava_run_is_retained() -> None:
    historical = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="historical-1",
        activity_kind=ActivityKind.RUNNING,
    )

    result = reconcile_activity_summaries(
        strava_activities=(historical,),
        garmin_activities=(),
    )

    assert len(result.activities) == 1
    assert result.activities[0].match_method is MatchMethod.SINGLE_SOURCE


def test_non_running_records_are_excluded() -> None:
    strava_other = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="strava-other",
        activity_kind=ActivityKind.OTHER,
    )
    garmin_other = _activity(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        source_id="garmin-other",
        activity_kind=ActivityKind.OTHER,
    )

    result = reconcile_activity_summaries(
        strava_activities=(strava_other,),
        garmin_activities=(garmin_other,),
    )

    assert result.activities == ()
    assert result.excluded_strava_representations == 1
    assert result.excluded_garmin_representations == 1


def test_unmatched_garmin_run_is_retained() -> None:
    garmin = _activity(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        source_id="garmin-1",
        activity_kind=ActivityKind.RUNNING,
    )

    result = reconcile_activity_summaries(
        strava_activities=(),
        garmin_activities=(garmin,),
    )

    assert len(result.activities) == 1
    assert result.activities[0].canonical.source.provider is SourceProvider.GARMIN


def test_incompatible_distance_prevents_merge() -> None:
    strava = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="strava-1",
        activity_kind=ActivityKind.RUNNING,
        distance_m=5_000,
    )
    garmin = _activity(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        source_id="garmin-1",
        activity_kind=ActivityKind.RUNNING,
        distance_m=10_000,
    )

    result = reconcile_activity_summaries(
        strava_activities=(strava,),
        garmin_activities=(garmin,),
    )

    assert len(result.activities) == 2
    assert all(activity.match_method is MatchMethod.SINGLE_SOURCE for activity in result.activities)


def test_ambiguous_candidates_are_reported() -> None:
    strava_one = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="strava-1",
        activity_kind=ActivityKind.RUNNING,
    )
    strava_two = _activity(
        provider=SourceProvider.STRAVA,
        source_format=SourceFormat.CSV,
        source_id="strava-2",
        activity_kind=ActivityKind.RUNNING,
        start_offset_s=1,
    )
    garmin = _activity(
        provider=SourceProvider.GARMIN,
        source_format=SourceFormat.JSON,
        source_id="garmin-1",
        activity_kind=ActivityKind.RUNNING,
    )

    result = reconcile_activity_summaries(
        strava_activities=(
            strava_one,
            strava_two,
        ),
        garmin_activities=(garmin,),
    )

    assert len(result.activities) == 3
    assert len(result.findings) == 1
    assert result.findings[0].code == "CROSS_SOURCE_MATCH_AMBIGUOUS"
