"""Schema tests for multi-athlete identity, onboarding, and research consent."""

from sqlalchemy import CheckConstraint, String, Table, UniqueConstraint

from runcoach.db.base import Base
from runcoach.db.models import (
    AthleteOnboarding,
    AuthSession,
    ResearchConsent,
    UserAccount,
)


def _unique_column_sets(table: Table) -> set[frozenset[str]]:
    """Return columns covered by table-level unique constraints."""

    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_names(table: Table) -> set[str]:
    """Return explicitly named check constraints."""

    names: set[str] = set()
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and isinstance(constraint.name, str):
            names.add(constraint.name)
    return names


def test_identity_and_onboarding_tables_are_registered() -> None:
    assert {
        "user_accounts",
        "auth_sessions",
        "athlete_onboarding",
        "research_consents",
    } <= set(Base.metadata.tables)


def test_user_account_is_one_to_one_with_an_athlete() -> None:
    table = Base.metadata.tables[UserAccount.__tablename__]
    athlete_foreign_key = next(iter(table.c.athlete_id.foreign_keys))

    assert athlete_foreign_key.target_fullname == "athletes.id"
    assert frozenset({"athlete_id"}) in _unique_column_sets(table)
    assert frozenset({"email_normalized"}) in _unique_column_sets(table)
    assert "user_accounts_status" in _check_names(table)


def test_auth_session_persists_only_a_unique_token_hash() -> None:
    table = Base.metadata.tables[AuthSession.__tablename__]
    account_foreign_key = next(iter(table.c.user_account_id.foreign_keys))

    assert account_foreign_key.target_fullname == "user_accounts.id"
    assert "token" not in table.c
    assert isinstance(table.c.token_hash.type, String)
    assert table.c.token_hash.type.length == 64
    assert frozenset({"token_hash"}) in _unique_column_sets(table)
    assert {"auth_sessions_expiry", "auth_sessions_last_seen"} <= _check_names(table)


def test_onboarding_requires_strava_import_goal_and_plan_before_ready() -> None:
    table = Base.metadata.tables[AthleteOnboarding.__tablename__]

    assert table.c.athlete_id.primary_key
    assert table.c.strava_import_batch_id.nullable
    assert table.c.goal_id.nullable
    assert table.c.training_plan_id.nullable
    assert {
        "athlete_onboarding_status",
        "athlete_onboarding_ready",
        "athlete_onboarding_failure",
    } <= _check_names(table)


def test_onboarding_references_existing_import_and_plan_evidence() -> None:
    table = Base.metadata.tables[AthleteOnboarding.__tablename__]
    targets = {
        next(iter(table.c[column_name].foreign_keys)).target_fullname
        for column_name in ("strava_import_batch_id", "goal_id", "training_plan_id")
    }

    assert targets == {"import_batches.id", "goals.id", "training_plans.id"}


def test_research_consent_is_separate_and_append_only_by_schema() -> None:
    table = Base.metadata.tables[ResearchConsent.__tablename__]
    athlete_foreign_key = next(iter(table.c.athlete_id.foreign_keys))

    assert athlete_foreign_key.target_fullname == "athletes.id"
    assert "research_consents_decision" in _check_names(table)
    assert not _unique_column_sets(table)
