"""Read-only verified-performance queries for the analytical dashboard."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach.analytics.current_fitness import (
    CurrentFitnessAssessment,
    FitnessMark,
    TrainingProfile,
    estimate_current_fitness,
)
from runcoach.analytics.performance import (
    DEFAULT_DISTANCE_TOLERANCE_PCT,
    DistanceSample,
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
    VerifiedPerformance,
    calculate_fastest_rolling_distance_effort,
    standard_distance_meters,
)
from runcoach.analytics.performance_evidence import (
    PERFORMANCE_EVIDENCE_VERSION,
    ActivityPerformanceCandidate,
    PerformanceEvidenceKind,
    SelectedPerformanceEvidence,
    select_activity_performance_evidence,
)
from runcoach.analytics.session_classification import classify_session
from runcoach.db.models import Activity, Athlete, PersonalBest, Trackpoint

DISTANCE_BY_METERS = {
    Decimal("5000.000"): StandardDistance.FIVE_K,
    Decimal("10000.000"): StandardDistance.TEN_K,
    Decimal("21097.500"): StandardDistance.HALF_MARATHON,
    Decimal("42195.000"): StandardDistance.MARATHON,
}


class PerformanceQueryError(RuntimeError):
    """Raised when verified performance evidence is unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class PersonalBestSummary:
    """One active verified personal best and its evidence reference."""

    personal_best_id: UUID
    activity_id: UUID
    distance: StandardDistance
    distance_m: float
    elapsed_time_seconds: float
    pace_seconds_per_km: float
    achieved_at: datetime
    verification_status: PerformanceLabel
    effort_type: PerformanceEffortType
    verification_source: str
    algorithm_version: str


@dataclass(frozen=True, slots=True)
class PerformanceOverview:
    """Current verified personal bests and experimental current-fitness evidence."""

    personal_bests: tuple[PersonalBestSummary, ...]
    current_fitness: CurrentFitnessAssessment
    prediction_status: str
    prediction_method: str
    verified_labels: int
    interpretation_role: str
    limitations: tuple[str, ...]
    evidence_selection_version: str = PERFORMANCE_EVIDENCE_VERSION
    performance_evidence: tuple[SelectedPerformanceEvidence, ...] = ()


def _standard_distance(distance_m: Decimal) -> StandardDistance:
    try:
        return DISTANCE_BY_METERS[distance_m]
    except KeyError as error:
        raise PerformanceQueryError(
            "A current personal best uses an unsupported standard distance."
        ) from error


def _utc_datetime(value: datetime) -> datetime:
    """Preserve PostgreSQL timestamps and normalize SQLite test values as UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _training_profile(
    *,
    activities: tuple[Activity, ...],
    as_of_date: date,
) -> TrainingProfile:
    def window(days: int) -> tuple[Activity, ...]:
        start_date = as_of_date - timedelta(days=days - 1)
        return tuple(
            activity
            for activity in activities
            if start_date <= activity.local_start_date <= as_of_date
        )

    activities_28d = window(28)
    activities_84d = window(84)
    activities_168d = window(168)
    activities_365d = window(365)
    classifications = tuple(classify_session(activity.name) for activity in activities_84d)

    return TrainingProfile(
        as_of_date=as_of_date,
        runs_28d=len(activities_28d),
        distance_28d_km=round(
            sum(float(activity.distance_m) for activity in activities_28d) / 1_000,
            6,
        ),
        runs_84d=len(activities_84d),
        distance_84d_km=round(
            sum(float(activity.distance_m) for activity in activities_84d) / 1_000,
            6,
        ),
        longest_run_84d_km=(
            round(
                max(float(activity.distance_m) for activity in activities_84d) / 1_000,
                6,
            )
            if activities_84d
            else None
        ),
        classified_sessions_84d=sum(
            classification.normalized_title != ""
            and classification.primary_kind.value != "unclassified"
            for classification in classifications
        ),
        quality_sessions_84d=sum(
            classification.is_quality_session for classification in classifications
        ),
        runs_168d=len(activities_168d),
        distance_168d_km=round(
            sum(float(activity.distance_m) for activity in activities_168d) / 1_000,
            6,
        ),
        runs_365d=len(activities_365d),
        distance_365d_km=round(
            sum(float(activity.distance_m) for activity in activities_365d) / 1_000,
            6,
        ),
    )


def _observed_best_effort_marks(
    *,
    session: Session,
    activities: tuple[Activity, ...],
) -> tuple[FitnessMark, ...]:
    """Derive provisional best efforts from imported activity evidence."""

    candidates_by_distance: dict[StandardDistance, tuple[Activity, ...]] = {}
    for distance in StandardDistance:
        target_m = standard_distance_meters(distance)
        candidates = tuple(
            activity
            for activity in activities
            if float(activity.distance_m) >= target_m * (1 - DEFAULT_DISTANCE_TOLERANCE_PCT / 100)
            and activity.elapsed_time_ms > 0
        )
        if candidates:
            candidates_by_distance[distance] = candidates

    candidate_ids = {
        activity.id for candidates in candidates_by_distance.values() for activity in candidates
    }
    samples_by_activity: dict[UUID, list[DistanceSample]] = defaultdict(list)
    if candidate_ids:
        for activity_id, elapsed_ms, distance_m in session.execute(
            select(Trackpoint.activity_id, Trackpoint.elapsed_ms, Trackpoint.distance_m)
            .where(
                Trackpoint.activity_id.in_(candidate_ids),
                Trackpoint.distance_m.is_not(None),
            )
            .order_by(Trackpoint.activity_id, Trackpoint.sequence_number)
        ).yield_per(1_000):
            if distance_m is not None:
                samples_by_activity[activity_id].append(
                    DistanceSample(elapsed_ms=elapsed_ms, distance_m=float(distance_m))
                )
    activity_samples = {
        activity_id: tuple(samples) for activity_id, samples in samples_by_activity.items()
    }

    marks: list[FitnessMark] = []
    for distance, candidates in candidates_by_distance.items():
        target_m = standard_distance_meters(distance)
        best: tuple[float, Activity, PerformanceEffortType] | None = None
        for activity in candidates:
            samples = activity_samples.get(activity.id, ())
            try:
                rolling = calculate_fastest_rolling_distance_effort(samples, distance)
            except ValueError:
                rolling = None
            if rolling is not None:
                elapsed_seconds = rolling.elapsed_time_seconds
                effort_type = PerformanceEffortType.ROLLING_SEGMENT
            else:
                measured_distance_m = float(activity.distance_m)
                deviation_pct = abs(measured_distance_m - target_m) / target_m * 100
                if deviation_pct > DEFAULT_DISTANCE_TOLERANCE_PCT:
                    continue
                elapsed_seconds = (
                    activity.elapsed_time_ms / 1_000 * (target_m / measured_distance_m)
                )
                effort_type = PerformanceEffortType.WHOLE_ACTIVITY

            candidate = (elapsed_seconds, activity, effort_type)
            if best is None or (candidate[0], -candidate[1].local_start_date.toordinal()) < (
                best[0],
                -best[1].local_start_date.toordinal(),
            ):
                best = candidate

        if best is None:
            continue
        elapsed_seconds, activity, effort_type = best
        marks.append(
            FitnessMark(
                distance=distance,
                elapsed_time_seconds=round(elapsed_seconds, 6),
                achieved_on=activity.local_start_date,
                verification_status=PerformanceLabel.VERIFIED_MAX_EFFORT,
                effort_type=effort_type,
                activity_distance_km=round(float(activity.distance_m) / 1_000, 6),
                session_kind=classify_session(activity.name).primary_kind,
                is_verified=False,
            )
        )
    return tuple(marks)


class PerformanceQueryService:
    """Read verified PBs and build an auditable experimental fitness estimate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def overview(self, *, athlete_id: UUID) -> PerformanceOverview:
        """Return current PBs and the training-model readiness state."""

        if self._session.get(Athlete, athlete_id) is None:
            raise PerformanceQueryError("The configured athlete does not exist.")

        all_records = tuple(
            self._session.scalars(
                select(PersonalBest)
                .where(PersonalBest.athlete_id == athlete_id)
                .order_by(PersonalBest.distance_m, PersonalBest.achieved_at)
            )
        )
        records = tuple(record for record in all_records if record.superseded_at is None)
        if not records:
            raise PerformanceQueryError("No verified personal bests are available.")

        summaries: list[PersonalBestSummary] = []
        observed_distances: set[StandardDistance] = set()

        for record in records:
            distance = _standard_distance(record.distance_m)
            if distance in observed_distances:
                raise PerformanceQueryError(
                    f"Multiple current personal bests exist for {distance.value}."
                )
            observed_distances.add(distance)

            achieved_at = _utc_datetime(record.achieved_at)
            elapsed_time_seconds = record.elapsed_time_ms / 1_000
            performance = VerifiedPerformance(
                activity_id=record.activity_id,
                distance=distance,
                elapsed_time_seconds=elapsed_time_seconds,
                achieved_at=achieved_at,
                label=PerformanceLabel(record.verification_status),
            )
            summaries.append(
                PersonalBestSummary(
                    personal_best_id=record.id,
                    activity_id=record.activity_id,
                    distance=distance,
                    distance_m=standard_distance_meters(distance),
                    elapsed_time_seconds=elapsed_time_seconds,
                    pace_seconds_per_km=round(
                        elapsed_time_seconds / (standard_distance_meters(distance) / 1_000),
                        6,
                    ),
                    achieved_at=achieved_at,
                    verification_status=performance.label,
                    effort_type=PerformanceEffortType(record.effort_type),
                    verification_source=record.verification_source,
                    algorithm_version=record.algorithm_version,
                )
            )

        activities = tuple(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.athlete_id == athlete_id,
                    Activity.sport == "running",
                    Activity.verification_status != "excluded",
                )
                .order_by(Activity.local_start_date, Activity.id)
            )
        )
        if not activities:
            raise PerformanceQueryError("No running history is available for estimation.")

        activity_by_id = {activity.id: activity for activity in activities}

        verified_evidence: list[SelectedPerformanceEvidence] = []
        active_record_ids = {record.id for record in records}
        for record in all_records:
            activity = activity_by_id.get(record.activity_id)
            if activity is None:
                continue
            distance = _standard_distance(record.distance_m)
            elapsed_time_seconds = record.elapsed_time_ms / 1_000
            verified_evidence.append(
                SelectedPerformanceEvidence(
                    activity_id=activity.id,
                    activity_name=activity.name,
                    achieved_on=_utc_datetime(record.achieved_at).date(),
                    evidence_kind=(
                        PerformanceEvidenceKind.VERIFIED_PERSONAL_BEST
                        if record.id in active_record_ids
                        else PerformanceEvidenceKind.VERIFIED_HISTORY
                    ),
                    target_distance=distance,
                    activity_distance_km=round(float(activity.distance_m) / 1_000, 6),
                    elapsed_time_seconds=round(elapsed_time_seconds, 3),
                    pace_seconds_per_km=round(
                        elapsed_time_seconds / (standard_distance_meters(distance) / 1_000),
                        6,
                    ),
                    session_kind=classify_session(activity.name).primary_kind,
                    reason=(
                        "Athlete-confirmed active personal best at this standard distance."
                        if record.id in active_record_ids
                        else "Athlete-confirmed historical performance retained for progression."
                    ),
                )
            )

        activity_evidence = select_activity_performance_evidence(
            tuple(
                ActivityPerformanceCandidate(
                    activity_id=activity.id,
                    name=activity.name,
                    achieved_on=activity.local_start_date,
                    distance_km=float(activity.distance_m) / 1_000,
                    moving_time_seconds=activity.moving_time_ms / 1_000,
                    elapsed_time_seconds=activity.elapsed_time_ms / 1_000,
                    activity_type=activity.activity_type,
                    session_kind=classify_session(activity.name).primary_kind,
                )
                for activity in activities
                if activity.distance_m > 0
                and activity.moving_time_ms > 0
                and activity.elapsed_time_ms > 0
            ),
            already_verified_activity_ids=frozenset(record.activity_id for record in all_records),
        )
        performance_evidence = tuple(
            sorted(
                (*verified_evidence, *activity_evidence),
                key=lambda item: (
                    item.achieved_on,
                    item.evidence_kind,
                    str(item.activity_id),
                ),
                reverse=True,
            )
        )

        def fitness_mark(record: PersonalBest) -> FitnessMark:
            activity = activity_by_id.get(record.activity_id)
            if activity is None:
                raise PerformanceQueryError(
                    "A verified personal best is not linked to running history."
                )
            return FitnessMark(
                distance=_standard_distance(record.distance_m),
                elapsed_time_seconds=record.elapsed_time_ms / 1_000,
                achieved_on=_utc_datetime(record.achieved_at).date(),
                verification_status=PerformanceLabel(record.verification_status),
                effort_type=PerformanceEffortType(record.effort_type),
                activity_distance_km=round(float(activity.distance_m) / 1_000, 6),
                session_kind=classify_session(activity.name).primary_kind,
            )

        verified_marks = tuple(fitness_mark(record) for record in records)
        observed_marks = _observed_best_effort_marks(
            session=self._session,
            activities=activities,
        )
        verified_by_distance = {mark.distance: mark for mark in verified_marks}
        observed_by_distance = {mark.distance: mark for mark in observed_marks}
        marks = tuple(
            min(
                (
                    mark
                    for mark in (
                        verified_by_distance.get(distance),
                        observed_by_distance.get(distance),
                    )
                    if mark is not None
                ),
                key=lambda mark: (mark.elapsed_time_seconds, not mark.is_verified),
            )
            for distance in StandardDistance
            if distance in verified_by_distance or distance in observed_by_distance
        )
        anchor = max(marks, key=lambda mark: mark.achieved_on)
        older_anchor_records = tuple(
            record
            for record in all_records
            if _standard_distance(record.distance_m) is anchor.distance
            and _utc_datetime(record.achieved_at).date() < anchor.achieved_on
        )
        prior_anchor_record = (
            min(older_anchor_records, key=lambda record: record.elapsed_time_ms)
            if older_anchor_records
            else None
        )
        prior_anchor = (
            fitness_mark(prior_anchor_record) if prior_anchor_record is not None else None
        )

        as_of_date = max(activity.local_start_date for activity in activities)
        current_training = _training_profile(
            activities=activities,
            as_of_date=as_of_date,
        )
        reference_training_by_distance = {
            mark.distance: _training_profile(
                activities=activities,
                as_of_date=mark.achieved_on - timedelta(days=1),
            )
            for mark in marks
        }
        current_fitness = estimate_current_fitness(
            current_marks=marks,
            anchor=anchor,
            prior_anchor=prior_anchor,
            training=current_training,
            reference_training_by_distance=reference_training_by_distance,
        )

        return PerformanceOverview(
            personal_bests=tuple(summaries),
            current_fitness=current_fitness,
            prediction_status=current_fitness.status,
            prediction_method=current_fitness.algorithm_version,
            verified_labels=len(summaries),
            interpretation_role="openai_explains_validated_outputs_only",
            limitations=current_fitness.limitations,
            evidence_selection_version=PERFORMANCE_EVIDENCE_VERSION,
            performance_evidence=performance_evidence,
        )
