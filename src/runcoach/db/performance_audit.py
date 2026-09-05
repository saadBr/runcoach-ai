"""Read-only candidate and leakage-safe feature queries for performance audits."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.activity import ACTIVITY_METRICS_VERSION, DURATION_LOAD_METHOD
from runcoach.analytics.performance import (
    DEFAULT_DISTANCE_TOLERANCE_PCT,
    STANDARD_DISTANCE_AUDIT_VERSION,
    DistanceSample,
    RollingDistanceEffort,
    StandardDistance,
    StandardDistanceEffort,
    calculate_fastest_rolling_distance_effort,
    calculate_standard_distance_effort,
    match_standard_distance,
)
from runcoach.analytics.session_classification import SessionKind, classify_session
from runcoach.analytics.workload import DAILY_LOAD_ALGORITHM_VERSION
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    DailyLoad,
    PersonalBest,
    Trackpoint,
)

PERFORMANCE_FEATURE_DATASET_VERSION: Final = "performance_training_features_v3"
TRAINING_WINDOWS_DAYS: Final = (7, 28, 42, 84, 180, 365)


class PerformanceAuditQueryError(RuntimeError):
    """Raised when a performance audit cannot be produced."""


@dataclass(frozen=True, slots=True)
class PerformanceCandidate:
    """A whole activity near a standard distance and awaiting human review."""

    activity_id: UUID
    achieved_at: datetime
    measured_distance_m: float
    elapsed_time_seconds: float
    elapsed_pace_seconds_per_km: float
    activity_type: str
    verification_status: str
    matched_distance: StandardDistance
    official_distance_m: float
    distance_deviation_m: float
    distance_deviation_pct: float


@dataclass(frozen=True, slots=True)
class PerformanceAudit:
    """Versioned summary of standard-distance candidates for manual labeling."""

    audit_version: str
    distance_tolerance_pct: float
    eligible_activities: int
    candidates: tuple[PerformanceCandidate, ...]


@dataclass(frozen=True, slots=True)
class PerformanceEvidence:
    """Recorded totals plus from-start and fastest rolling distance evidence."""

    activity_id: UUID
    achieved_at: datetime
    recorded_distance_m: float
    recorded_elapsed_time_seconds: float
    distance_samples: int
    target_distance: StandardDistance
    derived_effort: StandardDistanceEffort | None
    rolling_effort: RollingDistanceEffort | None


@dataclass(frozen=True, slots=True)
class TrainingWindowFeatures:
    """Aggregate training evidence strictly preceding a candidate performance."""

    days: int
    runs: int
    distance_km: float
    moving_hours: float
    longest_run_km: float | None
    weighted_pace_seconds_per_km: float | None
    elevation_gain_m: float | None
    activities_with_heart_rate: int
    duration_load_minutes: float
    classified_sessions: int
    quality_sessions: int
    easy_sessions: int
    long_sessions: int
    progressive_sessions: int
    tempo_sessions: int
    hill_sessions: int
    interval_sessions: int
    race_sessions: int
    unclassified_sessions: int


@dataclass(frozen=True, slots=True)
class PerformanceTrainingRow:
    """One candidate label paired with time-safe pre-event features."""

    activity_id: UUID
    activity_name: str | None
    achieved_at: datetime
    matched_distance: StandardDistance
    measured_distance_m: float
    recorded_elapsed_time_seconds: float
    distance_deviation_pct: float
    review_status: str
    review_label: str | None
    verified_elapsed_time_seconds: float | None
    review_notes: str | None
    prior_history_runs: int
    prior_history_days: int
    prior_acute_load: float | None
    prior_chronic_load: float | None
    prior_form_index: float | None
    prior_5k_best_seconds: float | None
    prior_10k_best_seconds: float | None
    prior_half_marathon_best_seconds: float | None
    prior_marathon_best_seconds: float | None
    training_windows: tuple[TrainingWindowFeatures, ...]


@dataclass(frozen=True, slots=True)
class PerformanceTrainingDataset:
    """Private review dataset; unreviewed rows are not valid ML labels."""

    dataset_version: str
    audit_version: str
    leakage_rule: str
    candidate_rows: int
    verified_rows: int
    unreviewed_rows: int
    model_status: str
    rows: tuple[PerformanceTrainingRow, ...]


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _window_features(
    *,
    activities: tuple[Activity, ...],
    metrics_by_activity: dict[UUID, ActivityMetric],
    candidate: Activity,
    days: int,
) -> TrainingWindowFeatures:
    window_start = candidate.local_start_date - timedelta(days=days)
    window = tuple(
        activity
        for activity in activities
        if activity.start_time_utc < candidate.start_time_utc
        and activity.local_start_date >= window_start
    )
    distance_m = sum(float(activity.distance_m) for activity in window)
    moving_time_ms = sum(activity.moving_time_ms for activity in window)
    elevations = tuple(
        float(activity.elevation_gain_m)
        for activity in window
        if activity.elevation_gain_m is not None
    )
    metrics = tuple(
        metrics_by_activity[activity.id]
        for activity in window
        if activity.id in metrics_by_activity
    )
    classifications = tuple(classify_session(activity.name) for activity in window)

    def count_tag(tag: SessionKind) -> int:
        return sum(classification.has_tag(tag) for classification in classifications)

    return TrainingWindowFeatures(
        days=days,
        runs=len(window),
        distance_km=round(distance_m / 1_000, 6),
        moving_hours=round(moving_time_ms / 3_600_000, 6),
        longest_run_km=(
            round(max(float(activity.distance_m) for activity in window) / 1_000, 6)
            if window
            else None
        ),
        weighted_pace_seconds_per_km=(
            round((moving_time_ms / 1_000) / (distance_m / 1_000), 6)
            if moving_time_ms > 0 and distance_m > 0
            else None
        ),
        elevation_gain_m=round(sum(elevations), 6) if elevations else None,
        activities_with_heart_rate=sum(metric.heart_rate_coverage_pct > 0 for metric in metrics),
        duration_load_minutes=round(
            sum(
                float(metric.training_load)
                for metric in metrics
                if metric.training_load is not None
            ),
            6,
        ),
        classified_sessions=sum(
            classification.primary_kind is not SessionKind.UNCLASSIFIED
            for classification in classifications
        ),
        quality_sessions=sum(
            classification.is_quality_session for classification in classifications
        ),
        easy_sessions=count_tag(SessionKind.EASY),
        long_sessions=count_tag(SessionKind.LONG),
        progressive_sessions=count_tag(SessionKind.PROGRESSIVE),
        tempo_sessions=count_tag(SessionKind.TEMPO),
        hill_sessions=count_tag(SessionKind.HILLS),
        interval_sessions=count_tag(SessionKind.INTERVALS),
        race_sessions=count_tag(SessionKind.RACE),
        unclassified_sessions=count_tag(SessionKind.UNCLASSIFIED),
    )


class PerformanceAuditQueryService:
    """Read canonical activities and build human-review performance evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _eligible_activities(self, athlete_id: UUID) -> tuple[Activity, ...]:
        if self._session.get(Athlete, athlete_id) is None:
            raise PerformanceAuditQueryError("The configured athlete does not exist.")

        return tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.sport == "running",
                    Activity.verification_status != "excluded",
                    Activity.distance_m > 0,
                    Activity.elapsed_time_ms > 0,
                )
                .order_by(Activity.start_time_utc, Activity.id)
            )
        )

    def audit(
        self,
        *,
        athlete_id: UUID,
        distance_tolerance_pct: float = DEFAULT_DISTANCE_TOLERANCE_PCT,
    ) -> PerformanceAudit:
        """Return candidates without changing activity types or verification states."""

        activities = self._eligible_activities(athlete_id)
        candidates: list[PerformanceCandidate] = []

        for activity in activities:
            measured_distance_m = float(activity.distance_m)
            match = match_standard_distance(
                measured_distance_m,
                tolerance_pct=distance_tolerance_pct,
            )
            if match is None:
                continue

            elapsed_time_seconds = activity.elapsed_time_ms / 1_000
            candidates.append(
                PerformanceCandidate(
                    activity_id=activity.id,
                    achieved_at=_utc_datetime(activity.start_time_utc),
                    measured_distance_m=measured_distance_m,
                    elapsed_time_seconds=elapsed_time_seconds,
                    elapsed_pace_seconds_per_km=round(
                        elapsed_time_seconds / (measured_distance_m / 1_000),
                        6,
                    ),
                    activity_type=activity.activity_type,
                    verification_status=activity.verification_status,
                    matched_distance=match.distance,
                    official_distance_m=match.official_distance_m,
                    distance_deviation_m=match.deviation_m,
                    distance_deviation_pct=match.deviation_pct,
                )
            )

        return PerformanceAudit(
            audit_version=STANDARD_DISTANCE_AUDIT_VERSION,
            distance_tolerance_pct=distance_tolerance_pct,
            eligible_activities=len(activities),
            candidates=tuple(candidates),
        )

    def training_dataset(
        self,
        *,
        athlete_id: UUID,
        distance_tolerance_pct: float = DEFAULT_DISTANCE_TOLERANCE_PCT,
    ) -> PerformanceTrainingDataset:
        """Pair reviewed labels with features calculated strictly before each event."""

        activities = self._eligible_activities(athlete_id)
        audit = self.audit(
            athlete_id=athlete_id,
            distance_tolerance_pct=distance_tolerance_pct,
        )
        activities_by_id = {activity.id: activity for activity in activities}

        metrics_by_activity: dict[UUID, ActivityMetric] = {}
        metrics = self._session.scalars(
            select(ActivityMetric)
            .join(Activity, Activity.id == ActivityMetric.activity_id)
            .where(
                Activity.athlete_id == athlete_id,
                ActivityMetric.algorithm_version == ACTIVITY_METRICS_VERSION,
                ActivityMetric.load_method == DURATION_LOAD_METHOD,
            )
            .order_by(ActivityMetric.calculated_at, ActivityMetric.id)
        )
        for metric in metrics:
            metrics_by_activity[metric.activity_id] = metric

        workload_by_date = {
            workload.local_date: workload
            for workload in self._session.scalars(
                select(DailyLoad).where(
                    DailyLoad.athlete_id == athlete_id,
                    DailyLoad.load_method == DURATION_LOAD_METHOD,
                    DailyLoad.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION,
                )
            )
        }
        personal_bests = tuple(
            self._session.scalars(
                select(PersonalBest)
                .where(PersonalBest.athlete_id == athlete_id)
                .order_by(PersonalBest.achieved_at, PersonalBest.id)
            )
        )
        verified_by_candidate = {
            (record.activity_id, float(record.distance_m)): record for record in personal_bests
        }

        candidates_by_key = {
            (candidate.activity_id, candidate.matched_distance): candidate
            for candidate in audit.candidates
        }
        for record in personal_bests:
            activity = activities_by_id.get(record.activity_id)
            matched = match_standard_distance(float(record.distance_m), tolerance_pct=0.01)
            if activity is None or matched is None:
                continue

            key = (activity.id, matched.distance)
            if key in candidates_by_key:
                continue

            elapsed_time_seconds = record.elapsed_time_ms / 1_000
            candidates_by_key[key] = PerformanceCandidate(
                activity_id=activity.id,
                achieved_at=_utc_datetime(record.achieved_at),
                measured_distance_m=float(record.distance_m),
                elapsed_time_seconds=elapsed_time_seconds,
                elapsed_pace_seconds_per_km=round(
                    elapsed_time_seconds / (matched.official_distance_m / 1_000),
                    6,
                ),
                activity_type=activity.activity_type,
                verification_status=activity.verification_status,
                matched_distance=matched.distance,
                official_distance_m=matched.official_distance_m,
                distance_deviation_m=matched.deviation_m,
                distance_deviation_pct=matched.deviation_pct,
            )

        candidates = tuple(
            sorted(
                candidates_by_key.values(),
                key=lambda candidate: (
                    candidate.achieved_at,
                    candidate.matched_distance,
                    str(candidate.activity_id),
                ),
            )
        )

        rows: list[PerformanceTrainingRow] = []
        for candidate in candidates:
            activity = activities_by_id[candidate.activity_id]
            prior_activities = tuple(
                prior for prior in activities if prior.start_time_utc < activity.start_time_utc
            )
            previous_day_load = workload_by_date.get(activity.local_start_date - timedelta(days=1))
            verified = verified_by_candidate.get((activity.id, candidate.official_distance_m))
            prior_bests: dict[StandardDistance, float] = {}
            for record in personal_bests:
                if _utc_datetime(record.achieved_at) >= _utc_datetime(activity.start_time_utc):
                    continue
                matched = match_standard_distance(float(record.distance_m), tolerance_pct=0.01)
                if matched is None:
                    continue
                elapsed_seconds = record.elapsed_time_ms / 1_000
                existing = prior_bests.get(matched.distance)
                if existing is None or elapsed_seconds < existing:
                    prior_bests[matched.distance] = elapsed_seconds

            rows.append(
                PerformanceTrainingRow(
                    activity_id=activity.id,
                    activity_name=activity.name,
                    achieved_at=_utc_datetime(activity.start_time_utc),
                    matched_distance=candidate.matched_distance,
                    measured_distance_m=candidate.measured_distance_m,
                    recorded_elapsed_time_seconds=candidate.elapsed_time_seconds,
                    distance_deviation_pct=candidate.distance_deviation_pct,
                    review_status="verified" if verified is not None else "unreviewed",
                    review_label=(verified.verification_status if verified is not None else None),
                    verified_elapsed_time_seconds=(
                        verified.elapsed_time_ms / 1_000 if verified is not None else None
                    ),
                    review_notes=None,
                    prior_history_runs=len(prior_activities),
                    prior_history_days=(
                        (activity.local_start_date - prior_activities[0].local_start_date).days
                        if prior_activities
                        else 0
                    ),
                    prior_acute_load=(
                        _optional_float(previous_day_load.acute_load)
                        if previous_day_load is not None
                        else None
                    ),
                    prior_chronic_load=(
                        _optional_float(previous_day_load.chronic_load)
                        if previous_day_load is not None
                        else None
                    ),
                    prior_form_index=(
                        _optional_float(previous_day_load.form_index)
                        if previous_day_load is not None
                        else None
                    ),
                    prior_5k_best_seconds=prior_bests.get(StandardDistance.FIVE_K),
                    prior_10k_best_seconds=prior_bests.get(StandardDistance.TEN_K),
                    prior_half_marathon_best_seconds=prior_bests.get(
                        StandardDistance.HALF_MARATHON
                    ),
                    prior_marathon_best_seconds=prior_bests.get(StandardDistance.MARATHON),
                    training_windows=tuple(
                        _window_features(
                            activities=activities,
                            metrics_by_activity=metrics_by_activity,
                            candidate=activity,
                            days=days,
                        )
                        for days in TRAINING_WINDOWS_DAYS
                    ),
                )
            )

        verified_rows = sum(row.review_status == "verified" for row in rows)
        unreviewed_rows = len(rows) - verified_rows
        return PerformanceTrainingDataset(
            dataset_version=PERFORMANCE_FEATURE_DATASET_VERSION,
            audit_version=audit.audit_version,
            leakage_rule=(
                "Only activities before candidate start and workload through the prior local "
                "date may contribute features."
            ),
            candidate_rows=len(rows),
            verified_rows=verified_rows,
            unreviewed_rows=unreviewed_rows,
            model_status=("label_audit_required" if unreviewed_rows else "evaluation_required"),
            rows=tuple(rows),
        )

    def evidence(
        self,
        *,
        athlete_id: UUID,
        activity_id: UUID,
        target_distance: StandardDistance,
    ) -> PerformanceEvidence:
        """Derive the standard-distance crossing supported by stored trackpoints."""

        activity = self._session.scalar(
            select(Activity).where(
                Activity.id == activity_id,
                Activity.athlete_id == athlete_id,
                Activity.sport == "running",
                Activity.verification_status != "excluded",
            )
        )
        if activity is None:
            raise PerformanceAuditQueryError(
                "The requested eligible running activity does not exist."
            )

        trackpoints = tuple(
            self._session.scalars(
                select(Trackpoint)
                .where(
                    Trackpoint.activity_id == activity_id,
                    Trackpoint.distance_m.is_not(None),
                )
                .order_by(Trackpoint.sequence_number)
            )
        )
        samples = tuple(
            DistanceSample(
                elapsed_ms=trackpoint.elapsed_ms,
                distance_m=float(trackpoint.distance_m),
            )
            for trackpoint in trackpoints
            if trackpoint.distance_m is not None
        )

        return PerformanceEvidence(
            activity_id=activity.id,
            achieved_at=_utc_datetime(activity.start_time_utc),
            recorded_distance_m=float(activity.distance_m),
            recorded_elapsed_time_seconds=activity.elapsed_time_ms / 1_000,
            distance_samples=len(samples),
            target_distance=target_distance,
            derived_effort=calculate_standard_distance_effort(samples, target_distance),
            rolling_effort=calculate_fastest_rolling_distance_effort(
                samples,
                target_distance,
            ),
        )
