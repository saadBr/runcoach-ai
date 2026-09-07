"""End-to-end test for required Strava onboarding orchestration."""

import csv
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.db.base import Base
from runcoach.db.identity import NewAthleteRegistration, NewAthleteRegistrationService
from runcoach.db.models import (
    Activity,
    ActivityMetric,
    AthleteOnboarding,
    DailyLoad,
    PersonalBest,
    TrainingPlan,
    UserAccount,
)
from runcoach.onboarding.service import StravaOnboardingService

HEADER = [
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Elapsed Time",
    "Distance",
    "Filename",
    "Elapsed Time",
    "Moving Time",
    "Distance",
    "Elevation Gain",
    "Elevation Loss",
]


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _create_archive(path: Path) -> None:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    first_date = datetime(2026, 8, 29, 6, tzinfo=UTC)
    for index in range(10):
        activity_date = first_date + timedelta(days=index)
        distance_m = 5_000 if index == 3 else 8_000 + index * 250
        writer.writerow(
            [
                str(1_000 + index),
                activity_date.isoformat(),
                "5K benchmark" if index == 3 else f"Easy run {index + 1}",
                "Run",
                "display elapsed",
                "display distance",
                "",
                str(1_200 + index * 60),
                str(1_180 + index * 60),
                str(distance_m),
                "25",
                "25",
            ]
        )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("activities.csv", buffer.getvalue().encode("utf-8"))


def test_required_archive_produces_active_account_analytics_and_plan(
    db_session: Session,
    tmp_path: Path,
) -> None:
    registered = NewAthleteRegistrationService(db_session).register(
        NewAthleteRegistration(
            display_name="Onboarded Athlete",
            email="onboarded@example.com",
            password="onboarded private password",
            timezone="Africa/Casablanca",
            goal_distance=StandardDistance.MARATHON,
            race_date=date(2027, 1, 31),
            target_time_seconds=None,
            days_per_week=5,
            benchmark_distance=StandardDistance.FIVE_K,
            benchmark_elapsed_time_ms=1_200_000,
            benchmark_date=date(2026, 9, 1),
            benchmark_label=PerformanceLabel.VERIFIED_MAX_EFFORT,
        ),
        now=datetime(2026, 9, 7, 12, tzinfo=UTC),
        today=date(2026, 9, 7),
    )
    archive_path = tmp_path / "strava.zip"
    _create_archive(archive_path)

    completed = StravaOnboardingService(db_session).process_archive(
        athlete_id=registered.identity.athlete_id,
        archive_path=archive_path,
        extraction_directory=tmp_path / "extracted",
    )

    account = db_session.get(UserAccount, registered.identity.account_id)
    onboarding = db_session.get(AthleteOnboarding, registered.identity.athlete_id)
    assert completed.status == "ready"
    assert completed.canonical_runs == 10
    assert completed.sensor_runs == 0
    assert account is not None and account.status == "active"
    assert onboarding is not None and onboarding.status == "ready"
    assert onboarding.strava_import_batch_id is not None
    assert onboarding.training_plan_id == completed.plan_id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.athlete_id == registered.identity.athlete_id)
        )
        == 10
    )
    assert db_session.scalar(select(func.count()).select_from(PersonalBest)) == 1
    assert db_session.scalar(select(func.count()).select_from(ActivityMetric)) == 10
    daily_loads = db_session.scalar(select(func.count()).select_from(DailyLoad))
    assert daily_loads is not None and daily_loads > 0
    assert db_session.scalar(select(func.count()).select_from(TrainingPlan)) == 1
