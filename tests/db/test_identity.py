"""Tests for credential hashing and existing-athlete account bootstrap."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.db.base import Base
from runcoach.db.identity import (
    ExistingAthleteAccountService,
    IdentityConflictError,
    IdentityError,
    hash_password,
    normalize_email,
    verify_password,
)
from runcoach.db.models import (
    Activity,
    Athlete,
    AthleteOnboarding,
    Goal,
    ImportBatch,
    ImportFile,
    ResearchConsent,
    TrainingPlan,
    UserAccount,
)

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")
GOAL_ID = UUID("018f0000-0000-7000-8000-000000000002")
PLAN_ID = UUID("018f0000-0000-7000-8000-000000000003")
BATCH_ID = UUID("018f0000-0000-7000-8000-000000000004")
FILE_ID = UUID("018f0000-0000-7000-8000-000000000005")
ACTIVITY_ID = UUID("018f0000-0000-7000-8000-000000000006")
TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            Athlete(
                id=ATHLETE_ID,
                display_name="Existing Athlete",
                timezone="Africa/Casablanca",
            )
        )
        session.add(
            Goal(
                id=GOAL_ID,
                athlete_id=ATHLETE_ID,
                race_type="marathon",
                race_date=date(2027, 1, 31),
                target_time_seconds=11_400,
                days_per_week=6,
                status="active",
                priority="primary",
            )
        )
        session.add(
            TrainingPlan(
                id=PLAN_ID,
                goal_id=GOAL_ID,
                version=1,
                algorithm_version="test_plan_v1",
                evidence_as_of_date=date(2026, 9, 7),
                evidence_hash="a" * 64,
                status="active",
                plan_payload={"weeks": []},
            )
        )
        session.add(
            ImportBatch(
                id=BATCH_ID,
                athlete_id=ATHLETE_ID,
                status="completed",
                parser_bundle_version="test_parser_v1",
                total_files=1,
                accepted_files=1,
            )
        )
        session.add(
            ImportFile(
                id=FILE_ID,
                import_batch_id=BATCH_ID,
                original_name="synthetic.fit",
                source_provider="strava",
                media_type="application/octet-stream",
                size_bytes=128,
                sha256="b" * 64,
                storage_key="private/synthetic.fit",
                status="accepted",
                detected_format="fit",
            )
        )
        session.add(
            Activity(
                id=ACTIVITY_ID,
                athlete_id=ATHLETE_ID,
                sport="running",
                name="Existing history",
                start_time_utc=datetime(2026, 9, 1, 6, tzinfo=UTC),
                original_timezone="Africa/Casablanca",
                local_start_date=date(2026, 9, 1),
                distance_m=10_000,
                moving_time_ms=3_600_000,
                elapsed_time_ms=3_600_000,
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_email_normalization_is_stable_and_rejects_invalid_values() -> None:
    assert normalize_email("  ATHLETE@Example.COM ") == "athlete@example.com"

    for value in ("", "athlete", "@example.com", "athlete@localhost", "a b@example.com"):
        with pytest.raises(ValueError, match="valid email"):
            normalize_email(value)


def test_password_hash_is_salted_versioned_and_verifiable() -> None:
    first = hash_password(TEST_PASSWORD, salt=b"a" * 16)
    second = hash_password(TEST_PASSWORD, salt=b"b" * 16)

    assert first.startswith("scrypt$1$")
    assert first != second
    assert verify_password(TEST_PASSWORD, first)
    assert not verify_password("incorrect password", first)
    assert not verify_password(TEST_PASSWORD, "invalid")
    assert TEST_PASSWORD not in first


def test_password_policy_rejects_short_and_invalid_salt() -> None:
    with pytest.raises(ValueError, match="at least"):
        hash_password("too short")
    with pytest.raises(ValueError, match="salt"):
        hash_password(TEST_PASSWORD, salt=b"short")


def test_bootstrap_preserves_existing_profile_history_goal_and_plan(
    db_session: Session,
) -> None:
    result = ExistingAthleteAccountService(db_session).bootstrap(
        athlete_id=ATHLETE_ID,
        email="Athlete@Example.com",
        password=TEST_PASSWORD,
    )

    athlete = db_session.get(Athlete, ATHLETE_ID)
    account = db_session.get(UserAccount, result.account_id)
    onboarding = db_session.get(AthleteOnboarding, ATHLETE_ID)

    assert result.created
    assert result.account_status == "active"
    assert result.onboarding_status == "ready"
    assert athlete is not None
    assert athlete.display_name == "Existing Athlete"
    assert db_session.get(Activity, ACTIVITY_ID) is not None
    assert db_session.get(Goal, GOAL_ID) is not None
    assert db_session.get(TrainingPlan, PLAN_ID) is not None
    assert account is not None
    assert account.athlete_id == ATHLETE_ID
    assert account.email_normalized == "athlete@example.com"
    assert verify_password(TEST_PASSWORD, account.password_hash)
    assert onboarding is not None
    assert onboarding.strava_import_batch_id == BATCH_ID
    assert onboarding.goal_id == GOAL_ID
    assert onboarding.training_plan_id == PLAN_ID
    assert db_session.scalar(select(func.count()).select_from(ResearchConsent)) == 0


def test_bootstrap_is_idempotent_only_for_matching_credentials(db_session: Session) -> None:
    service = ExistingAthleteAccountService(db_session)
    first = service.bootstrap(
        athlete_id=ATHLETE_ID,
        email="athlete@example.com",
        password=TEST_PASSWORD,
    )
    second = service.bootstrap(
        athlete_id=ATHLETE_ID,
        email="ATHLETE@example.com",
        password=TEST_PASSWORD,
    )

    assert first.account_id == second.account_id
    assert not second.created
    assert db_session.scalar(select(func.count()).select_from(UserAccount)) == 1
    assert db_session.scalar(select(func.count()).select_from(AthleteOnboarding)) == 1
    db_session.commit()

    with pytest.raises(IdentityConflictError, match="different credentials"):
        service.bootstrap(
            athlete_id=ATHLETE_ID,
            email="athlete@example.com",
            password="a different secure password",
        )


def test_bootstrap_rolls_back_when_required_existing_evidence_is_missing(
    db_session: Session,
) -> None:
    plan = db_session.get(TrainingPlan, PLAN_ID)
    assert plan is not None
    db_session.delete(plan)
    db_session.commit()

    with pytest.raises(IdentityError, match="active training plan"):
        ExistingAthleteAccountService(db_session).bootstrap(
            athlete_id=ATHLETE_ID,
            email="athlete@example.com",
            password=TEST_PASSWORD,
        )

    assert db_session.scalar(select(func.count()).select_from(UserAccount)) == 0
    assert db_session.scalar(select(func.count()).select_from(AthleteOnboarding)) == 0
