"""Resumable orchestration for required Strava-history onboarding."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from runcoach import __version__
from runcoach.analytics.performance import (
    PerformanceEffortType,
    PerformanceLabel,
    StandardDistance,
    standard_distance_meters,
)
from runcoach.db.analytics import AnalyticsPersistenceError, DeterministicAnalyticsService
from runcoach.db.ingestion import ImportFileDescriptor, ReconciliationPersistenceService
from runcoach.db.models import Activity, Athlete, AthleteOnboarding, Goal, UserAccount
from runcoach.db.personal_bests import PersonalBestError, PersonalBestInput, PersonalBestService
from runcoach.db.sensors import (
    SensorActivityInput,
    SensorPersistenceError,
    SensorPersistenceService,
)
from runcoach.db.training_plans import (
    TrainingPlanPersistenceError,
    TrainingPlanPersistenceService,
    TrainingPlanQueryError,
)
from runcoach.ingestion.contracts import FindingSeverity, NormalizedActivity, SourceProvider
from runcoach.ingestion.fit import parse_fit_activity
from runcoach.ingestion.gpx import parse_gpx_activity
from runcoach.ingestion.reconciliation import reconcile_activity_summaries
from runcoach.ingestion.strava_csv import parse_strava_activities_csv
from runcoach.ingestion.strava_fit import infer_activity_type, single_running_activity
from runcoach.onboarding.strava_archive import (
    ExtractedArchiveMember,
    StravaArchiveError,
    extract_strava_archive,
)

MINIMUM_RUNNING_HISTORY = 10
ONBOARDING_BENCHMARK_SOURCE = "athlete_declared_strava_best_effort"
ONBOARDING_BENCHMARK_VERSION = "onboarding_benchmark_v1"


class OnboardingError(RuntimeError):
    """Raised with a sanitized code when onboarding cannot advance safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CompletedOnboarding:
    """Privacy-minimized result of a completed onboarding pipeline."""

    status: str
    canonical_runs: int
    sensor_runs: int
    parser_findings: int
    plan_id: UUID


@dataclass(frozen=True, slots=True)
class _OnboardingConfiguration:
    """Stable values copied before independently committed onboarding stages."""

    goal_distance: StandardDistance
    race_date: date
    target_time_seconds: float | None
    days_per_week: int
    benchmark_distance: StandardDistance
    benchmark_elapsed_time_ms: int
    benchmark_date: date
    benchmark_label: PerformanceLabel


def _logical_name(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").casefold()


def _prepare_sensor_input(
    *,
    member: ExtractedArchiveMember,
    summary: NormalizedActivity,
    athlete_id: UUID,
    timezone_name: str,
) -> tuple[SensorActivityInput | None, int]:
    source_activity_id = summary.source.source_activity_id
    source_row_number = summary.source.source_row_number
    if member.logical_name.casefold().endswith(".gpx"):
        result = parse_gpx_activity(
            member.path,
            athlete_id,
            activity_kind=summary.activity_kind,
            source_activity_id=source_activity_id,
            source_row_number=source_row_number,
        )
    else:
        result = parse_fit_activity(
            member.path,
            athlete_id,
            SourceProvider.STRAVA,
            source_activity_id=source_activity_id,
            source_row_number=source_row_number,
            activity_kind_override=summary.activity_kind,
        )
    normalized = single_running_activity(result.activities)
    if normalized is None:
        return None, len(result.findings)
    normalized = normalized.model_copy(
        update={
            "name": summary.name,
            "timezone_name": timezone_name,
            "source": normalized.source.model_copy(
                update={
                    "source_file_name": member.logical_name,
                    "source_activity_id": source_activity_id,
                    "source_row_number": source_row_number,
                }
            ),
        }
    )
    return (
        SensorActivityInput(
            file=ImportFileDescriptor(
                provider=SourceProvider.STRAVA,
                source_format=normalized.source.source_format,
                source_file_name=member.logical_name,
                content_sha256=normalized.source.content_sha256,
                storage_key=f"strava/onboarding/{normalized.source.content_sha256}",
                size_bytes=member.size_bytes,
                media_type="application/octet-stream",
            ),
            activity=normalized,
            activity_type=infer_activity_type(summary.name or ""),
        ),
        len(result.findings),
    )


class StravaOnboardingService:
    """Advance one pending account through archive import, analytics, and planning."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def process_archive(
        self,
        *,
        athlete_id: UUID,
        archive_path: Path,
        extraction_directory: Path,
    ) -> CompletedOnboarding:
        """Process one bounded archive; completed stages remain safe to retry."""

        try:
            configuration = self._load_pending(athlete_id)
            self._set_status(athlete_id, "validating_archive")
            extracted = extract_strava_archive(archive_path, extraction_directory)

            self._set_status(athlete_id, "importing_history")
            parsed = parse_strava_activities_csv(extracted.activities_csv.path, athlete_id)
            running = tuple(
                activity
                for activity in parsed.activities
                if activity.activity_kind.value.endswith("running")
            )
            if any(
                finding.severity is FindingSeverity.ERROR
                and finding.code == "STRAVA_HEADER_INVALID"
                for finding in parsed.findings
            ):
                raise OnboardingError(
                    "ACTIVITIES_CSV_INVALID",
                    "The Strava activities.csv schema could not be validated.",
                )
            if len(running) < MINIMUM_RUNNING_HISTORY:
                raise OnboardingError(
                    "INSUFFICIENT_RUNNING_HISTORY",
                    "The archive must contain at least "
                    f"{MINIMUM_RUNNING_HISTORY} running activities.",
                )

            reconciled = reconcile_activity_summaries(
                strava_activities=parsed.activities,
                garmin_activities=(),
            )
            descriptor = ImportFileDescriptor(
                provider=SourceProvider.STRAVA,
                source_format=parsed.activities[0].source.source_format,
                source_file_name="activities.csv",
                content_sha256=parsed.activities[0].source.content_sha256,
                storage_key=f"strava/onboarding/{parsed.activities[0].source.content_sha256}",
                size_bytes=extracted.activities_csv.size_bytes,
                media_type="text/csv",
            )
            athlete_timezone = self._athlete_timezone(athlete_id)
            self._session.rollback()
            import_summary = ReconciliationPersistenceService(self._session).persist(
                athlete_id=athlete_id,
                athlete_timezone=athlete_timezone.key,
                parser_bundle_version=f"runcoach-{__version__}",
                files=(descriptor,),
                result=reconciled,
            )

            summary_by_file = {
                _logical_name(activity.source.referenced_file_name): activity
                for activity in running
                if activity.source.referenced_file_name is not None
            }
            sensor_inputs: list[SensorActivityInput] = []
            parser_findings = len(parsed.findings)
            for member in extracted.sensor_files:
                summary = summary_by_file.get(_logical_name(member.logical_name))
                if summary is None:
                    continue
                prepared, findings = _prepare_sensor_input(
                    member=member,
                    summary=summary,
                    athlete_id=athlete_id,
                    timezone_name=athlete_timezone.key,
                )
                parser_findings += findings
                if prepared is not None:
                    sensor_inputs.append(prepared)

            if sensor_inputs:
                self._session.rollback()
                SensorPersistenceService(self._session).persist(
                    athlete_id=athlete_id,
                    parser_bundle_version=f"runcoach-{__version__}",
                    inputs=tuple(sensor_inputs),
                    create_missing_strava_activities=False,
                )

            self._record_benchmark(athlete_id, configuration)
            self._set_status(athlete_id, "calculating_analytics")
            latest_date = self._latest_activity_date(athlete_id)
            self._session.rollback()
            DeterministicAnalyticsService(self._session).calculate(
                athlete_id=athlete_id,
                as_of_date=latest_date,
            )

            self._set_status(athlete_id, "generating_plan")
            self._session.rollback()
            plan = TrainingPlanPersistenceService(self._session).create_or_refresh(
                athlete_id=athlete_id,
                distance=configuration.goal_distance,
                race_date=configuration.race_date,
                target_time_seconds=configuration.target_time_seconds,
                days_per_week=configuration.days_per_week,
            )
            self._complete(
                athlete_id=athlete_id,
                import_batch_id=import_summary.import_batch_id,
                plan_id=plan.plan_id,
            )
            return CompletedOnboarding(
                status="ready",
                canonical_runs=len(reconciled.activities),
                sensor_runs=len(sensor_inputs),
                parser_findings=parser_findings,
                plan_id=plan.plan_id,
            )
        except StravaArchiveError as error:
            self._fail(athlete_id, error.code)
            raise OnboardingError(error.code, str(error)) from error
        except OnboardingError as error:
            self._fail(athlete_id, error.code)
            raise
        except (
            AnalyticsPersistenceError,
            PersonalBestError,
            SensorPersistenceError,
            TrainingPlanPersistenceError,
            TrainingPlanQueryError,
            ValueError,
        ) as error:
            self._fail(athlete_id, "ONBOARDING_PIPELINE_FAILED")
            raise OnboardingError(
                "ONBOARDING_PIPELINE_FAILED",
                "The Strava history could not produce a complete initial plan.",
            ) from error

    def _load_pending(self, athlete_id: UUID) -> _OnboardingConfiguration:
        onboarding = self._session.get(AthleteOnboarding, athlete_id)
        if onboarding is None:
            raise OnboardingError("ONBOARDING_NOT_FOUND", "Onboarding state was not found.")
        if onboarding.status == "ready":
            raise OnboardingError("ONBOARDING_COMPLETE", "Onboarding is already complete.")
        if onboarding.goal_id is None:
            raise OnboardingError("GOAL_NOT_FOUND", "The onboarding goal was not found.")
        goal = self._session.get(Goal, onboarding.goal_id)
        if goal is None or goal.athlete_id != athlete_id:
            raise OnboardingError("GOAL_NOT_FOUND", "The onboarding goal was not found.")
        if (
            onboarding.benchmark_distance is None
            or onboarding.benchmark_elapsed_time_ms is None
            or onboarding.benchmark_date is None
            or onboarding.benchmark_label is None
        ):
            raise OnboardingError(
                "BENCHMARK_REQUIRED",
                "A verified Strava benchmark is required before generating a plan.",
            )
        return _OnboardingConfiguration(
            goal_distance=StandardDistance(goal.race_type),
            race_date=goal.race_date,
            target_time_seconds=(
                float(goal.target_time_seconds) if goal.target_time_seconds is not None else None
            ),
            days_per_week=goal.days_per_week,
            benchmark_distance=StandardDistance(onboarding.benchmark_distance),
            benchmark_elapsed_time_ms=onboarding.benchmark_elapsed_time_ms,
            benchmark_date=onboarding.benchmark_date,
            benchmark_label=PerformanceLabel(onboarding.benchmark_label),
        )

    def _athlete_timezone(self, athlete_id: UUID) -> ZoneInfo:
        athlete = self._session.get(Athlete, athlete_id)
        if athlete is None:
            raise OnboardingError("ATHLETE_NOT_FOUND", "The athlete profile was not found.")
        return ZoneInfo(athlete.timezone)

    def _record_benchmark(
        self,
        athlete_id: UUID,
        configuration: _OnboardingConfiguration,
    ) -> None:
        minimum_distance = Decimal(
            str(standard_distance_meters(configuration.benchmark_distance) * 0.95)
        )
        candidates = tuple(
            self._session.scalars(
                select(Activity).where(
                    Activity.athlete_id == athlete_id,
                    Activity.sport == "running",
                    Activity.verification_status != "excluded",
                    Activity.local_start_date == configuration.benchmark_date,
                    Activity.distance_m >= minimum_distance,
                )
            )
        )
        if len(candidates) != 1:
            raise OnboardingError(
                "BENCHMARK_ACTIVITY_NOT_UNIQUE",
                "The benchmark date must match exactly one eligible Strava run.",
            )
        activity_id = candidates[0].id
        self._session.rollback()
        PersonalBestService(self._session).record(
            PersonalBestInput(
                athlete_id=athlete_id,
                activity_id=activity_id,
                distance=configuration.benchmark_distance,
                elapsed_time_ms=configuration.benchmark_elapsed_time_ms,
                label=configuration.benchmark_label,
                effort_type=PerformanceEffortType.PROVIDER_BEST_EFFORT,
                verification_source=ONBOARDING_BENCHMARK_SOURCE,
                algorithm_version=ONBOARDING_BENCHMARK_VERSION,
            )
        )

    def _latest_activity_date(self, athlete_id: UUID) -> date:
        latest = self._session.scalar(
            select(Activity.local_start_date)
            .where(Activity.athlete_id == athlete_id, Activity.verification_status != "excluded")
            .order_by(Activity.local_start_date.desc())
            .limit(1)
        )
        if latest is None:
            raise OnboardingError(
                "RUNNING_HISTORY_REQUIRED",
                "No eligible running history was imported.",
            )
        return latest

    def _set_status(self, athlete_id: UUID, status: str) -> None:
        self._session.rollback()
        with self._session.begin():
            onboarding = self._session.get(AthleteOnboarding, athlete_id)
            if onboarding is None:
                raise OnboardingError("ONBOARDING_NOT_FOUND", "Onboarding state was not found.")
            onboarding.status = status
            onboarding.failure_code = None

    def _complete(self, *, athlete_id: UUID, import_batch_id: UUID, plan_id: UUID) -> None:
        self._session.rollback()
        with self._session.begin():
            onboarding = self._session.get(AthleteOnboarding, athlete_id)
            account = self._session.scalar(
                select(UserAccount).where(UserAccount.athlete_id == athlete_id)
            )
            if onboarding is None or account is None:
                raise OnboardingError(
                    "ONBOARDING_NOT_FOUND",
                    "Onboarding state was not found.",
                )
            onboarding.status = "ready"
            onboarding.strava_import_batch_id = import_batch_id
            onboarding.training_plan_id = plan_id
            onboarding.failure_code = None
            onboarding.completed_at = datetime.now(UTC)
            account.status = "active"

    def _fail(self, athlete_id: UUID, code: str) -> None:
        self._session.rollback()
        try:
            with self._session.begin():
                onboarding = self._session.get(AthleteOnboarding, athlete_id)
                if onboarding is not None and onboarding.status != "ready":
                    onboarding.status = "failed"
                    onboarding.failure_code = code[:64]
        except Exception:
            self._session.rollback()
